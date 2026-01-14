# -*- coding: utf-8 -*-
"""Stage 6.1 + Stage 7.1 patch self-test.

This script is intentionally lightweight:
- Validates schema/normalization/template for CONSISTENCY_DRIFT
- (Optional) Validates hist_entry inference from DB bars

Usage:
  # pure python checks (no DB)
  python -m scripts.e2e_stage61_stage71_patch_test

  # with Postgres (requires DATABASE_URL env and bars table)
  python -m scripts.e2e_stage61_stage71_patch_test --with-db --symbol TESTUSDT --timeframe 1h
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import List

# Provide safe defaults so this script can run without env.
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trading")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from libs.common.config import settings
from libs.mq.risk_normalize import normalize_risk_type
from services.notifier.templates import render_risk_event


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _check_consistency_drift_schema() -> None:
    schema = _load_json("libs/schemas/streams/risk-event.json")
    enums = schema["properties"]["payload"]["properties"]["type"]["enum"]
    assert "CONSISTENCY_DRIFT" in enums, "risk-event.json missing CONSISTENCY_DRIFT enum"
    assert normalize_risk_type("CONSISTENCY_DRIFT") == "CONSISTENCY_DRIFT"

    evt = {
        "payload": {
            "type": "CONSISTENCY_DRIFT",
            "severity": "IMPORTANT",
            "symbol": "BCHUSDT",
            "detail": {"local_qty_total": 1.2, "ws_size": 0.9, "drift_pct": 0.25, "threshold_pct": 0.10, "idempotency_key": "idem_x"},
        }
    }
    sev, txt = render_risk_event(evt)
    assert sev == "IMPORTANT"
    assert "一致性漂移" in txt


def _ensure_bars(symbol: str, timeframe: str, close_times: List[int], closes: List[float]) -> None:
    from libs.db.pg import get_conn
    sql = """INSERT INTO bars(symbol,timeframe,open,high,low,close,volume,open_time_ms,close_time_ms)
             VALUES (%(symbol)s,%(timeframe)s,%(o)s,%(h)s,%(l)s,%(c)s,%(v)s,%(ot)s,%(ct)s)
             ON CONFLICT(symbol,timeframe,close_time_ms) DO NOTHING"""
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            for ct, c in zip(close_times, closes):
                cur.execute(
                    sql,
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "o": float(c),
                        "h": float(c),
                        "l": float(c),
                        "c": float(c),
                        "v": 1.0,
                        "ot": int(ct - 60_000),
                        "ct": int(ct),
                    },
                )
        conn.commit()


def _check_hist_entry_inference(symbol: str, timeframe: str) -> None:
    from services.execution.executor import _infer_hist_entry_from_bars

    # fabricate 200 bars
    base = 1700000000000
    close_times = [base + i * 3_600_000 for i in range(200)]
    closes = [100.0 + math.sin(i / 5.0) * 2.0 + i * 0.05 for i in range(200)]
    _ensure_bars(symbol, timeframe, close_times, closes)

    entry_close_ms = close_times[-1]
    v = _infer_hist_entry_from_bars(settings.database_url, symbol=symbol, timeframe=timeframe, entry_close_time_ms=entry_close_ms)
    assert v is not None, "hist_entry inference returned None"
    assert isinstance(v, float)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-db", action="store_true", help="Run DB integration checks (requires DATABASE_URL & bars table).")
    ap.add_argument("--symbol", default="TESTUSDT")
    ap.add_argument("--timeframe", default="1h")
    args = ap.parse_args()

    _check_consistency_drift_schema()
    print("[OK] CONSISTENCY_DRIFT schema/normalize/template")

    if args.with_db:
        _check_hist_entry_inference(args.symbol, args.timeframe)
        print("[OK] hist_entry inference from bars")


if __name__ == "__main__":
    main()
