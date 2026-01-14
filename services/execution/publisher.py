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
from libs.mq.risk_normalize import normalize_risk_type, normalize_risk_severity

EXEC_REPORT_SCHEMA = "streams/execution-report.json"
RISK_EVENT_SCHEMA = "streams/risk-event.json"

STREAM_EXEC_REPORT = "stream:execution_report"
STREAM_RISK = "stream:risk_event"


def _derive_plan_id(idempotency_key: str, detail: Dict[str, Any], ext: Dict[str, Any]) -> str:
    # Prefer explicit plan_id
    pid = detail.get("plan_id") or ext.get("plan_id")
    if isinstance(pid, str) and pid.strip():
        return pid.strip()

    # If idempotency_key looks like a sha256 hex, take the prefix.
    # Strategy worker uses plan_id = sha256(... )[:24].
    ik = (idempotency_key or "").strip()
    if len(ik) >= 24:
        return ik[:24]

    return ("plan_" + new_event_id())[:24]


def _map_exec_status(typ: str) -> str:
    t = (typ or "").strip().upper()
    mapping = {
        "ENTRY_SUBMITTED": "ORDER_SUBMITTED",
        "EXIT_SUBMITTED": "ORDER_SUBMITTED",
        "ENTRY_FILLED": "FILLED",
        "TP_FILLED": "TP_HIT",
        "TP1_FILLED": "TP_HIT",
        "TP2_FILLED": "TP_HIT",
        "EXITED": "POSITION_CLOSED",
        "POSITION_CLOSED": "POSITION_CLOSED",
        "PRIMARY_SL_HIT": "PRIMARY_SL_HIT",
        "SECONDARY_SL_EXIT": "SECONDARY_SL_EXIT",
        "EXIT_RULE_TRIGGERED": "SECONDARY_SL_EXIT",
        "SL_UPDATE": "RUNNER_SL_UPDATED",
        "COOLDOWN_SET": "ORDER_REJECTED",
        "REJECTED": "ORDER_REJECTED",
        "INVALID_ORDER": "ORDER_REJECTED",
        "SET_SL_FAILED": "ORDER_REJECTED",
        "FORCE_EXIT_FAILED": "ORDER_REJECTED",
        "ERROR": "ORDER_REJECTED",
    }
    if t in mapping:
        return mapping[t]
    # fallback: keep within schema
    if t in (
        "ORDER_SUBMITTED",
        "ORDER_REJECTED",
        "FILLED",
        "TP_HIT",
        "PRIMARY_SL_HIT",
        "SECONDARY_SL_EXIT",
        "RUNNER_SL_UPDATED",
        "POSITION_CLOSED",
    ):
        return t
    return "ORDER_REJECTED"


def build_execution_report(
    *,
    idempotency_key: str,
    symbol: str,
    typ: str,
    severity: str,
    detail: Dict[str, Any],
    ext: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a schema-valid execution_report event.

    Note: the project previously used a legacy payload shape (idempotency_key/type/severity/detail).
    For compatibility we keep the call signature but emit the new schema-defined payload:
      - payload.plan_id (required)
      - payload.status (required)
      - optional fields filled_qty/avg_price/reason/order_id/latency_ms/slippage_bps/retry_count
      - payload.ext includes legacy fields for debugging
    """

    detail = detail or {}
    payload_ext: Dict[str, Any] = dict(ext or {})
    payload_ext.setdefault("idempotency_key", idempotency_key)
    payload_ext.setdefault("legacy_type", typ)
    payload_ext.setdefault("legacy_severity", severity)
    payload_ext.setdefault("detail", detail)

    status = _map_exec_status(typ)
    plan_id = _derive_plan_id(idempotency_key, detail=detail, ext=payload_ext)

    # try to infer quantities/prices from legacy detail
    filled_qty = detail.get("filled_qty")
    if filled_qty is None:
        filled_qty = detail.get("qty") or detail.get("fill_qty")
    avg_price = detail.get("avg_price")
    if avg_price is None:
        avg_price = detail.get("price") or detail.get("fill_price")

    order_id = detail.get("order_id") or detail.get("bybit_order_id") or detail.get("orderLinkId")
    timeframe = detail.get("timeframe") or payload_ext.get("timeframe")

    reason = detail.get("reason") or detail.get("error") or typ
    retry_count = detail.get("retry_count") or payload_ext.get("retry_count")
    latency_ms = detail.get("latency_ms") or payload_ext.get("latency_ms")
    slippage_bps = detail.get("slippage_bps") or payload_ext.get("slippage_bps")
    fill_ratio = detail.get("fill_ratio") or payload_ext.get("fill_ratio")

    payload: Dict[str, Any] = {
        "plan_id": str(plan_id),
        "status": str(status),
    }
    if symbol:
        payload["symbol"] = symbol
    if timeframe:
        payload["timeframe"] = str(timeframe)
    if filled_qty is not None:
        try:
            payload["filled_qty"] = float(filled_qty)
        except Exception:
            pass
    if avg_price is not None:
        try:
            payload["avg_price"] = float(avg_price)
        except Exception:
            pass
    if reason is not None:
        payload["reason"] = str(reason)
    if order_id is not None:
        payload["order_id"] = str(order_id)
    if retry_count is not None:
        try:
            payload["retry_count"] = int(retry_count)
        except Exception:
            pass
    if latency_ms is not None:
        try:
            payload["latency_ms"] = int(latency_ms)
        except Exception:
            pass
    if slippage_bps is not None:
        try:
            payload["slippage_bps"] = float(slippage_bps)
        except Exception:
            pass
    if fill_ratio is not None:
        try:
            payload["fill_ratio"] = float(fill_ratio)
        except Exception:
            pass

    payload["ext"] = payload_ext

    event = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "env": settings.env,
        "service": "execution-service",
        "trace_id": trace_id or new_trace_id(),
        "schema_version": 1,
        "meta": {},
        "payload": payload,
        "ext": {},
    }
    validate(EXEC_REPORT_SCHEMA, event)
    return event


def publish_execution_report(redis_url: str, event: Dict[str, Any]) -> str:
    client = RedisStreamsClient(redis_url)
    msg_id = publish_event(client, STREAM_EXEC_REPORT, event, event_type="execution_report")

    # Stage 1: persist to DB for API queries / observability.
    # This MUST NOT block trading path; errors are swallowed.
    try:
        from services.execution.repo import save_execution_report

        payload = event.get("payload", {}) or {}
        ext = payload.get("ext", {}) or {}
        idem = str(ext.get("idempotency_key") or "")
        symbol = str(payload.get("symbol") or "")
        status = str(payload.get("status") or "")
        # Derive a reasonable severity for legacy column
        sev = "IMPORTANT" if status else "INFO"
        save_execution_report(
            settings.database_url,
            report_id=str(event.get("event_id") or new_event_id()),
            idempotency_key=idem,
            symbol=symbol,
            typ=status or "EXEC_REPORT",
            severity=sev,
            payload=event,
        )
    except Exception:
        pass

    return msg_id


def build_risk_event(
    *,
    typ: str,
    severity: str,
    symbol: Optional[str],
    detail: Dict[str, Any],
    trace_id: Optional[str] = None,
    retry_after_ms: Optional[int] = None,
    ext: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    detail = detail or {}
    n_type = normalize_risk_type(typ)
    n_sev = normalize_risk_severity(severity)

    # Preserve legacy values if normalized
    payload_detail = dict(detail)
    if (typ or "").strip().upper() != n_type:
        payload_detail.setdefault("legacy_type", typ)
    if (severity or "").strip().upper() != n_sev:
        payload_detail.setdefault("legacy_severity", severity)

    payload: Dict[str, Any] = {
        "type": n_type,
        "severity": n_sev,
        "detail": payload_detail,
        "ext": dict(ext or {}),
    }
    if symbol:
        payload["symbol"] = symbol
    if retry_after_ms is not None:
        try:
            payload["retry_after_ms"] = int(retry_after_ms)
        except Exception:
            pass

    event = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "env": settings.env,
        "service": "execution-service",
        "trace_id": trace_id or new_trace_id(),
        "schema_version": 1,
        "meta": {},
        "payload": payload,
        "ext": {},
    }
    validate(RISK_EVENT_SCHEMA, event)
    return event


def publish_risk_event(redis_url: str, event: Dict[str, Any]) -> str:
    client = RedisStreamsClient(redis_url)
    return publish_event(client, STREAM_RISK, event, event_type="risk_event")
