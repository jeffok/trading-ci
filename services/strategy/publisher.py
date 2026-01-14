# -*- coding: utf-8 -*-
"""
strategy-service 事件发布器（Phase 2）
- signal -> stream:signal
- trade_plan -> stream:trade_plan
- risk_event -> stream:risk_event（用于异常/拒绝原因事件化）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from libs.common.config import settings
from libs.common.id import new_event_id, new_trace_id
from libs.common.time import now_ms
from libs.mq.events import publish_event
from libs.mq.redis_streams import RedisStreamsClient
from libs.mq.schema_validator import validate

SIGNAL_SCHEMA = "streams/signal.json"
TRADE_PLAN_SCHEMA = "streams/trade-plan.json"
RISK_EVENT_SCHEMA = "streams/risk-event.json"

STREAM_SIGNAL = "stream:signal"
STREAM_TRADE_PLAN = "stream:trade_plan"
STREAM_RISK = "stream:risk_event"


def build_signal_event(
    *,
    symbol: str,
    timeframe: str,
    close_time_ms: int,
    bias: str,  # LONG/SHORT
    vegas_state: str,
    hits: List[str],
    setup_id: str,
    trigger_id: str,
    trace_id: Optional[str] = None,
    signal_score: Optional[int] = None,
    divergence_strength: Optional[int] = None,
    market_state: str = "NORMAL",
    ext: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "env": settings.env,
        "service": "strategy-service",
        "trace_id": trace_id or new_trace_id(),
        "schema_version": 1,
        "meta": {},
        "payload": {
            "symbol": symbol,
            "timeframe": timeframe,
            "close_time_ms": close_time_ms,
            "setup_id": setup_id,
            "trigger_id": trigger_id,
            "bias": bias,
            "vegas_state": vegas_state,
            "confirmations": {
                "min_required": settings.min_confirmations,
                "hit_count": len(hits),
                "hits": hits,
            },
            "lifecycle": {
                "status": "CONFIRMED",
                "valid_from_ms": close_time_ms,
                # 过期时间：Phase 2 先给一个保守值（例如 3 根K线后过期），执行层仍需做幂等与检查
                "expires_at_ms": close_time_ms + 3 * 60 * 60 * 1000,
            },
            "signal_score": signal_score,
            "divergence_strength": divergence_strength,
            "market_state": market_state,
            "ext": (ext or {}),
        },
        "ext": {},
    }
    validate(SIGNAL_SCHEMA, event)
    return event


def publish_signal(redis_url: str, event: Dict[str, Any]) -> str:
    client = RedisStreamsClient(redis_url)
    return publish_event(client, STREAM_SIGNAL, event, event_type="signal")


def build_trade_plan_event(
    *,
    plan_id: str,
    idempotency_key: str,
    symbol: str,
    timeframe: str,
    close_time_ms: int,
    side: str,  # BUY/SELL
    entry_price: float,
    primary_sl_price: float,
    setup_id: str,
    trigger_id: str,
    trace_id: Optional[str] = None,
    risk_pct: Optional[float] = None,
    ext: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "env": settings.env,
        "service": "strategy-service",
        "trace_id": trace_id or new_trace_id(),
        "schema_version": 1,
        "meta": {},
        "payload": {
            "plan_id": plan_id,
            "idempotency_key": idempotency_key,
            "symbol": symbol,
            "timeframe": timeframe,
            # Stage 8 lifecycle
            "status": (ext or {}).get("status") or "NEW",
            "valid_from_ms": int((ext or {}).get("valid_from_ms") or close_time_ms),
            "expires_at_ms": int((ext or {}).get("expires_at_ms") or 0),
            "side": side,
            "entry_price": float(entry_price),
            "primary_sl_price": float(primary_sl_price),
            "tp_rules": {
                "tp1": {"r": 1.0, "pct": 0.4},
                "tp2": {"r": 2.0, "pct": 0.4},
                "tp3_trail": {"pct": 0.2, "mode": "ATR"},
                "reduce_only": True,
            },
            "secondary_sl_rule": {"type": "NEXT_BAR_NOT_SHORTEN_EXIT"},
            "risk_params": {
                "risk_pct": float(risk_pct if risk_pct is not None else settings.risk_pct),
                "max_open_positions_default": int(settings.max_open_positions_default),
            },
            "confluence": {
                # 由执行层/复盘使用；Phase 2 先保留结构
                "vegas_state": None,
                "confirmations": None,
                "signal_score": None,
            },
            "traceability": {"setup_id": setup_id, "trigger_id": trigger_id},
            "ext": (ext or {"close_time_ms": close_time_ms}),
        },
        "ext": {},
    }
    validate(TRADE_PLAN_SCHEMA, event)
    return event


def publish_trade_plan(redis_url: str, event: Dict[str, Any]) -> str:
    client = RedisStreamsClient(redis_url)
    return publish_event(client, STREAM_TRADE_PLAN, event, event_type="trade_plan")


def build_risk_event(*, typ: str, severity: str, symbol: Optional[str], detail: Dict[str, Any], trace_id: Optional[str] = None) -> Dict[str, Any]:
    event = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "env": settings.env,
        "service": "strategy-service",
        "trace_id": trace_id or new_trace_id(),
        "schema_version": 1,
        "meta": {},
        "payload": {
            "type": typ,
            "severity": severity,
            "symbol": symbol,
            "detail": detail,
            "ext": {},
        },
        "ext": {},
    }
    validate(RISK_EVENT_SCHEMA, event)
    return event


def publish_risk_event(redis_url: str, event: Dict[str, Any]) -> str:
    client = RedisStreamsClient(redis_url)
    return publish_event(client, STREAM_RISK, event, event_type="risk_event")
