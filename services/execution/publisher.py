# -*- coding: utf-8 -*-
"""execution-service 事件构建与发布（Phase 3/4）"""

from __future__ import annotations

from typing import Any, Dict, Optional

from libs.common.config import settings
from libs.common.id import new_event_id, new_trace_id
from libs.common.time import now_ms
from libs.mq.events import publish_event
from libs.mq.redis_streams import RedisStreamsClient
from libs.mq.schema_validator import validate

EXEC_REPORT_SCHEMA = "streams/execution-report.json"
RISK_EVENT_SCHEMA = "streams/risk-event.json"

STREAM_EXEC_REPORT = "stream:execution_report"
STREAM_RISK = "stream:risk_event"


def build_execution_report(*, idempotency_key: str, symbol: str, typ: str, severity: str, detail: Dict[str, Any], ext: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
    event = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "env": settings.env,
        "service": "execution-service",
        "trace_id": trace_id or new_trace_id(),
        "schema_version": 1,
        "meta": {},
        "payload": {
            "idempotency_key": idempotency_key,
            "symbol": symbol,
            "type": typ,
            "severity": severity,
            "detail": detail,
            "ext": (ext or {}),
        },
        "ext": {},
    }
    validate(EXEC_REPORT_SCHEMA, event)
    return event


def publish_execution_report(redis_url: str, event: Dict[str, Any]) -> str:
    client = RedisStreamsClient(redis_url)
    return publish_event(client, STREAM_EXEC_REPORT, event, event_type="execution_report")


def build_risk_event(*, typ: str, severity: str, symbol: Optional[str], detail: Dict[str, Any], trace_id: Optional[str] = None) -> Dict[str, Any]:
    event = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "env": settings.env,
        "service": "execution-service",
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
