# -*- coding: utf-8 -*-
"""Stage 7: 私有 WS 摄取（WS+REST 双机制一致性：WS 为主，REST 为兜底）

职责：
- 连接 Bybit V5 private WS，订阅 order/execution/position/wallet
- 将原始 WS 事件落库到 ws_events（便于审计与排障）
- 识别关键更新（订单成交/撤单等），更新 orders 表的 status/payload（best-effort）
- 在重要事件上发布 execution_report（用于通知与 API，可追踪计划执行）
- 连接/重连时发布 risk_event: WS_RECONNECT（用于可观测性）

约束：
- 不改变策略逻辑，只补齐“状态来源”与“一致性信息流”
- 异常不应阻塞主执行：catch + risk_event
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from libs.common.config import settings
from libs.common.time import now_ms
from libs.bybit.ws_private import BybitV5PrivateWsClient

from services.execution import repo
from services.execution.publisher import (
    build_execution_report,
    publish_execution_report,
    build_risk_event,
    publish_risk_event,
)

logger = logging.getLogger(__name__)


def _norm_order_status(s: str) -> str:
    ss = (s or "").lower()
    if ss in ("filled", "fill", "done"):
        return "FILLED"
    if ss in ("cancelled", "canceled", "cancel"):
        return "CANCELED"
    if ss in ("partiallyfilled", "partial", "partially_filled"):
        return "PARTIAL_FILLED"
    if ss in ("new", "created", "submitted", "active"):
        return "SUBMITTED"
    if ss in ("rejected", "reject"):
        return "FAILED"
    return "SUBMITTED" if ss else "SUBMITTED"


def _extract_symbol(msg: Dict[str, Any]) -> Optional[str]:
    data = msg.get("data")
    if isinstance(data, list) and data:
        sym = data[0].get("symbol") or data[0].get("s")
        if sym:
            return str(sym)
    return None


def _extract_order_ids(item: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    oid = item.get("orderId") or item.get("order_id") or item.get("id")
    olid = item.get("orderLinkId") or item.get("order_link_id") or item.get("orderLinkID") or item.get("orderLinkid")
    return (str(oid) if oid is not None else None, str(olid) if olid is not None else None)


def _derive_legacy_typ(purpose: str, status: str) -> str:
    p = (purpose or "").upper()
    st = (status or "").upper()
    if st == "FILLED":
        if p == "ENTRY":
            return "ENTRY_FILLED"
        if p.startswith("TP"):
            return "TP_FILLED"
        if p in ("EXIT", "SL_ADJUST"):
            return "EXITED"
        return "EXITED"
    if st in ("CANCELED", "FAILED"):
        return "ORDER_REJECTED"
    # partial/submitted
    if p == "ENTRY":
        return "ENTRY_SUBMITTED"
    if p in ("EXIT",) or p.startswith("TP"):
        return "EXIT_SUBMITTED"
    return "ENTRY_SUBMITTED"


async def _emit_exec_report_from_order(
    *,
    ord_row: Dict[str, Any],
    symbol: str,
    bybit_order_id: Optional[str],
    bybit_order_link_id: Optional[str],
    status: str,
    status_raw: str,
    avg_price: Optional[float],
    filled_qty: Optional[float],
    reason: str,
    ws_payload: Dict[str, Any],
) -> None:
    payload = ord_row.get("payload") or {}
    idem = str(ord_row.get("idempotency_key") or "")
    plan_id = str(payload.get("plan_id") or payload.get("trade_plan_id") or payload.get("idempotency_key") or idem)

    typ = _derive_legacy_typ(str(ord_row.get("purpose")), status)
    detail = {
        "purpose": ord_row.get("purpose"),
        "bybit_order_id": bybit_order_id,
        "bybit_order_link_id": bybit_order_link_id,
        "order_status": status_raw,
        "ws": True,
        "ws_reason": reason,
    }
    ext = {
        "ws": True,
        "avg_price": avg_price,
        "filled_qty": filled_qty,
        "ws_payload": ws_payload,
        "plan_id": plan_id,
        "timeframe": payload.get("timeframe"),
    }
    er = build_execution_report(
        idempotency_key=idem,
        symbol=symbol,
        typ=typ,
        severity="IMPORTANT" if status in ("FILLED", "PARTIAL_FILLED") else "INFO",
        detail=detail,
        ext=ext,
        trace_id=None,
    )
    await publish_execution_report(er)


async def _handle_order_update(msg: Dict[str, Any]) -> None:
    data = msg.get("data") or []
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict):
            continue
        bybit_order_id, bybit_order_link_id = _extract_order_ids(item)
        symbol = str(item.get("symbol") or item.get("s") or _extract_symbol(msg) or "").strip() or None
        status_raw = str(item.get("orderStatus") or item.get("order_status") or item.get("status") or "")
        status = _norm_order_status(status_raw)

        # 审计落库
        try:
            repo.insert_ws_event(settings.database_url, topic="order", symbol=symbol, payload=item)
        except Exception:
            logger.exception("ws_event_insert_failed", extra={"extra_fields": {"topic": "order"}})

        # best-effort 同步本地 orders
        try:
            ord_row = repo.get_order_by_bybit_ids(
                settings.database_url, bybit_order_id=bybit_order_id, bybit_order_link_id=bybit_order_link_id
            )
            if ord_row is None:
                continue
            repo.update_order_status_from_ws(
                settings.database_url,
                order_id=str(ord_row["order_id"]),
                new_status=status,
                bybit_order_id=bybit_order_id,
                bybit_order_link_id=bybit_order_link_id,
                ws_payload=item,
            )

            # Stage 7.1: when TP1/TP2 is filled (from WS), mirror status into positions.meta so reconcile can skip REST polling.
            try:
                pur = str(ord_row.get("purpose") or "").upper()
                if status == "FILLED" and pur in ("TP1", "TP2"):
                    patch = {
                        f"{pur.lower()}_filled": True,
                        f"{pur.lower()}_filled_ms": int(now_ms()),
                        "tp_source": "ws",
                    }
                    repo.merge_position_meta_by_idem(
                        settings.database_url,
                        idempotency_key=str(ord_row.get("idempotency_key") or ""),
                        patch=patch,
                    )
            except Exception:
                logger.exception("ws_tp_meta_merge_failed")
            if symbol:
                avg_price = item.get("avgPrice") or item.get("avg_price")
                filled_qty = item.get("cumExecQty") or item.get("cum_exec_qty")
                await _emit_exec_report_from_order(
                    ord_row=ord_row,
                    symbol=symbol,
                    bybit_order_id=bybit_order_id,
                    bybit_order_link_id=bybit_order_link_id,
                    status=status,
                    status_raw=status_raw,
                    avg_price=float(avg_price) if avg_price is not None and str(avg_price) != "" else None,
                    filled_qty=float(filled_qty) if filled_qty is not None and str(filled_qty) != "" else None,
                    reason="WS_ORDER_UPDATE",
                    ws_payload=item,
                )
        except Exception:
            logger.exception("ws_order_update_failed")


async def _handle_execution_update(msg: Dict[str, Any]) -> None:
    data = msg.get("data") or []
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict):
            continue
        bybit_order_id, bybit_order_link_id = _extract_order_ids(item)
        symbol = str(item.get("symbol") or item.get("s") or _extract_symbol(msg) or "").strip() or None

        try:
            repo.insert_ws_event(settings.database_url, topic="execution", symbol=symbol, payload=item)
        except Exception:
            logger.exception("ws_event_insert_failed", extra={"extra_fields": {"topic": "execution"}})

        try:
            ord_row = repo.get_order_by_bybit_ids(
                settings.database_url, bybit_order_id=bybit_order_id, bybit_order_link_id=bybit_order_link_id
            )
            if ord_row is None:
                continue
            # Stage 9: normalize fill payload and persist
            try:
                exec_price = item.get("execPrice") or item.get("exec_price")
                exec_qty = item.get("execQty") or item.get("exec_qty")
                exec_fee = item.get("execFee") or item.get("exec_fee")
                exec_time = item.get("execTime") or item.get("exec_time") or item.get("tradeTime") or item.get("trade_time")
                bybit_exec_id = item.get("execId") or item.get("exec_id")
                norm_fill = {
                    "idempotency_key": str(ord_row.get("idempotency_key") or ""),
                    "order_id": str(ord_row.get("order_id") or ""),
                    "symbol": str(symbol or ord_row.get("symbol") or ""),
                    "purpose": str(ord_row.get("purpose") or ""),
                    "side": str(ord_row.get("side") or ""),
                    "exec_qty": float(exec_qty) if exec_qty is not None and str(exec_qty) != "" else 0.0,
                    "exec_price": float(exec_price) if exec_price is not None and str(exec_price) != "" else 0.0,
                    "exec_fee": float(exec_fee) if exec_fee is not None and str(exec_fee) != "" else None,
                    "exec_time_ms": int(exec_time) if exec_time is not None and str(exec_time) != "" else None,
                    "bybit_exec_id": str(bybit_exec_id) if bybit_exec_id is not None and str(bybit_exec_id) != "" else None,
                    "bybit_order_id": str(bybit_order_id or "") or None,
                    "bybit_order_link_id": str(bybit_order_link_id or "") or None,
                    "raw": item,
                }
                repo.append_order_fill_from_ws(settings.database_url, order_id=str(ord_row["order_id"]), fill=norm_fill)
            except Exception:
                logger.exception("ws_fill_persist_failed")

            # Stage 10: if fills indicate order completed, eagerly mark it FILLED (eventual convergence)
            try:
                prog = repo.get_order_fill_progress(settings.database_url, order_id=str(ord_row["order_id"]))
                if prog and prog.get("qty") and prog.get("filled_qty") is not None:
                    if float(prog["filled_qty"]) >= float(prog["qty"]) * 0.999 and str(prog.get("status") or "").upper() not in ("FILLED", "CANCELED", "FAILED"):
                        repo.update_order_status_from_ws(
                            settings.database_url,
                            order_id=str(ord_row["order_id"]),
                            new_status="FILLED",
                            bybit_order_id=bybit_order_id,
                            bybit_order_link_id=bybit_order_link_id,
                            ws_payload=item,
                        )
                        if symbol:
                            await _emit_exec_report_from_order(
                                ord_row=ord_row,
                                symbol=symbol,
                                bybit_order_id=bybit_order_id,
                                bybit_order_link_id=bybit_order_link_id,
                                status="FILLED",
                                status_raw="ExecutionFillComplete",
                                avg_price=None,
                                filled_qty=float(prog["filled_qty"]),
                                reason="WS_EXECUTION_CONVERGE_FILLED",
                                ws_payload=item,
                            )
            except Exception:
                logger.exception("ws_execution_converge_failed")





            if symbol:
                exec_price = item.get("execPrice") or item.get("exec_price")
                exec_qty = item.get("execQty") or item.get("exec_qty")
                # 对 execution 消息我们默认认为至少是 partial
                await _emit_exec_report_from_order(
                    ord_row=ord_row,
                    symbol=symbol,
                    bybit_order_id=bybit_order_id,
                    bybit_order_link_id=bybit_order_link_id,
                    status="PARTIAL_FILLED",
                    status_raw="Execution",
                    avg_price=float(exec_price) if exec_price is not None and str(exec_price) != "" else None,
                    filled_qty=float(exec_qty) if exec_qty is not None and str(exec_qty) != "" else None,
                    reason="WS_EXECUTION_UPDATE",
                    ws_payload=item,
                )
        except Exception:
            logger.exception("ws_execution_update_failed")


async def _handle_position_update(msg: Dict[str, Any]) -> None:
    data = msg.get("data") or []
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or item.get("s") or _extract_symbol(msg) or "").strip() or None
        try:
            repo.insert_ws_event(settings.database_url, topic="position", symbol=symbol, payload=item)
        except Exception:
            logger.exception("ws_event_insert_failed", extra={"extra_fields": {"topic": "position"}})
        try:
            repo.upsert_position_snapshot_from_ws(settings.database_url, payload=item)
        except Exception:
            logger.exception("ws_position_snapshot_failed")


async def _handle_wallet_update(msg: Dict[str, Any]) -> None:
    symbol = _extract_symbol(msg)
    payload = msg.get("data") or msg
    try:
        repo.insert_ws_event(settings.database_url, topic="wallet", symbol=symbol, payload=payload)
    except Exception:
        logger.exception("ws_event_insert_failed", extra={"extra_fields": {"topic": "wallet"}})

    # Stage 10: persist wallet snapshot from WS for drift detection (observability only)
    try:
        repo.upsert_wallet_snapshot_from_ws(settings.database_url, payload=payload, ts_ms=int(now_ms()))
    except Exception:
        logger.exception("ws_wallet_snapshot_failed")



async def handle_private_ws_message(msg: Dict[str, Any]) -> None:
    topic = str(msg.get("topic") or msg.get("dataType") or msg.get("channel") or "")
    # ignore ping/subscribe/auth ack
    if msg.get("op") in ("subscribe", "auth") or msg.get("type") in ("pong", "ping", "AUTH_RESP"):
        return
    if "order" in topic:
        await _handle_order_update(msg); return
    if "execution" in topic:
        await _handle_execution_update(msg); return
    if "position" in topic:
        await _handle_position_update(msg); return
    if "wallet" in topic:
        await _handle_wallet_update(msg); return
    # fallback audit
    try:
        repo.insert_ws_event(settings.database_url, topic=topic or "unknown", symbol=_extract_symbol(msg), payload=msg)
    except Exception:
        logger.exception("ws_event_insert_failed", extra={"extra_fields": {"topic": topic or "unknown"}})


async def run_private_ws_ingest_loop() -> None:
    if not bool(getattr(settings, "bybit_private_ws_enabled", False)):
        logger.info("private_ws_disabled")
        while True:
            await asyncio.sleep(60.0)

    if str(getattr(settings, "execution_mode", "")).upper() != "LIVE":
        logger.info("private_ws_skip_non_live", extra={"extra_fields": {"execution_mode": settings.execution_mode}})
        while True:
            await asyncio.sleep(60.0)

    if not settings.bybit_api_key or not settings.bybit_api_secret:
        logger.warning("private_ws_missing_keys")
        while True:
            await asyncio.sleep(60.0)

    ws_url = getattr(settings, "bybit_private_ws_url", "wss://stream.bybit.com/v5/private")
    auth_path = getattr(settings, "bybit_private_ws_auth_path", "/realtime")
    subs = getattr(settings, "bybit_private_ws_subscriptions", "order,execution,position,wallet")
    subscriptions = [s.strip() for s in str(subs).split(",") if s.strip()]

    async def _on_connected(connect_count: int) -> None:
        ev = build_risk_event(
            typ="WS_RECONNECT",
            severity="INFO",
            symbol=None,
            detail={"event": "WS_PRIVATE_CONNECTED", "connect_count": connect_count, "ws_url": ws_url},
            retry_after_ms=None,
            ext={"ws": True},
            trace_id=None,
        )
        await publish_risk_event(ev)

    async def _on_disconnected(reason: str) -> None:
        ev = build_risk_event(
            typ="WS_RECONNECT",
            severity="IMPORTANT",
            symbol=None,
            detail={"event": "WS_PRIVATE_DISCONNECTED", "reason": reason, "ws_url": ws_url},
            retry_after_ms=None,
            ext={"ws": True},
            trace_id=None,
        )
        await publish_risk_event(ev)

    client = BybitV5PrivateWsClient(
        ws_url=ws_url,
        api_key=settings.bybit_api_key,
        api_secret=settings.bybit_api_secret,
        subscriptions=subscriptions,
        auth_path=auth_path,
        on_connected=_on_connected,
        on_disconnected=_on_disconnected,
        on_message=handle_private_ws_message,
    )
    await client.run_forever()
