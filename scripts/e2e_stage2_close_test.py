#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Stage 2 E2E: inject a trade_plan then force-close in PAPER/BACKTEST.

Why this script exists:
- Stage 1 smoke test usually verifies ENTRY only.
- Stage 2 requires Telegram close message to include PnL + consecutive loss count.

This script:
1) Injects a trade_plan (same schema as scripts/e2e_smoke_test.py)
2) Waits for execution-service to create the position (PAPER/BACKTEST fills immediately)
3) Calls close_position_market() to generate POSITION_CLOSED execution_report with pnl_usdt
4) Prints related execution_report/risk_event messages from Redis

Run it inside docker (recommended):
  docker compose exec trading-ci-api-1 python scripts/e2e_stage2_close_test.py --env-file .env

Important:
- Set EXECUTION_MODE=PAPER (or BACKTEST) in .env / compose env.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import redis


DEFAULT_GROUP = "bot-group"


def _load_env_file(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path or not os.path.exists(path):
        return out
    for line in open(path, "r", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass
class RedisCtx:
    r: redis.Redis
    group: str


def redis_connect(redis_url: str) -> RedisCtx:
    r = redis.Redis.from_url(redis_url, decode_responses=True)
    r.ping()
    group = os.getenv("REDIS_STREAM_GROUP", DEFAULT_GROUP)
    return RedisCtx(r=r, group=group)


def xrevrange_latest_event(r: redis.Redis, stream: str, count: int = 50) -> list[dict]:
    out: list[dict] = []
    items = r.xrevrange(stream, max="+", min="-", count=count)
    for msg_id, fields in items:
        raw = fields.get("json") or fields.get("data")
        if raw is None:
            evt = {"_fields": fields}
        else:
            try:
                evt = json.loads(raw)
            except Exception:
                evt = {"_raw": raw}
        out.append({"id": msg_id, "event": evt})
    return out


def publish_event(r: redis.Redis, stream: str, event: Dict[str, Any], event_type: Optional[str] = None) -> str:
    payload: Dict[str, Any] = {"json": json.dumps(event, ensure_ascii=False)}
    if event_type:
        payload["type"] = event_type
    return r.xadd(stream, payload)


def build_trade_plan(env: str) -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    plan_id = f"stage2-{uuid.uuid4().hex[:12]}"
    idem = f"idem-{uuid.uuid4().hex}"

    symbol = os.getenv("SMOKE_SYMBOL", "BCHUSDT")
    timeframe = os.getenv("SMOKE_TIMEFRAME", "15m")
    side = os.getenv("SMOKE_SIDE", "SELL")  # default short (matches sample)
    entry = float(os.getenv("SMOKE_ENTRY_PRICE", "617.5"))
    sl = float(os.getenv("SMOKE_SL_PRICE", "630"))

    event = {
        "event_id": f"evt-{uuid.uuid4().hex}",
        "ts_ms": now_ms,
        "env": env,
        "service": "strategy-service",
        "schema_version": 1,
        "payload": {
            "plan_id": plan_id,
            "idempotency_key": idem,
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "entry_price": entry,
            "primary_sl_price": sl,
            "tp_rules": {
                "tp1": {"r": 1.0, "pct": 0.4},
                "tp2": {"r": 2.0, "pct": 0.4},
                "tp3_trail": {"pct": 0.2, "mode": "ATR"},
                "reduce_only": True,
            },
            "secondary_sl_rule": {"type": "NEXT_BAR_NOT_SHORTEN_EXIT"},
            "traceability": {"setup_id": "stage2-setup", "trigger_id": "stage2-trigger"},
            "ext": {"stage2_test": True},
        },
    }
    return event


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 2 E2E close test")
    ap.add_argument("--env-file", default=".env", help="path to .env (default: .env)")
    ap.add_argument("--wait-before-close", type=int, default=3, help="seconds to wait after injecting plan")
    ap.add_argument("--wait-after-close", type=int, default=3, help="seconds to wait after force close")
    ap.add_argument(
        "--close-price",
        type=float,
        default=float(os.getenv("STAGE2_CLOSE_PRICE", "623.7579")),
        help="forced close price for PAPER/BACKTEST",
    )
    args = ap.parse_args()

    # Load env BEFORE importing project settings
    file_env = _load_env_file(args.env_file)
    for k, v in file_env.items():
        os.environ.setdefault(k, v)

    env = os.getenv("ENV", "dev")
    redis_url = os.getenv("REDIS_URL")
    database_url = os.getenv("DATABASE_URL")
    if not redis_url or not database_url:
        raise SystemExit("REDIS_URL / DATABASE_URL missing")

    mode = (os.getenv("EXECUTION_MODE") or "LIVE").upper()
    if mode not in ("PAPER", "BACKTEST"):
        print(f"[WARN] EXECUTION_MODE={mode} (recommend PAPER/BACKTEST).")

    ctx = redis_connect(redis_url)

    print("== Inject trade_plan ==")
    plan_evt = build_trade_plan(env=env)
    msg_id = publish_event(ctx.r, "stream:trade_plan", plan_evt, event_type="TRADE_PLAN")
    plan_id = plan_evt["payload"]["plan_id"]
    idem = plan_evt["payload"]["idempotency_key"]
    symbol = plan_evt["payload"]["symbol"]
    side = plan_evt["payload"]["side"]
    print(f"[ OK ] injected msg_id={msg_id} plan_id={plan_id}")
    print(f"      idempotency_key={idem} symbol={symbol} side={side}")

    print(f"== Wait {args.wait_before_close}s (entry fill) ==")
    time.sleep(args.wait_before_close)

    print("== Force close (PAPER/BACKTEST) ==")
    # Import late to respect env-file overrides
    from services.execution.executor import close_position_market

    close_position_market(
        database_url,
        redis_url,
        idempotency_key=idem,
        symbol=symbol,
        side=side,
        close_price=float(args.close_price),
        close_time_ms=int(time.time() * 1000),
        reason="stage2_test_force_close",
    )

    print(f"== Wait {args.wait_after_close}s (reports/notify) ==")
    time.sleep(args.wait_after_close)

    print("== Related execution_report ==")
    latest = xrevrange_latest_event(ctx.r, "stream:execution_report", count=200)
    related = []
    for item in latest:
        ev = item.get("event") or {}
        payload = (ev.get("payload") or {}) if isinstance(ev, dict) else {}
        if payload.get("plan_id") == plan_id:
            related.append(item)
    print(json.dumps(related[:10], ensure_ascii=False, indent=2))

    print("== Latest risk_event (if any) ==")
    risk = xrevrange_latest_event(ctx.r, "stream:risk_event", count=50)
    print(json.dumps(risk[:5], ensure_ascii=False, indent=2))

    print("\n[OK] If TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID configured, you should receive a close message with PnL + loss streak.")


if __name__ == "__main__":
    main()
