# -*- coding: utf-8 -*-
"""Risk/alert type normalization.

`streams/risk-event.json` is strict (enum-based). Historically the codebase emitted
free-form `typ` / `severity` values. This module converts legacy/internal values
into schema-allowed enums while preserving the original value for troubleshooting.
"""

from __future__ import annotations

from typing import Optional


RISK_TYPES_ALLOWED = {
    "RATE_LIMIT",
    "INVALID_ORDER",
    "REJECTED_BY_EXCHANGE",
    "KILL_SWITCH_ON",
    "MAX_POSITIONS_BLOCKED",
    "POSITION_MUTEX_BLOCKED",
    "COOLDOWN_BLOCKED",
    "DATA_LAG",
    "BAR_DUPLICATE",
    "PRICE_JUMP",
    "VOLUME_ANOMALY",
    "WS_RECONNECT",
    "SIGNAL_CONFLICT",
    "IDEMPOTENCY_CONFLICT",
    "CONSISTENCY_DRIFT",
    # Stage 8
    "SIGNAL_EXPIRED",
    "ORDER_TIMEOUT",
    "ORDER_PARTIAL_FILL",
    "ORDER_CANCELLED",
    "ORDER_FALLBACK_MARKET",
    "ORDER_RETRY",
    "MARKET_STATE",
    "RISK_REJECTED",
}


def normalize_risk_severity(severity: Optional[str]) -> str:
    """Normalize to schema enum: CRITICAL / IMPORTANT / INFO."""
    s = (severity or "").strip().upper()
    if s in ("CRITICAL", "IMPORTANT", "INFO"):
        return s
    # legacy
    if s in ("EMERGENCY", "FATAL", "PANIC"):
        return "CRITICAL"
    if s in ("WARN", "WARNING", "ALERT"):
        return "IMPORTANT"
    return "INFO"


def normalize_risk_type(typ: Optional[str]) -> str:
    """Normalize to a schema-allowed risk type enum."""
    t = (typ or "").strip().upper()
    if t in RISK_TYPES_ALLOWED:
        return t

    # common legacy/internal types
    if t in ("PROCESSING_LAG", "BAR_CLOSE_LAG", "TRADE_PLAN_LAG"):
        return "DATA_LAG"
    if t in ("DAILY_DRAWDOWN_SOFT", "DAILY_DRAWDOWN_HARD", "RISK_CIRCUIT_BLOCK", "KILL_SWITCH", "HARD_HALT", "SOFT_HALT"):
        return "KILL_SWITCH_ON"
    if t in ("TRADE_PLAN_FAILED", "BAR_CLOSE_FAILED", "LIFECYCLE_ERROR", "RISK_STATE_READ_FAILED"):
        return "DATA_LAG"
    if t in ("BYBIT_RATE_LIMIT", "HTTP_429"):
        return "RATE_LIMIT"
    if t in ("SIGNAL_EXPIRE", "SIGNAL_EXPIRED", "PLAN_EXPIRED", "TRADE_PLAN_EXPIRED"):
        return "SIGNAL_EXPIRED"
    if t in ("ORDER_TIMEOUT", "TIMEOUT", "ORDER_STUCK"):
        return "ORDER_TIMEOUT"
    if t in ("PARTIAL_FILL", "ORDER_PARTIAL_FILL"):
        return "ORDER_PARTIAL_FILL"
    if t in ("MARKET_STATE", "HIGH_VOL", "NEWS_WINDOW"):
        return "MARKET_STATE"
    if t in ("COOLDOWN_SET", "COOLDOWN"):
        return "COOLDOWN_BLOCKED"
    if t in ("REJECTED", "REJECT", "ORDER_REJECTED"):
        return "REJECTED_BY_EXCHANGE"
    return "RISK_REJECTED"
