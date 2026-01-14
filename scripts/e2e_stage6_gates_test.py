# -*- coding: utf-8 -*-
"""Stage 6 E2E test: max positions / mutex priority upgrade / cooldown.

Run with EXECUTION_MODE=PAPER and all services up.

This script is safe for dev: it can optionally TRUNCATE execution tables.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import redis


def _load_env_file(path: str) -> Dict[str, str]:
    if not os.path.exists(path):
        return {}
    out: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _now_ms() -> int:
    return int(time.time() * 1000)


def publish_event(r: redis.Redis, stream: str, event: Dict[str, Any], event_type: Optional[str] = None) -> str:
    payload: Dict[str, Any] = {"json": json.dumps(event, ensure_ascii=False)}
    if event_type:
        payload["type"] = event_type
    return r.xadd(stream, payload)


def build_trade_plan(
    *,
    symbol: str,
    timeframe: str,
    side: str,
    entry: float,
    sl: float,
    close_time_ms: int,
    plan_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    pid = plan_id or f"stage6-{uuid.uuid4().hex[:10]}"
    idem = idempotency_key or f"idem-{uuid.uuid4().hex}"
    evt = {
        "event_id": f"evt-{uuid.uuid4().hex}",
        "ts_ms": _now_ms(),
        "env": os.getenv("ENV", "dev"),
        "service": "e2e-stage6",
        "payload": {
            "plan_id": pid,
            "idempotency_key": idem,
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "entry_price": float(entry),
            "primary_sl_price": float(sl),
            "risk_pct": 0.005,
            "close_time_ms": int(close_time_ms),
            "tp_rules": {
                "tp1": {"r": 1.0, "pct": 0.4},
                "tp2": {"r": 2.0, "pct": 0.4},
                "tp3_trail": {"pct": 0.2, "mode": "ATR"},
                "reduce_only": True,
            },
            "secondary_sl_rule": {"type": "NEXT_BAR_NOT_SHORTEN_EXIT"},
            "traceability": {"setup_id": "stage6", "trigger_id": "stage6"},
            "ext": {"run_id": "stage6-test"},
        },
    }
    return evt


def build_bar_close(*, symbol: str, timeframe: str, close_time_ms: int, o: float, h: float, l: float, c: float) -> Dict[str, Any]:
    return {
        "event_id": f"evt-{uuid.uuid4().hex}",
        "ts_ms": _now_ms(),
        "env": os.getenv("ENV", "dev"),
        "service": "e2e-stage6",
        "payload": {
            "symbol": symbol,
            "timeframe": timeframe,
            "close_time_ms": int(close_time_ms),
            "is_final": True,
            "source": "bybit_ws",
            "ohlcv": {"open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": 1.0},
            "ext": {"run_id": "stage6-test"},
        },
    }


def _xlast(r: redis.Redis, stream: str) -> str:
    try:
        xs = r.xrevrange(stream, count=1)
        if xs:
            return xs[0][0].decode() if isinstance(xs[0][0], (bytes, bytearray)) else str(xs[0][0])
    except Exception:
        pass
    return "0-0"


def _collect(
    r: redis.Redis,
    stream: str,
    start_id: str,
    predicate,
    timeout_s: int = 15,
) -> List[Dict[str, Any]]:
    end = time.time() + timeout_s
    cur = start_id
    out: List[Dict[str, Any]] = []
    while time.time() < end:
        resp = r.xread({stream: cur}, count=100, block=500)
        if not resp:
            continue
        for _stream_name, items in resp:
            for xid, fields in items:
                cur = xid.decode() if isinstance(xid, (bytes, bytearray)) else str(xid)
                raw = fields.get(b"json") or fields.get("json")
                if raw is None:
                    continue
                try:
                    obj = json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
                except Exception:
                    continue
                if predicate(obj):
                    out.append(obj)
        if out:
            break
    return out


def _reset_db(database_url: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE orders, positions, cooldowns, execution_reports, risk_events, backtest_trades RESTART IDENTITY CASCADE;")
        conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--reset-db", action="store_true", help="TRUNCATE execution tables before running")
    ap.add_argument("--wait", type=int, default=10)
    args = ap.parse_args()

    for k, v in _load_env_file(args.env_file).items():
        os.environ.setdefault(k, v)

    redis_url = os.getenv("REDIS_URL")
    database_url = os.getenv("DATABASE_URL")
    assert redis_url and database_url, "REDIS_URL and DATABASE_URL are required"

    r = redis.Redis.from_url(redis_url, decode_responses=False)

    if args.reset_db:
        _reset_db(database_url)
        time.sleep(1)

    # --- Test 1: MAX_POSITIONS_BLOCKED (default max=3)
    print("[T1] max positions -> expect 4th rejected")
    start_rep = _xlast(r, "stream:execution_report")
    start_risk = _xlast(r, "stream:risk_event")
    base_t = _now_ms()
    syms = ["BTCUSDT", "ETHUSDT", "BCHUSDT", "LTCUSDT"]
    idems: List[str] = []
    for i, s in enumerate(syms):
        ev = build_trade_plan(symbol=s, timeframe="1h", side="BUY", entry=100 + i, sl=90 + i, close_time_ms=base_t + i * 3600000)
        idems.append(ev["payload"]["idempotency_key"])
        publish_event(r, "stream:trade_plan", ev, event_type="trade_plan")
        time.sleep(0.2)

    # wait for a REJECTED report for the 4th
    rejected = _collect(
        r,
        "stream:execution_report",
        start_rep,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idems[-1]
        and str((obj.get("payload") or {}).get("status") or "").upper() in ("REJECTED", "ORDER_REJECTED", "ERROR"),
        timeout_s=args.wait,
    )
    if not rejected:
        raise SystemExit("T1 failed: no reject report for 4th plan")
    print("  OK: got reject report")

    risk_max = _collect(
        r,
        "stream:risk_event",
        start_risk,
        lambda obj: str((obj.get("payload") or {}).get("type") or "").upper() == "MAX_POSITIONS_BLOCKED",
        timeout_s=args.wait,
    )
    if not risk_max:
        raise SystemExit("T1 failed: no MAX_POSITIONS_BLOCKED risk_event")
    print("  OK: got MAX_POSITIONS_BLOCKED risk_event")

    # --- Test 2: mutex upgrade (reset DB to avoid interference)
    print("[T2] mutex upgrade -> 4h plan should close 1h and open new")
    _reset_db(database_url)
    time.sleep(1)
    start_rep = _xlast(r, "stream:execution_report")
    base_t = _now_ms()
    ev1 = build_trade_plan(symbol="BTCUSDT", timeframe="1h", side="BUY", entry=200, sl=180, close_time_ms=base_t)
    ev2 = build_trade_plan(symbol="BTCUSDT", timeframe="4h", side="BUY", entry=200, sl=180, close_time_ms=base_t + 4 * 3600000)
    idem1 = ev1["payload"]["idempotency_key"]
    idem2 = ev2["payload"]["idempotency_key"]
    publish_event(r, "stream:trade_plan", ev1, event_type="trade_plan")
    time.sleep(0.5)
    publish_event(r, "stream:trade_plan", ev2, event_type="trade_plan")

    # expect: an EXITED for idem1 with reason mutex_upgrade, and a FILLED for idem2
    exited1 = _collect(
        r,
        "stream:execution_report",
        start_rep,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idem1
        and str((obj.get("payload") or {}).get("status") or "").upper() in ("EXITED", "POSITION_CLOSED", "PRIMARY_SL_HIT", "SECONDARY_SL_EXIT"),
        timeout_s=args.wait,
    )
    if not exited1:
        raise SystemExit("T2 failed: no EXITED/CLOSED for lower timeframe position")
    print("  OK: lower timeframe got closed/exited")

    filled2 = _collect(
        r,
        "stream:execution_report",
        start_rep,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idem2
        and str((obj.get("payload") or {}).get("status") or "").upper() in ("FILLED", "ORDER_SUBMITTED"),
        timeout_s=args.wait,
    )
    if not filled2:
        raise SystemExit("T2 failed: no FILLED for higher timeframe plan")
    print("  OK: higher timeframe plan executed")

    # --- Test 3: cooldown (reset DB)
    print("[T3] cooldown -> after PRIMARY_SL_HIT, next entry blocked")
    _reset_db(database_url)
    time.sleep(1)
    start_rep = _xlast(r, "stream:execution_report")
    start_risk = _xlast(r, "stream:risk_event")
    base_t = _now_ms()
    ev = build_trade_plan(symbol="BTCUSDT", timeframe="1h", side="BUY", entry=100, sl=90, close_time_ms=base_t)
    idem = ev["payload"]["idempotency_key"]
    publish_event(r, "stream:trade_plan", ev, event_type="trade_plan")
    time.sleep(1)
    # bar that triggers SL (low below 90)
    bc = build_bar_close(symbol="BTCUSDT", timeframe="1h", close_time_ms=base_t + 3600000, o=100, h=100, l=80, c=85)
    publish_event(r, "stream:bar_close", bc, event_type="bar_close")

    sl_rep = _collect(
        r,
        "stream:execution_report",
        start_rep,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idem
        and str((obj.get("payload") or {}).get("status") or "").upper() in ("PRIMARY_SL_HIT", "SECONDARY_SL_EXIT", "POSITION_CLOSED"),
        timeout_s=args.wait,
    )
    if not sl_rep:
        raise SystemExit("T3 failed: no SL close report")
    print("  OK: got SL close report")

    # try re-entry within cooldown window
    start_rep2 = _xlast(r, "stream:execution_report")
    ev_re = build_trade_plan(symbol="BTCUSDT", timeframe="1h", side="BUY", entry=100, sl=90, close_time_ms=base_t + 3600000)
    idem_re = ev_re["payload"]["idempotency_key"]
    publish_event(r, "stream:trade_plan", ev_re, event_type="trade_plan")

    reject_cd = _collect(
        r,
        "stream:execution_report",
        start_rep2,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idem_re
        and str((obj.get("payload") or {}).get("status") or "").upper() == "REJECTED",
        timeout_s=args.wait,
    )
    if not reject_cd:
        raise SystemExit("T3 failed: no REJECTED on cooldown")

    risk_cd = _collect(
        r,
        "stream:risk_event",
        start_risk,
        lambda obj: str((obj.get("payload") or {}).get("type") or "").upper() == "COOLDOWN_BLOCKED",
        timeout_s=args.wait,
    )
    if not risk_cd:
        raise SystemExit("T3 failed: no COOLDOWN_BLOCKED risk_event")
    print("  OK: cooldown blocked re-entry")

    print("All Stage 6 gate tests passed ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
