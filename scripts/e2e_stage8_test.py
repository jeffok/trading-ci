# -*- coding: utf-8 -*-
"""Stage 8 self-test.

This script is intentionally lightweight and runnable without Redis/Postgres:
- Schema checks (risk-event / execution-report / trade-plan)
- Risk type normalization
- Notifier templates for new risk types
- MarketStateTracker classification/emit logic

Usage:
  python -m scripts.e2e_stage8_test
"""

from __future__ import annotations

import json
import os

# Provide safe defaults so this script can run without env.
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trading")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from libs.mq.risk_normalize import normalize_risk_type
from services.notifier.templates import render_risk_event
from services.marketdata.market_state import MarketStateTracker


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _check_schemas() -> None:
    risk_schema = _load_json("libs/schemas/streams/risk-event.json")
    enums = risk_schema["properties"]["payload"]["properties"]["type"]["enum"]
    for t in ("SIGNAL_EXPIRED", "ORDER_TIMEOUT", "ORDER_PARTIAL_FILL", "MARKET_STATE"):
        assert t in enums, f"risk-event.json missing {t} enum"
        assert normalize_risk_type(t) == t

    exec_schema = _load_json("libs/schemas/streams/execution-report.json")
    props = exec_schema["properties"]["payload"]["properties"]
    assert "fill_ratio" in props, "execution-report.json missing fill_ratio"

    tp_schema = _load_json("libs/schemas/streams/trade-plan.json")
    tpp = tp_schema["properties"]["payload"]["properties"]
    for k in ("status", "valid_from_ms", "expires_at_ms"):
        assert k in tpp, f"trade-plan.json missing {k}"


def _check_templates() -> None:
    base = {
        "payload": {
            "severity": "IMPORTANT",
            "symbol": "BCHUSDT",
            "detail": {},
        }
    }

    evt = json.loads(json.dumps(base))
    evt["payload"]["type"] = "SIGNAL_EXPIRED"
    evt["payload"]["detail"] = {"expires_at_ms": 1, "now_ms": 2, "plan_id": "p1"}
    sev, txt = render_risk_event(evt)
    assert "过期" in txt

    evt = json.loads(json.dumps(base))
    evt["payload"]["type"] = "ORDER_TIMEOUT"
    evt["payload"]["detail"] = {"order_link_id": "x", "age_ms": 21000, "timeout_ms": 20000}
    sev, txt = render_risk_event(evt)
    assert "超时" in txt

    evt = json.loads(json.dumps(base))
    evt["payload"]["type"] = "ORDER_PARTIAL_FILL"
    evt["payload"]["detail"] = {"order_link_id": "x", "cum_exec_qty": "0.5", "qty": "1"}
    sev, txt = render_risk_event(evt)
    assert "部分成交" in txt

    evt = json.loads(json.dumps(base))
    evt["payload"]["type"] = "MARKET_STATE"
    evt["payload"]["detail"] = {"state": "HIGH_VOL", "range_pct": 0.05, "timeframe": "1h"}
    sev, txt = render_risk_event(evt)
    assert "HIGH_VOL" in txt or "高波动" in txt


def _check_market_state_tracker() -> None:
    tr = MarketStateTracker(high_vol_pct=0.04, emit_on_normal=False)
    st = tr.classify(symbol="BCHUSDT", timeframe="1h", ohlcv={"open": 100, "high": 105, "low": 95, "close": 100, "volume": 1})
    assert st is not None and st.state == "HIGH_VOL"
    assert tr.should_emit(symbol="BCHUSDT", timeframe="1h", state=st.state) is True
    # second time with same state should not emit
    assert tr.should_emit(symbol="BCHUSDT", timeframe="1h", state=st.state) is False


def main() -> None:
    _check_schemas()
    print("[OK] schemas")
    _check_templates()
    print("[OK] notifier templates")
    _check_market_state_tracker()
    print("[OK] market state tracker")


if __name__ == "__main__":
    main()
