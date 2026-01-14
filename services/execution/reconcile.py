# -*- coding: utf-8 -*-
"""执行对账/状态机（Phase 4 + Stage 7.1）

目标：在不改变策略规则的前提下，把“分段止盈 + Runner trailing”在实盘落地，并做 WS+REST 一致性闭环：
- 识别 TP1/TP2 是否成交（WS 优先，REST 兜底）
- TP1 成交后：把 SL 上移到入场价（保本）
- TP2 成交后：Runner 跟随止损开始“实盘生效”
- Stage 6.1：Runner trailing 的 stopLoss 在 TP2 之后可以持续更新（只更严格，不放松）
- Stage 7.1：
  - BYBIT_PRIVATE_WS_ENABLED=true 时，尽量减少 private REST open_orders 轮询（按间隔退避）
  - 对 WS position 快照与本地 positions 关键字段做一致性漂移检测（CONSISTENCY_DRIFT）
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import datetime

from libs.common.config import settings
from libs.bybit.trade_rest_v5 import TradeRestV5Client
from libs.bybit.errors import BybitError, is_rate_limit_error, extract_retry_after_ms

from libs.common.time import now_ms
from libs.common.id import new_event_id
from services.execution.repo import list_open_positions, save_position, insert_risk_event
from services.execution.publisher import build_execution_report, publish_execution_report, build_risk_event, publish_risk_event
from services.execution.order_manager import process_pending_entry_orders


def _bybit() -> TradeRestV5Client:
    return TradeRestV5Client(base_url=settings.bybit_rest_base_url)


def _as_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def _tightens_stop(*, bias: str, old: Optional[float], new: float) -> bool:
    """Return True if new stop is tighter (more protective) than old."""
    if old is None:
        return True
    b = (bias or "").upper()
    if b == "LONG":
        return new > float(old)
    if b == "SHORT":
        return new < float(old)
    # fallback by side-like semantics: LONG if BUY else SHORT
    return new > float(old)


def _extract_ws_position_size(ws_pos: Dict[str, Any]) -> Optional[float]:
    # bybit v5 position payload keys vary; try common ones
    for k in ("size", "qty", "positionSize", "position_size", "positionQty", "position_qty"):
        v = ws_pos.get(k)
        f = _as_float(v)
        if f is not None:
            return abs(float(f))
    return None


def reconcile(database_url: str, redis_url: str) -> None:
    if str(settings.execution_mode).upper() != "LIVE":
        return

    client = _bybit()
    trade_date = datetime.datetime.utcnow().date().isoformat()
    now = int(now_ms())

    # Stage 9: handle pending ENTRY limit orders (14.3)
    try:
        process_pending_entry_orders(database_url, redis_url, client)
    except Exception:
        pass

    for p in list_open_positions(database_url):
        symbol = p["symbol"]
        idem = p["idempotency_key"]
        meta = dict(p.get("meta") or {})
        changed = False

        # ---------------- Stage 7.1: WS/DB consistency drift ----------------
        if getattr(settings, "consistency_drift_enabled", True):
            ws_pos = meta.get("ws_position") if isinstance(meta.get("ws_position"), dict) else None
            if isinstance(ws_pos, dict) and ws_pos:
                try:
                    ws_size = _extract_ws_position_size(ws_pos)
                    local_size = _as_float(p.get("qty_total"))
                    if ws_size is not None and local_size is not None and local_size > 0:
                        drift = abs(ws_size - local_size) / max(local_size, 1e-9)
                        thr = float(getattr(settings, "consistency_drift_threshold_pct", 0.10))
                        if drift >= thr:
                            last_ms = int(meta.get("consistency_drift_last_ms") or 0)
                            window_ms = int(getattr(settings, "consistency_drift_window_ms", 300000))
                            if now - last_ms >= window_ms:
                                meta["consistency_drift_last_ms"] = now
                                changed = True
                                ev = build_risk_event(
                                    typ="CONSISTENCY_DRIFT",
                                    severity="IMPORTANT",
                                    symbol=symbol,
                                    detail={
                                        "local_qty_total": local_size,
                                        "ws_size": ws_size,
                                        "drift_pct": drift,
                                        "threshold_pct": thr,
                                        "idempotency_key": idem,
                                    },
                                )
                                publish_risk_event(redis_url, ev)
                                insert_risk_event(
                                    database_url,
                                    event_id=new_event_id(),
                                    trade_date=trade_date,
                                    ts_ms=now,
                                    typ="CONSISTENCY_DRIFT",
                                    severity="IMPORTANT",
                                    detail={
                                        "symbol": symbol,
                                        "local_qty_total": local_size,
                                        "ws_size": ws_size,
                                        "drift_pct": drift,
                                        "threshold_pct": thr,
                                        "idempotency_key": idem,
                                    },
                                )
                except Exception:
                    # do not break reconcile
                    pass

        # ---------------- TP status source selection (WS preferred) ----------------
        tp1_filled = bool(meta.get("tp1_filled"))
        tp2_filled = bool(meta.get("tp2_filled"))

        # Decide whether to poll private REST open_orders for this symbol
        need_poll = True
        if getattr(settings, "bybit_private_ws_enabled", False):
            last_poll = int(meta.get("open_orders_last_poll_ms") or 0)
            interval_ms = int(float(getattr(settings, "reconcile_open_orders_poll_interval_sec", 5.0)) * 1000)
            if last_poll > 0 and now - last_poll < interval_ms:
                need_poll = False

        if need_poll:
            try:
                rr = client.open_orders(category=settings.bybit_category, symbol=symbol, open_only=0)
            except BybitError as e:
                if is_rate_limit_error(e):
                    ra = extract_retry_after_ms(e)
                    ev = build_risk_event(
                        typ="RATE_LIMIT",
                        severity="IMPORTANT",
                        symbol=symbol,
                        retry_after_ms=int(ra) if ra is not None else None,
                        detail={
                            "ret_code": getattr(e, "ret_code", None),
                            "ret_msg": getattr(e, "ret_msg", None),
                            "endpoint": "/v5/order/realtime",
                            "context": "reconcile.open_orders",
                        },
                    )
                    publish_risk_event(redis_url, ev)
                    insert_risk_event(
                        database_url,
                        event_id=new_event_id(),
                        trade_date=trade_date,
                        ts_ms=now,
                        typ="RATE_LIMIT",
                        severity="IMPORTANT",
                        detail={
                            "context": "reconcile.open_orders",
                            "retry_after_ms": int(ra) if ra is not None else None,
                            "symbol": symbol,
                        },
                    )
                rr = {"result": {"list": []}}
            except Exception as e:
                rr = {"result": {"list": []}}
            meta["open_orders_last_poll_ms"] = now
            changed = True

            lst = rr.get("result", {}).get("list", []) or []
            tp1_link = idem[:28] + "_TP1"
            tp2_link = idem[:28] + "_TP2"
            # Stage 8: order timeout / partial fill alerts (observability first)
            timeout_ms = int(float(getattr(settings, "order_poll_timeout_sec", 20.0)) * 1000)
            alert_window_ms = int(getattr(settings, "order_timeout_alert_window_ms", 60000))
            for it in lst:
                if it.get("orderLinkId") == tp1_link and it.get("orderStatus") == "Filled":
                    tp1_filled = True
                if it.get("orderLinkId") == tp2_link and it.get("orderStatus") == "Filled":
                    tp2_filled = True

                try:
                    link = str(it.get("orderLinkId") or "")
                    status = str(it.get("orderStatus") or "")
                    created = int(float(it.get("createdTime") or 0))
                    if created > 0 and status in ("New", "PartiallyFilled"):
                        age = now - created
                        if age >= timeout_ms:
                            last_key = f"order_timeout_last_ms:{link}"
                            last_ms = int(meta.get(last_key) or 0)
                            if last_ms == 0 or now - last_ms >= alert_window_ms:
                                meta[last_key] = now
                                changed = True
                                ev = build_risk_event(
                                    typ="ORDER_TIMEOUT",
                                    severity="IMPORTANT",
                                    symbol=symbol,
                                    detail={
                                        "order_link_id": link,
                                        "order_id": it.get("orderId"),
                                        "status": status,
                                        "age_ms": age,
                                        "timeout_ms": timeout_ms,
                                        "cum_exec_qty": it.get("cumExecQty"),
                                        "qty": it.get("qty"),
                                        "context": "reconcile.open_orders",
                                    },
                                )
                                publish_risk_event(redis_url, ev)

                        if status == "PartiallyFilled":
                            last_key = f"order_partial_last_ms:{link}"
                            last_ms = int(meta.get(last_key) or 0)
                            if last_ms == 0 or now - last_ms >= alert_window_ms:
                                meta[last_key] = now
                                changed = True
                                ev = build_risk_event(
                                    typ="ORDER_PARTIAL_FILL",
                                    severity="INFO",
                                    symbol=symbol,
                                    detail={
                                        "order_link_id": link,
                                        "order_id": it.get("orderId"),
                                        "status": status,
                                        "cum_exec_qty": it.get("cumExecQty"),
                                        "qty": it.get("qty"),
                                        "context": "reconcile.open_orders",
                                    },
                                )
                                publish_risk_event(redis_url, ev)
                except Exception:
                    pass

            # mirror detection into meta (so next loop can skip)
            if tp1_filled and not meta.get("tp1_filled"):
                meta["tp1_filled"] = True
                meta["tp1_filled_ms"] = now
                meta["tp_source"] = "rest"
                changed = True
            if tp2_filled and not meta.get("tp2_filled"):
                meta["tp2_filled"] = True
                meta["tp2_filled_ms"] = now
                meta["tp_source"] = "rest"
                changed = True

        # ---------------- TP1: SL -> breakeven (must run even if tp1_filled came from WS) ----------------
        if tp1_filled and not meta.get("tp1_be_applied"):
            try:
                client.set_trading_stop(
                    category=settings.bybit_category,
                    symbol=symbol,
                    position_idx=int(settings.bybit_position_idx),
                    stop_loss=str(float(p["entry_price"])),
                    tpsl_mode="Full",
                )
                meta["tp1_be_applied"] = True
                changed = True
                rep = build_execution_report(
                    idempotency_key=idem,
                    symbol=symbol,
                    typ="SL_UPDATE",
                    severity="IMPORTANT",
                    detail={"reason": "TP1_FILLED_SL_TO_BREAKEVEN", "stop_loss": float(p["entry_price"]), "source": meta.get("tp_source")},
                )
                publish_execution_report(redis_url, rep)
            except BybitError as e:
                if is_rate_limit_error(e):
                    ra = extract_retry_after_ms(e)
                    ev = build_risk_event(
                        typ="RATE_LIMIT",
                        severity="IMPORTANT",
                        symbol=symbol,
                        retry_after_ms=int(ra) if ra is not None else None,
                        detail={"endpoint": "/v5/position/trading-stop", "context": "reconcile.tp1_be", "ret_code": e.ret_code, "ret_msg": e.ret_msg},
                    )
                    publish_risk_event(redis_url, ev)
            except Exception as e:
                rep = build_execution_report(
                    idempotency_key=idem,
                    symbol=symbol,
                    typ="ERROR",
                    severity="IMPORTANT",
                    detail={"stage": "SET_SL_BE", "error": repr(e)},
                )
                publish_execution_report(redis_url, rep)

        # ---------------- TP2: mark runner trailing enabled (informational) ----------------
        if tp2_filled and not meta.get("tp2_seen"):
            meta["tp2_seen"] = True
            changed = True
            rep = build_execution_report(
                idempotency_key=idem,
                symbol=symbol,
                typ="TP_FILLED",
                severity="INFO",
                detail={"tp": "TP2", "runner_trailing_enabled": True, "source": meta.get("tp_source")},
            )
            publish_execution_report(redis_url, rep)

        # ---------------- Stage 6.1: Runner trailing stop live update ----------------
        if getattr(settings, "runner_live_update_enabled", True) and tp2_filled and p.get("runner_stop_price") is not None:
            new_sl = float(p["runner_stop_price"])
            old_sl = _as_float(meta.get("runner_sl_last_applied"))
            last_ms = int(meta.get("runner_sl_last_applied_ms") or 0)
            min_int = int(getattr(settings, "runner_live_update_min_interval_ms", 3000))
            if _tightens_stop(bias=str(p.get("bias") or ""), old=old_sl, new=new_sl) and (last_ms == 0 or now - last_ms >= min_int):
                try:
                    client.set_trading_stop(
                        category=settings.bybit_category,
                        symbol=symbol,
                        position_idx=int(settings.bybit_position_idx),
                        stop_loss=str(float(new_sl)),
                        tpsl_mode="Full",
                    )
                    meta["runner_sl_last_applied"] = float(new_sl)
                    meta["runner_sl_last_applied_ms"] = now
                    meta["runner_sl_applied"] = True
                    changed = True
                    rep = build_execution_report(
                        idempotency_key=idem,
                        symbol=symbol,
                        typ="SL_UPDATE",
                        severity="INFO",
                        detail={"reason": "RUNNER_TRAIL_APPLIED", "stop_loss": float(new_sl)},
                    )
                    publish_execution_report(redis_url, rep)
                except BybitError as e:
                    if is_rate_limit_error(e):
                        ra = extract_retry_after_ms(e)
                        ev = build_risk_event(
                            typ="RATE_LIMIT",
                            severity="IMPORTANT",
                            symbol=symbol,
                            retry_after_ms=int(ra) if ra is not None else None,
                            detail={"endpoint": "/v5/position/trading-stop", "context": "reconcile.runner_trail", "ret_code": e.ret_code, "ret_msg": e.ret_msg},
                        )
                        publish_risk_event(redis_url, ev)
                except Exception as e:
                    rep = build_execution_report(
                        idempotency_key=idem,
                        symbol=symbol,
                        typ="ERROR",
                        severity="IMPORTANT",
                        detail={"stage": "APPLY_RUNNER_SL", "error": repr(e)},
                    )
                    publish_execution_report(redis_url, rep)

        if changed:
            save_position(
                database_url,
                position_id=p["position_id"],
                idempotency_key=idem,
                symbol=p["symbol"],
                timeframe=p["timeframe"],
                side=p["side"],
                bias=p["bias"],
                qty_total=p["qty_total"],
                qty_runner=p["qty_runner"],
                entry_price=p["entry_price"],
                primary_sl_price=p["primary_sl_price"],
                runner_stop_price=p["runner_stop_price"],
                status=p["status"],
                entry_close_time_ms=p["entry_close_time_ms"],
                opened_at_ms=p["opened_at_ms"],
                secondary_rule_checked=p["secondary_rule_checked"],
                hist_entry=p["hist_entry"],
                meta=meta,
            )


# compatibility shim

def run_reconcile_once(database_url: str, redis_url: str) -> None:
    return reconcile(database_url, redis_url)
