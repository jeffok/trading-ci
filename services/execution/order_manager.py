# -*- coding: utf-8 -*-
"""Stage 9: Order abnormal handling state machine (14.3).

Goals (without changing strategy rules):
- For ENTRY orders in LIVE mode, if configured as Limit:
  - Timeout -> cancel -> retry with repriced limit (N times) -> optional fallback to Market.
  - Partial fill that stalls -> cancel remainder -> optional market for remaining.
- Persist fills detail (via WS execution updates + DB `fills` table).
- Emit risk_event for each abnormal step to close the alert loop.

This module is intentionally conservative:
- Default entry order remains Market (no behavior change).
- Abnormal handling triggers only for orders with purpose=ENTRY and order_type=Limit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import datetime

from libs.common.config import settings
from libs.common.time import now_ms
from libs.common.id import new_event_id
from libs.bybit.trade_rest_v5 import TradeRestV5Client
from libs.bybit.errors import BybitError, is_rate_limit_error, extract_retry_after_ms



def _dt_to_ms(dt: Any) -> Optional[int]:
    if dt is None:
        return None
    if isinstance(dt, (int, float)):
        return int(dt)
    if isinstance(dt, datetime.datetime):
        if dt.tzinfo is None:
            # assume UTC
            return int(dt.timestamp() * 1000)
        return int(dt.timestamp() * 1000)
    return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def _compute_retry_price(*, base_price: float, side: str, bps: int, attempt: int) -> float:
    """Move limit price towards market to increase fill probability.
    BUY: price up; SELL: price down.
    attempt is 1-based.
    """
    mult = 1.0 + (float(bps) / 10000.0) * float(max(1, attempt))
    if str(side).upper() == "BUY":
        return base_price * mult
    return base_price / mult


def _emit_risk(redis_url: str, database_url: str, *, typ: str, severity: str, symbol: str, detail: Dict[str, Any]) -> None:
    from services.execution.publisher import build_risk_event, publish_risk_event
    from services.execution.repo import insert_risk_event
    trade_date = datetime.datetime.utcnow().date().isoformat()
    ev_id = new_event_id()
    ev = build_risk_event(
        event_id=ev_id,
        trade_date=trade_date,
        symbol=symbol,
        typ=typ,
        severity=severity,
        retry_after_ms=detail.get("retry_after_ms"),
        detail=detail,
        ext=detail.get("ext") or {},
    )
    publish_risk_event(redis_url, ev)
    insert_risk_event(database_url, event_id=ev_id, trade_date=trade_date, symbol=symbol, typ=typ,
                      severity=severity, retry_after_ms=detail.get("retry_after_ms"), detail=detail, ext=detail.get("ext") or {})

def _group_open_orders_by_symbol(client: TradeRestV5Client, symbols: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for sym in sorted(set([s for s in symbols if s])):
        try:
            rr = client.open_orders_cached(category=settings.bybit_category, symbol=sym)
            lst = (rr.get("result") or {}).get("list") or []
            out[sym] = lst if isinstance(lst, list) else []
        except Exception:
            out[sym] = []
    return out


def process_pending_entry_orders(database_url: str, redis_url: str, client: TradeRestV5Client) -> None:
    """Main entry point: handle ENTRY limit orders that are pending too long."""
    from services.execution.repo import list_orders_by_status, upsert_order

    if str(settings.execution_mode).upper() != "LIVE":
        return

    # Feature gate: only meaningful when user sets Limit entry.
    if str(getattr(settings, "execution_entry_order_type", "Market")).upper() != "LIMIT":
        return

    timeout_ms = int(getattr(settings, "execution_entry_timeout_ms", 15000))
    partial_timeout_ms = int(getattr(settings, "execution_entry_partial_fill_timeout_ms", 20000))
    max_retries = int(getattr(settings, "execution_entry_max_retries", 2))
    reprice_bps = int(getattr(settings, "execution_entry_reprice_bps", 5))
    fallback_market = bool(getattr(settings, "execution_entry_fallback_market", True))

    now = int(now_ms())
    orders = list_orders_by_status(database_url, status="SUBMITTED", purpose="ENTRY")
    if not orders:
        return

    symbols = [str(o.get("symbol") or "") for o in orders]
    open_orders_by_sym = _group_open_orders_by_symbol(client, symbols)

    for o in orders:
        try:
            symbol = str(o.get("symbol") or "")
            if not symbol:
                continue
            if str(o.get("order_type") or "").upper() != "LIMIT":
                # do not touch market entry
                continue

            order_id = str(o.get("order_id") or "")
            idem = str(o.get("idempotency_key") or "")
            side = str(o.get("side") or "")
            total_qty = float(o.get("qty") or 0.0)
            price = _safe_float(o.get("price")) or _safe_float((o.get("payload") or {}).get("entry_price")) or _safe_float((o.get("payload") or {}).get("base_price"))
            submitted_at_ms = o.get("submitted_at_ms") or (o.get("payload") or {}).get("submitted_at_ms") or _dt_to_ms(o.get("created_at"))
            retry_count = int(o.get("retry_count") or (o.get("payload") or {}).get("retry_count") or 0)

            # If we can find the matching open order, enrich with its state
            open_list = open_orders_by_sym.get(symbol) or []
            match = None
            bybit_order_id = str(o.get("bybit_order_id") or "")
            bybit_link = str(o.get("bybit_order_link_id") or "")
            for it in open_list:
                oid = str(it.get("orderId") or it.get("order_id") or "")
                olid = str(it.get("orderLinkId") or it.get("order_link_id") or "")
                if (bybit_order_id and oid == bybit_order_id) or (bybit_link and olid == bybit_link):
                    match = it
                    break

            # Determine fill progress (best-effort)
            filled_qty = _safe_float(o.get("filled_qty")) or _safe_float((o.get("payload") or {}).get("cum_exec_qty"))
            if match:
                filled_qty = _safe_float(match.get("cumExecQty") or match.get("cum_exec_qty")) or filled_qty
                avg_price = _safe_float(match.get("avgPrice") or match.get("avg_price")) or _safe_float(o.get("avg_price"))
                # update helper columns best-effort
                try:
                    upsert_order(
                        database_url,
                        order_id=order_id,
                        idempotency_key=idem,
                        symbol=symbol,
                        purpose="ENTRY",
                        side=side,
                        order_type="Limit",
                        qty=total_qty,
                        price=_safe_float(match.get("price")) or _safe_float(match.get("orderPrice")) or price,
                        reduce_only=bool(o.get("reduce_only") or False),
                        status="SUBMITTED",
                        bybit_order_id=o.get("bybit_order_id"),
                        bybit_order_link_id=o.get("bybit_order_link_id"),
                        payload=o.get("payload") or {},
                        submitted_at_ms=int(submitted_at_ms) if submitted_at_ms is not None else None,
                        retry_count=retry_count,
                        filled_qty=filled_qty,
                        avg_price=avg_price,
                        last_fill_at_ms=o.get("last_fill_at_ms"),
                    )
                except Exception:
                    pass

            # Decide if stalled
            age_ms = now - int(submitted_at_ms or now)
            if filled_qty is not None and filled_qty > 0:
                # partial fill stalled?
                last_fill = o.get("last_fill_at_ms") or (o.get("payload") or {}).get("last_fill_at_ms") or submitted_at_ms
                stall_ms = now - int(last_fill or now)
                if stall_ms < partial_timeout_ms:
                    continue
                _handle_partial_fill_stalled(
                    database_url,
                    redis_url,
                    client,
                    order=o,
                    filled_qty=float(filled_qty),
                    total_qty=total_qty,
                    retry_count=retry_count,
                    price=float(price) if price is not None else None,
                    reprice_bps=reprice_bps,
                    max_retries=max_retries,
                    fallback_market=fallback_market,
                )
                continue

            # not filled at all
            if age_ms < timeout_ms:
                continue
            _handle_timeout_no_fill(
                database_url,
                redis_url,
                client,
                order=o,
                age_ms=age_ms,
                retry_count=retry_count,
                base_price=float(price) if price is not None else None,
                reprice_bps=reprice_bps,
                max_retries=max_retries,
                fallback_market=fallback_market,
            )
        except Exception:
            # never break reconcile loop
            continue


def _cancel_best_effort(client: TradeRestV5Client, *, symbol: str, bybit_order_id: Optional[str], bybit_order_link_id: Optional[str]) -> Tuple[bool, Optional[int], Optional[str]]:
    try:
        rr = client.cancel_order(
            category=settings.bybit_category,
            symbol=symbol,
            order_id=bybit_order_id or None,
            order_link_id=bybit_order_link_id or None,
        )
        return True, None, None
    except BybitError as e:
        if is_rate_limit_error(e):
            return False, extract_retry_after_ms(e), "RATE_LIMIT"
        return False, None, str(e)
    except Exception as e:
        return False, None, str(e)


def _place_limit(client: TradeRestV5Client, *, symbol: str, side: str, qty: float, price: float, order_link_id: str) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    try:
        rr = client.place_order(
            category=settings.bybit_category,
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=str(qty),
            price=str(price),
            time_in_force="GTC",
            reduce_only=False,
            position_idx=settings.bybit_position_idx,
            order_link_id=order_link_id,
        )
        oid = str(((rr.get("result") or {}).get("orderId")) or "")
        return oid or None, order_link_id, None, None
    except BybitError as e:
        if is_rate_limit_error(e):
            return None, order_link_id, extract_retry_after_ms(e), "RATE_LIMIT"
        return None, order_link_id, None, str(e)
    except Exception as e:
        return None, order_link_id, None, str(e)


def _place_market(client: TradeRestV5Client, *, symbol: str, side: str, qty: float, order_link_id: str) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    try:
        rr = client.place_order(
            category=settings.bybit_category,
            symbol=symbol,
            side=side,
            order_type="Market",
            qty=str(qty),
            price=None,
            time_in_force="IOC",
            reduce_only=False,
            position_idx=settings.bybit_position_idx,
            order_link_id=order_link_id,
        )
        oid = str(((rr.get("result") or {}).get("orderId")) or "")
        return oid or None, order_link_id, None, None
    except BybitError as e:
        if is_rate_limit_error(e):
            return None, order_link_id, extract_retry_after_ms(e), "RATE_LIMIT"
        return None, order_link_id, None, str(e)
    except Exception as e:
        return None, order_link_id, None, str(e)


def _handle_timeout_no_fill(
    database_url: str,
    redis_url: str,
    client: TradeRestV5Client,
    *,
    order: Dict[str, Any],
    age_ms: int,
    retry_count: int,
    base_price: Optional[float],
    reprice_bps: int,
    max_retries: int,
    fallback_market: bool,
) -> None:
    from services.execution.repo import upsert_order
    symbol = str(order.get("symbol") or "")
    order_id = str(order.get("order_id") or "")
    idem = str(order.get("idempotency_key") or "")
    side = str(order.get("side") or "")
    total_qty = float(order.get("qty") or 0.0)
    bybit_order_id = str(order.get("bybit_order_id") or "") or None
    bybit_link = str(order.get("bybit_order_link_id") or "") or None

    _emit_risk(
        redis_url,
        database_url,
        typ="ORDER_TIMEOUT",
        severity="IMPORTANT",
        symbol=symbol,
        detail={"purpose": "ENTRY", "order_id": order_id, "age_ms": age_ms, "action": "cancel_retry_or_fallback"},
    )

    ok, retry_after, err = _cancel_best_effort(client, symbol=symbol, bybit_order_id=bybit_order_id, bybit_order_link_id=bybit_link)
    if not ok:
        # rate limit or error; emit and return (closed loop)
        typ = "RATE_LIMIT" if err == "RATE_LIMIT" else "RISK_REJECTED"
        _emit_risk(redis_url, database_url, typ=typ, severity="IMPORTANT", symbol=symbol, detail={
            "purpose": "ENTRY",
            "order_id": order_id,
            "action": "cancel_failed",
            "error": err,
            "retry_after_ms": retry_after,
        })
        return

    _emit_risk(redis_url, database_url, typ="ORDER_CANCELLED", severity="INFO", symbol=symbol, detail={
        "purpose": "ENTRY",
        "order_id": order_id,
        "reason": "timeout",
    })

    # retry or fallback
    attempt = retry_count + 1
    if attempt <= max_retries and base_price is not None:
        new_price = _compute_retry_price(base_price=base_price, side=side, bps=reprice_bps, attempt=attempt)
        new_link = f"{idem}:ENTRY:{attempt}"
        oid, olid, ra, err2 = _place_limit(client, symbol=symbol, side=side, qty=total_qty, price=new_price, order_link_id=new_link)
        if oid:
            payload = dict(order.get("payload") or {})
            payload.update({"submitted_at_ms": int(now_ms()), "retry_count": attempt, "base_price": base_price})
            upsert_order(
                database_url,
                order_id=order_id,
                idempotency_key=idem,
                symbol=symbol,
                purpose="ENTRY",
                side=side,
                order_type="Limit",
                qty=total_qty,
                price=float(new_price),
                reduce_only=False,
                status="SUBMITTED",
                bybit_order_id=oid,
                bybit_order_link_id=olid,
                payload=payload,
                submitted_at_ms=int(now_ms()),
                retry_count=attempt,
            )
            _emit_risk(redis_url, database_url, typ="ORDER_RETRY", severity="INFO", symbol=symbol, detail={
                "purpose": "ENTRY",
                "order_id": order_id,
                "attempt": attempt,
                "new_price": float(new_price),
            })
            return
        # retry placement failed
        typ = "RATE_LIMIT" if err2 == "RATE_LIMIT" else "RISK_REJECTED"
        _emit_risk(redis_url, database_url, typ=typ, severity="IMPORTANT", symbol=symbol, detail={
            "purpose": "ENTRY",
            "order_id": order_id,
            "action": "retry_place_failed",
            "attempt": attempt,
            "retry_after_ms": ra,
            "error": err2,
        })
        return

    if fallback_market:
        new_link = f"{idem}:ENTRY:FALLBACK"
        oid, olid, ra, err2 = _place_market(client, symbol=symbol, side=side, qty=total_qty, order_link_id=new_link)
        if oid:
            payload = dict(order.get("payload") or {})
            payload.update({"submitted_at_ms": int(now_ms()), "retry_count": attempt, "fallback_market": True})
            upsert_order(
                database_url,
                order_id=order_id,
                idempotency_key=idem,
                symbol=symbol,
                purpose="ENTRY",
                side=side,
                order_type="Market",
                qty=total_qty,
                price=None,
                reduce_only=False,
                status="SUBMITTED",
                bybit_order_id=oid,
                bybit_order_link_id=olid,
                payload=payload,
                submitted_at_ms=int(now_ms()),
                retry_count=attempt,
            )
            _emit_risk(redis_url, database_url, typ="ORDER_FALLBACK_MARKET", severity="IMPORTANT", symbol=symbol, detail={
                "purpose": "ENTRY",
                "order_id": order_id,
                "remaining_qty": total_qty,
            })
            return

        typ = "RATE_LIMIT" if err2 == "RATE_LIMIT" else "RISK_REJECTED"
        _emit_risk(redis_url, database_url, typ=typ, severity="IMPORTANT", symbol=symbol, detail={
            "purpose": "ENTRY",
            "order_id": order_id,
            "action": "fallback_place_failed",
            "retry_after_ms": ra,
            "error": err2,
        })


def _handle_partial_fill_stalled(
    database_url: str,
    redis_url: str,
    client: TradeRestV5Client,
    *,
    order: Dict[str, Any],
    filled_qty: float,
    total_qty: float,
    retry_count: int,
    price: Optional[float],
    reprice_bps: int,
    max_retries: int,
    fallback_market: bool,
) -> None:
    from services.execution.repo import upsert_order
    symbol = str(order.get("symbol") or "")
    order_id = str(order.get("order_id") or "")
    idem = str(order.get("idempotency_key") or "")
    side = str(order.get("side") or "")
    bybit_order_id = str(order.get("bybit_order_id") or "") or None
    bybit_link = str(order.get("bybit_order_link_id") or "") or None
    remaining = max(0.0, float(total_qty) - float(filled_qty))

    _emit_risk(redis_url, database_url, typ="ORDER_PARTIAL_FILL", severity="IMPORTANT", symbol=symbol, detail={
        "order_id": order_id,
        "filled_qty": float(filled_qty),
        "total_qty": float(total_qty),
        "action": "cancel_remaining_and_retry_or_fallback",
    })

    ok, retry_after, err = _cancel_best_effort(client, symbol=symbol, bybit_order_id=bybit_order_id, bybit_order_link_id=bybit_link)
    if not ok:
        typ = "RATE_LIMIT" if err == "RATE_LIMIT" else "RISK_REJECTED"
        _emit_risk(redis_url, database_url, typ=typ, severity="IMPORTANT", symbol=symbol, detail={
            "purpose": "ENTRY",
            "order_id": order_id,
            "action": "cancel_failed",
            "retry_after_ms": retry_after,
            "error": err,
        })
        return

    _emit_risk(redis_url, database_url, typ="ORDER_CANCELLED", severity="INFO", symbol=symbol, detail={
        "purpose": "ENTRY",
        "order_id": order_id,
        "reason": "partial_fill_stalled",
    })

    if remaining <= 0:
        return

    attempt = retry_count + 1
    if attempt <= max_retries and price is not None:
        new_price = _compute_retry_price(base_price=price, side=side, bps=reprice_bps, attempt=attempt)
        new_link = f"{idem}:ENTRY:{attempt}"
        oid, olid, ra, err2 = _place_limit(client, symbol=symbol, side=side, qty=remaining, price=new_price, order_link_id=new_link)
        if oid:
            payload = dict(order.get("payload") or {})
            payload.update({"submitted_at_ms": int(now_ms()), "retry_count": attempt, "base_price": price, "remaining_from_partial": True})
            upsert_order(
                database_url,
                order_id=order_id,
                idempotency_key=idem,
                symbol=symbol,
                purpose="ENTRY",
                side=side,
                order_type="Limit",
                qty=total_qty,
                price=float(new_price),
                reduce_only=False,
                status="SUBMITTED",
                bybit_order_id=oid,
                bybit_order_link_id=olid,
                payload=payload,
                submitted_at_ms=int(now_ms()),
                retry_count=attempt,
                filled_qty=float(filled_qty),
            )
            _emit_risk(redis_url, database_url, typ="ORDER_RETRY", severity="INFO", symbol=symbol, detail={
                "purpose": "ENTRY",
                "order_id": order_id,
                "attempt": attempt,
                "new_price": float(new_price),
                "remaining_qty": float(remaining),
            })
            return

        typ = "RATE_LIMIT" if err2 == "RATE_LIMIT" else "RISK_REJECTED"
        _emit_risk(redis_url, database_url, typ=typ, severity="IMPORTANT", symbol=symbol, detail={
            "purpose": "ENTRY",
            "order_id": order_id,
            "action": "retry_place_failed",
            "attempt": attempt,
            "retry_after_ms": ra,
            "error": err2,
        })
        return

    if fallback_market:
        new_link = f"{idem}:ENTRY:FALLBACK"
        oid, olid, ra, err2 = _place_market(client, symbol=symbol, side=side, qty=remaining, order_link_id=new_link)
        if oid:
            payload = dict(order.get("payload") or {})
            payload.update({"submitted_at_ms": int(now_ms()), "retry_count": attempt, "fallback_market": True, "remaining_from_partial": True})
            upsert_order(
                database_url,
                order_id=order_id,
                idempotency_key=idem,
                symbol=symbol,
                purpose="ENTRY",
                side=side,
                order_type="Market",
                qty=total_qty,
                price=None,
                reduce_only=False,
                status="SUBMITTED",
                bybit_order_id=oid,
                bybit_order_link_id=olid,
                payload=payload,
                submitted_at_ms=int(now_ms()),
                retry_count=attempt,
                filled_qty=float(filled_qty),
            )
            _emit_risk(redis_url, database_url, typ="ORDER_FALLBACK_MARKET", severity="IMPORTANT", symbol=symbol, detail={
                "purpose": "ENTRY",
                "order_id": order_id,
                "remaining_qty": float(remaining),
            })
            return

        typ = "RATE_LIMIT" if err2 == "RATE_LIMIT" else "RISK_REJECTED"
        _emit_risk(redis_url, database_url, typ=typ, severity="IMPORTANT", symbol=symbol, detail={
            "purpose": "ENTRY",
            "order_id": order_id,
            "action": "fallback_place_failed",
            "retry_after_ms": ra,
            "error": err2,
        })
