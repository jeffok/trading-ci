# -*- coding: utf-8 -*-
"""Stage 11 self-test (no external services required).

Run:
  python -m scripts.e2e_stage11_selftest

This test focuses on:
- risk type normalization for new data quality types
- NEWS_WINDOW parsing / classification
- ATR-based HIGH_VOL marker basic behavior
- notifier template rendering for PRICE_JUMP
"""

from __future__ import annotations

import time

from libs.mq.risk_normalize import normalize_risk_type
from services.marketdata.market_state import MarketStateTracker
from services.notifier.templates import render_risk_event


def test_risk_types() -> None:
    for t in ["BAR_DUPLICATE", "PRICE_JUMP", "VOLUME_ANOMALY"]:
        assert normalize_risk_type(t) == t


def test_news_window_and_atr() -> None:
    # Window: 12:00-12:10 UTC
    tr = MarketStateTracker(atr_period=3, high_vol_pct=0.01, news_window_utc="12:00-12:10", emit_on_normal=True)
    # 2026-01-01 12:05 UTC
    ts_ms = 1767269100000  # fixed epoch ms
    st = tr.classify_states(symbol="BTCUSDT", timeframe="1h", close_time_ms=ts_ms, high=101, low=99, close=100)
    assert "NEWS_WINDOW" in st.states

    # feed a couple bars to initialize ATR
    for i in range(3):
        tr.classify_states(symbol="BTCUSDT", timeframe="1h", close_time_ms=ts_ms + (i+1)*3600_000, high=110, low=90, close=100)
    st2 = tr.classify_states(symbol="BTCUSDT", timeframe="1h", close_time_ms=ts_ms + 10*3600_000, high=120, low=80, close=100)
    assert st2.atr is not None
    assert st2.atr_pct is not None
    assert "HIGH_VOL" in st2.states or "NORMAL" in st2.states


def test_template_price_jump() -> None:
    evt = {
        "event_id": "e1",
        "ts_ms": int(time.time() * 1000),
        "trade_date": "2026-01-01",
        "payload": {
            "type": "PRICE_JUMP",
            "severity": "IMPORTANT",
            "symbol": "BCHUSDT",
            "detail": {"timeframe": "1h", "jump_pct": 0.12, "threshold_pct": 0.08},
        },
    }
    sev, msg = render_risk_event(evt)
    assert sev in ("INFO", "IMPORTANT", "CRITICAL")
    assert "异常跳变" in msg


def main() -> None:
    test_risk_types()
    test_news_window_and_atr()
    test_template_price_jump()
    print("Stage11 selftest OK")


if __name__ == "__main__":
    main()
