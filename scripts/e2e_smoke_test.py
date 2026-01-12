#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import redis


DEFAULT_PORTS = {
    "api": 8000,
    "marketdata": 8001,
    "strategy": 8002,
    "execution": 8003,
    "notifier": 8004,
}

STREAMS = [
    "stream:dlq",
    "stream:bar_close",
    "stream:signal",
    "stream:trade_plan",
    "stream:execution_report",
    "stream:risk_event",
]

DEFAULT_GROUP = "bot-group"


def _load_env_file(path: str) -> Dict[str, str]:
    """极简 .env 解析器（避免额外依赖）"""
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


def http_json(url: str, timeout: float = 3.0) -> Tuple[int, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
    except Exception as e:
        return 0, str(e)


@dataclass
class RedisCtx:
    r: redis.Redis
    group: str


def redis_connect(redis_url: str) -> RedisCtx:
    r = redis.Redis.from_url(redis_url, decode_responses=True)
    r.ping()
    group = os.getenv("REDIS_STREAM_GROUP", DEFAULT_GROUP)
    return RedisCtx(r=r, group=group)


def xinfo_stream_safe(r: redis.Redis, stream: str) -> Dict[str, Any]:
    try:
        return r.xinfo_stream(stream)
    except Exception as e:
        return {"error": str(e)}


def xinfo_groups_safe(r: redis.Redis, stream: str) -> Any:
    try:
        return r.xinfo_groups(stream)
    except Exception as e:
        return {"error": str(e)}


def xrevrange_latest_event(r: redis.Redis, stream: str, count: int = 20) -> list[dict]:
    """
    读取 stream 最新若干条事件。
    兼容两种字段：
    - 项目规范：fields["json"] 是 JSON string
    - 旧格式：fields["data"] 是 JSON string
    """
    out: list[dict] = []
    try:
        items = r.xrevrange(stream, max="+", min="-", count=count)
        for msg_id, fields in items:
            raw = None
            if "json" in fields:
                raw = fields["json"]
            elif "data" in fields:
                raw = fields["data"]

            if raw is not None:
                try:
                    evt = json.loads(raw)
                except Exception:
                    evt = {"_raw": raw}
            else:
                evt = {"_fields": fields}

            out.append({"id": msg_id, "event": evt})
    except Exception as e:
        out.append({"error": str(e)})
    return out


def build_trade_plan(env: str) -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    plan_id = f"smoke-{uuid.uuid4().hex[:12]}"
    idem = f"idem-{uuid.uuid4().hex}"

    event = {
        "event_id": f"evt-{uuid.uuid4().hex}",
        "ts_ms": now_ms,
        "env": env,
        "service": "strategy-service",
        "schema_version": 1,
        "payload": {
            "plan_id": plan_id,
            "idempotency_key": idem,
            "symbol": os.getenv("SMOKE_SYMBOL", "BTCUSDT"),
            "timeframe": os.getenv("SMOKE_TIMEFRAME", "15m"),
            "side": os.getenv("SMOKE_SIDE", "BUY"),
            "entry_price": float(os.getenv("SMOKE_ENTRY_PRICE", "30000")),
            "primary_sl_price": float(os.getenv("SMOKE_SL_PRICE", "29000")),
            "tp_rules": {
                "tp1": {"r": 1.0, "pct": 0.4},
                "tp2": {"r": 2.0, "pct": 0.4},
                "tp3_trail": {"pct": 0.2, "mode": "ATR"},
                "reduce_only": True,
            },
            "secondary_sl_rule": {"type": "NEXT_BAR_NOT_SHORTEN_EXIT"},
            "traceability": {"setup_id": "smoke-setup", "trigger_id": "smoke-trigger"},
            "ext": {"smoke_test": True},
        },
    }
    return event


def publish_event(
    r: redis.Redis, stream: str, event: Dict[str, Any], event_type: Optional[str] = None
) -> str:
    """
    ✅ 关键：项目消费者解析优先读取 fields["json"]
    所以注入必须用字段 json，而不是 data。
    """
    payload: Dict[str, Any] = {"json": json.dumps(event, ensure_ascii=False)}
    if event_type:
        payload["type"] = event_type
    return r.xadd(stream, payload)


def main():
    ap = argparse.ArgumentParser(description="Trading-CI E2E smoke test")
    ap.add_argument("--env-file", default=".env", help="path to .env (default: .env)")
    ap.add_argument("--base-url", default="http://127.0.0.1", help="base url for health checks")
    ap.add_argument("--wait-seconds", type=int, default=8, help="wait seconds after injecting trade_plan")
    ap.add_argument("--inject-trade-plan", action="store_true", help="inject a trade_plan into Redis")
    args = ap.parse_args()

    file_env = _load_env_file(args.env_file)
    for k, v in file_env.items():
        os.environ.setdefault(k, v)

    env = os.getenv("ENV", "dev")
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise SystemExit("REDIS_URL is missing (set in .env or env vars)")

    print("== Health checks ==")
    ok = True
    for name, port in DEFAULT_PORTS.items():
        url = f"{args.base_url}:{port}/health"
        code, body = http_json(url)
        if code != 200:
            ok = False
            print(f"[FAIL] {name:10s} {url} -> {code} {body}")
        else:
            print(f"[ OK ] {name:10s} {url} -> {body}")

    print("\n== Redis checks ==")
    ctx = redis_connect(redis_url)
    print(f"[ OK ] redis ping ok, group={ctx.group}")

    for s in STREAMS:
        info = xinfo_stream_safe(ctx.r, s)
        groups = xinfo_groups_safe(ctx.r, s)
        print(f"- {s}")
        if "error" in info:
            print(f"  stream_info: {info}")
        else:
            print(
                f"  stream_info: {{'length': {info.get('length')}, 'last-generated-id': '{info.get('last-generated-id')}'}}"
            )
        print(f"  groups: {groups}")

    if args.inject_trade_plan:
        print("\n== Inject trade_plan ==")
        evt = build_trade_plan(env=env)
        msg_id = publish_event(ctx.r, "stream:trade_plan", evt, event_type="TRADE_PLAN")
        print(f"[ OK ] injected trade_plan msg_id={msg_id}, plan_id={evt['payload']['plan_id']}")
        print(f"      idempotency_key={evt['payload']['idempotency_key']}")

        print(f"\n== Wait {args.wait_seconds}s for execution ==")
        time.sleep(args.wait_seconds)

        print("\n== Check latest outputs ==")
        plan_id = evt["payload"]["plan_id"]

        for out_stream in ["stream:execution_report", "stream:risk_event", "stream:dlq"]:
            latest = xrevrange_latest_event(ctx.r, out_stream, count=50)
            related = []
            for item in latest:
                ev = item.get("event", {})
                if isinstance(ev, dict):
                    payload = ev.get("payload", {})
                    if isinstance(payload, dict) and payload.get("plan_id") == plan_id:
                        related.append(item)

            print(f"- {out_stream}: related={len(related)}")
            if related:
                print(json.dumps(related[:3], ensure_ascii=False, indent=2))
            else:
                # 没找到就输出最新 1 条帮助诊断
                print("  (no related event found; latest 1 shown)")
                print(json.dumps(latest[:1], ensure_ascii=False, indent=2))

    print("\n== Result ==")
    if not ok:
        print("Some health checks failed. Fix services first.")
        raise SystemExit(2)

    print("Health checks OK.")
    if args.inject_trade_plan:
        print("Trade plan injected. Review execution_report/risk_event/dlq outputs above.")
    else:
        print("Run with --inject-trade-plan to test the event pipeline.")


if __name__ == "__main__":
    main()
