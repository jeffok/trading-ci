# -*- coding: utf-8 -*-
"""Risk-state extensions.

This module adds lightweight, non-intrusive state used for notifications/observability
without changing the strategy logic.

Currently:
- consecutive_loss_count: consecutive realized losing trades (reset on win/breakeven)

Storage:
- risk_state.meta JSONB (per UTC trade_date)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from services.execution.repo import get_or_init_risk_state, merge_risk_state_meta


def update_consecutive_loss_count(
    database_url: str,
    *,
    trade_date: str,
    mode: str,
    pnl_usdt: float,
) -> int:
    """Update and return consecutive_loss_count.

    Rule:
    - pnl_usdt < 0  => +1
    - pnl_usdt >= 0 => reset to 0
    """
    st = get_or_init_risk_state(database_url, trade_date=trade_date, mode=mode)
    meta = st.get("meta") or {}
    try:
        current = int(meta.get("consecutive_loss_count") or 0)
    except Exception:
        current = 0

    nxt = current + 1 if float(pnl_usdt) < 0 else 0
    merge_risk_state_meta(database_url, trade_date=trade_date, meta_patch={"consecutive_loss_count": int(nxt)})
    return int(nxt)
