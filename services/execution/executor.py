# -*- coding: utf-8 -*-
"""执行器（Phase 3/4 + Backtest/Paper 闭环）

该模块把 strategy-service 产生的 trade_plan 变成“可执行动作”，并把结果：
- 落库（orders / positions）
- 事件化（execution_report / risk_event）

重要：不改变策略，只做执行与工程闭环。

支持三种模式（settings.execution_mode）：
- live：调用 Bybit 下单/设置止损/挂 TP
- paper/backtest：不调用交易所，直接模拟“ENTRY 立即成交 + TP 挂单”，后续由 paper_sim
  在 stream:bar_close 的 OHLC 上模拟撮合 TP/SL/Runner 出场。
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Dict, Optional

from libs.bybit.trade_rest_v5 import TradeRestV5Client
from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.execution.risk import InstrumentFilters, calc_qty, split_tp_qty, tp_prices
from libs.mq.locks import acquire_lock, release_lock

from services.execution.publisher import build_execution_report, publish_execution_report, build_risk_event, publish_risk_event
from services.execution.repo import (
    upsert_order,
    upsert_position,
    get_position_by_idem,
    get_or_init_risk_state,
)

logger = setup_logging("execution-executor")


def _parse_instrument_filters(symbol: str) -> InstrumentFilters:
    """从 Bybit instruments-info 解析 qtyStep/minOrderQty/tickSize。失败则返回保守默认值。"""
    try:
        c = TradeRestV5Client(base_url=settings.bybit_rest_base_url)
        r = c.instruments_info(category=settings.bybit_category, symbol=symbol)
        lst = (r.get("result") or {}).get("list") or []
        if lst:
            it = lst[0]
            lot = it.get("lotSizeFilter") or {}
            price = it.get("priceFilter") or {}
            qty_step = float(lot.get("qtyStep") or 0.001)
            min_qty = float(lot.get("minOrderQty") or 0.001)
            tick = float(price.get("tickSize") or 0.1)
            return InstrumentFilters(qty_step=qty_step, min_qty=min_qty, tick_size=tick)
    except Exception:
        pass
    return InstrumentFilters(qty_step=0.001, min_qty=0.001, tick_size=0.1)


def _equity_usdt() -> float:
    """获取可用资金（USDT）。paper/backtest 下允许无 API Key。"""
    mode = str(settings.execution_mode).upper()
    # backtest/paper：优先用环境变量，不依赖交易所私有接口
    if mode in ("PAPER", "BACKTEST"):
        v = os.environ.get("BACKTEST_EQUITY") or os.environ.get("PAPER_EQUITY") or "10000"
        try:
            return float(v)
        except Exception:
            return 10000.0

    # live：尽量读交易所余额
    if not settings.bybit_api_key:
        # 没有 key 也不直接报错：返回 0 -> 触发下方保护
        return 0.0

    c = TradeRestV5Client(base_url=settings.bybit_rest_base_url)
    r = c.wallet_balance(account_type=settings.bybit_account_type, coin="USDT")
    # result.list[0].totalEquity / totalWalletBalance 的字段在不同账号类型略有差异
    lst = (r.get("result") or {}).get("list") or []
    if not lst:
        return 0.0
    acc = lst[0]
    # 优先 totalEquity
    for k in ("totalEquity", "totalWalletBalance", "totalAvailableBalance"):
        if k in acc and acc[k] is not None:
            try:
                return float(acc[k])
            except Exception:
                pass
    return 0.0


def _paper_id(prefix: str, idem: str) -> str:
    return f"paper-{prefix}-{hashlib.sha256(idem.encode('utf-8')).hexdigest()[:12]}"


def execute_trade_plan(database_url: str, redis_url: str, *, trade_plan_event: Dict[str, Any]) -> None:
    """执行 trade_plan：ENTRY + SL + TP1/TP2（runner 由 lifecycle/paper_sim 接管）。"""
    payload = trade_plan_event.get("payload") or {}
    plan_ext = payload.get("ext", {}) or {}
    run_id = plan_ext.get("run_id")
    idem = payload.get("idempotency_key")

    if not idem:
        # 保护：没有幂等键，直接发 ERROR 报告
        rep = build_execution_report(
            idempotency_key="",
            symbol=str(payload.get("symbol") or ""),
            typ="ERROR",
            severity="IMPORTANT",
            detail={"error": "missing idempotency_key"},
            ext={"run_id": run_id} if run_id else None,
        )
        publish_execution_report(redis_url, rep)
        return

    lock = acquire_lock(redis_url, key=f"lock:plan:{idem}", ttl_ms=int(getattr(settings, "lock_ttl_ms", 60000)))
    if lock is None:
        return

    try:
        symbol = payload["symbol"]
        timeframe = payload["timeframe"]
        side = payload["side"]  # BUY/SELL
        entry = float(payload["entry_price"])
        sl = float(payload["primary_sl_price"])
        risk_pct = float(payload.get("risk_pct") or 0.005)
        hist_entry = payload.get("hist_entry")  # 可选：用于复盘

        # 风控：账户级熔断
        if settings.risk_circuit_enabled:
            try:
                import datetime
                trade_date = datetime.datetime.utcnow().date().isoformat()
                rs = get_or_init_risk_state(database_url, trade_date=trade_date, mode=settings.execution_mode)
                if rs.get("kill_switch") or rs.get("hard_halt") or rs.get("soft_halt"):
                    ev = build_risk_event(
                        typ="RISK_CIRCUIT_BLOCK",
                        severity="IMPORTANT",
                        symbol=symbol,
                        detail={"reason": "risk_state.halt", "risk_state": rs},
                        trace_id=trade_plan_event.get("trace_id"),
                    )
                    publish_risk_event(redis_url, ev)

                    rep = build_execution_report(
                        idempotency_key=idem,
                        symbol=symbol,
                        typ="REJECTED",
                        severity="IMPORTANT",
                        detail={"reason": "risk_circuit_halt", "risk_state": rs},
                        ext={"run_id": run_id} if run_id else None,
                        trace_id=trade_plan_event.get("trace_id"),
                    )
                    publish_execution_report(redis_url, rep)
                    return
            except Exception:
                # 风控检查失败不阻塞执行：记录风险事件即可
                ev = build_risk_event(
                    typ="RISK_STATE_READ_FAILED",
                    severity="INFO",
                    symbol=symbol,
                    detail={"warning": "risk_state_read_failed"},
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_risk_event(redis_url, ev)

        filters = _parse_instrument_filters(symbol)
        equity = _equity_usdt()

        qty_total = calc_qty(equity=equity, risk_pct=risk_pct, entry=entry, stop=sl, filters=filters)
        if qty_total <= 0:
            rep = build_execution_report(
                idempotency_key=idem,
                symbol=symbol,
                typ="ERROR",
                severity="IMPORTANT",
                detail={"error": "qty_total<=0", "equity": equity, "risk_pct": risk_pct, "entry": entry, "sl": sl},
                ext={"run_id": run_id} if run_id else None,
                trace_id=trade_plan_event.get("trace_id"),
            )
            publish_execution_report(redis_url, rep)
            return

        tp1_qty, tp2_qty, runner_qty = split_tp_qty(qty_total)
        tp1_price, tp2_price = tp_prices(side=side, entry=entry, stop=sl, tick_size=filters.tick_size)

        # 建立/更新 position（幂等：idempotency_key 唯一）
        # runner_stop 初始与 primary_sl 一致（后续由 lifecycle 更新）
        upsert_position(
            database_url,
            position_id=_paper_id("pos", idem),
            idempotency_key=idem,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            bias=str(payload.get("bias") or ""),
            qty_total=float(qty_total),
            qty_runner=float(runner_qty),
            entry_price=float(entry),
            primary_sl_price=float(sl),
            runner_stop_price=float(sl),
            status="OPEN",
            entry_close_time_ms=int(payload.get("close_time_ms") or 0),
            opened_at_ms=int(payload.get("close_time_ms") or 0),
            secondary_rule_checked=False,
            hist_entry=hist_entry,
            meta={
                "run_id": run_id,
                "tp1_filled": False,
                "tp2_filled": False,
                "mode": settings.execution_mode,
            },
        )

        mode = str(settings.execution_mode).upper()

        # -------- ENTRY --------
        if mode in ("PAPER", "BACKTEST"):
            entry_order_id = _paper_id("entry", idem)
            upsert_order(
                database_url,
                order_id=entry_order_id,
                idempotency_key=idem,
                symbol=symbol,
                purpose="ENTRY",
                side=side,
                order_type="Market",
                qty=float(qty_total),
                price=None,
                reduce_only=False,
                status="FILLED",
                bybit_order_id=entry_order_id,
                bybit_order_link_id=f"{idem}:ENTRY",
                payload={"mode": mode, "fill_price": entry, "ext": {"run_id": run_id} if run_id else {}},
            )
        else:
            # live：下市价单（最小可用）
            c = TradeRestV5Client(base_url=settings.bybit_rest_base_url)
            rr = c.place_order(
                category=settings.bybit_category,
                symbol=symbol,
                side=side,
                order_type="Market",
                qty=str(qty_total),
                reduce_only=False,
                position_idx=int(settings.bybit_position_idx),
                order_link_id=f"{idem}:ENTRY",
            )
            bybit_order_id = ((rr.get("result") or {}).get("orderId")) or None

            upsert_order(
                database_url,
                order_id=_paper_id("entry", idem),
                idempotency_key=idem,
                symbol=symbol,
                purpose="ENTRY",
                side=side,
                order_type="Market",
                qty=float(qty_total),
                price=None,
                reduce_only=False,
                status="SUBMITTED",
                bybit_order_id=bybit_order_id,
                bybit_order_link_id=f"{idem}:ENTRY",
                payload={"mode": mode, "bybit_resp": rr, "ext": {"run_id": run_id} if run_id else {}},
            )

            # 设置 SL（trading-stop）
            try:
                c.set_trading_stop(
                    category=settings.bybit_category,
                    symbol=symbol,
                    position_idx=int(settings.bybit_position_idx),
                    stop_loss=str(sl),
                    tpsl_mode="Full",
                )
            except Exception as e:
                ev = build_risk_event(
                    typ="SET_SL_FAILED",
                    severity="INFO",
                    symbol=symbol,
                    detail={"error": str(e), "sl": sl},
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_risk_event(redis_url, ev)

        # -------- TP1/TP2 --------
        # 纸面模式：挂单只落库；撮合由 paper_sim 在 bar_close 驱动
        def _upsert_tp(purpose: str, qty: float, price: float) -> None:
            if qty <= 0:
                return
            order_id = _paper_id(purpose.lower(), idem)
            upsert_order(
                database_url,
                order_id=order_id,
                idempotency_key=idem,
                symbol=symbol,
                purpose=purpose,
                side="SELL" if side == "BUY" else "BUY",
                order_type="Limit",
                qty=float(qty),
                price=float(price),
                reduce_only=True,
                status="SUBMITTED",
                bybit_order_id=(order_id if mode in ("PAPER", "BACKTEST") else None),
                bybit_order_link_id=f"{idem}:{purpose}",
                payload={"mode": mode, "tp_price": float(price), "tp_qty": float(qty), "ext": {"run_id": run_id} if run_id else {}},
            )

        _upsert_tp("TP1", tp1_qty, tp1_price)
        _upsert_tp("TP2", tp2_qty, tp2_price)

        # -------- 报告：ENTRY_FILLED（paper/backtest 立即成交；live 用 SUBMITTED 也可以） --------
        rep = build_execution_report(
            idempotency_key=idem,
            symbol=symbol,
            typ="ENTRY_FILLED" if mode in ("PAPER", "BACKTEST") else "ENTRY_SUBMITTED",
            severity="INFO",
            detail={
                "side": side,
                "qty": float(qty_total),
                "entry": float(entry),
                "sl": float(sl),
                "tp1": float(tp1_price),
                "tp2": float(tp2_price),
                "mode": mode,
            },
            ext={"run_id": run_id} if run_id else None,
            trace_id=trade_plan_event.get("trace_id"),
        )
        publish_execution_report(redis_url, rep)

    except Exception as e:
        logger.warning("execute_trade_plan_failed", extra={"extra_fields": {"event": "EXECUTE_TRADE_PLAN_FAILED", "error": str(e)}})
        rep = build_execution_report(
            idempotency_key=idem,
            symbol=str((trade_plan_event.get("payload") or {}).get("symbol") or ""),
            typ="ERROR",
            severity="IMPORTANT",
            detail={"error": str(e)},
            ext={"run_id": run_id} if run_id else None,
            trace_id=trade_plan_event.get("trace_id"),
        )
        publish_execution_report(redis_url, rep)
    finally:
        release_lock(redis_url, lock)


def close_position_market(
    database_url: str,
    redis_url: str,
    *,
    idempotency_key: str,
    symbol: str,
    side: str,
    close_price: Optional[float] = None,
    close_time_ms: Optional[int] = None,
    reason: str = "forced_exit",
) -> None:
    """按市价 reduce-only 平掉当前持仓（Phase 4）

paper/backtest：不调用交易所，只做落库 + execution_report（并让 paper_sim 的后续 bar_close 自然空转）。
live：这里提供最小可用实现（如果你后续要“强制平仓/熔断”可复用该通道）。
"""

    p = get_position_by_idem(database_url, idempotency_key=idempotency_key)
    run_id = (p.get("meta") or {}).get("run_id") if p else None

    if not p:
        rep = build_execution_report(
            idempotency_key=idempotency_key,
            symbol=symbol,
            typ="EXITED",
            severity="IMPORTANT",
            detail={"mode": settings.execution_mode, "reason": "no_position", "exit_reason": reason},
            ext={"run_id": run_id} if run_id else None,
        )
        publish_execution_report(redis_url, rep)
        return

    mode = str(settings.execution_mode).upper()
    if mode in ("PAPER", "BACKTEST"):
        # 直接平仓落库
        meta = (p.get("meta") or {}).copy()
        meta["status"] = "CLOSED"
        meta["close_price"] = float(close_price or 0.0)
        meta["close_time_ms"] = int(close_time_ms or 0)
        meta["close_reason"] = reason

        upsert_position(
            database_url,
            position_id=p["position_id"],
            idempotency_key=idempotency_key,
            symbol=symbol,
            timeframe=p["timeframe"],
            side=p["side"],
            bias=p.get("bias") or "",
            qty_total=float(p["qty_total"]),
            qty_runner=float(p["qty_runner"]),
            entry_price=float(p["entry_price"]),
            primary_sl_price=float(p["primary_sl_price"]),
            runner_stop_price=float(p.get("runner_stop_price") or p["primary_sl_price"]),
            status="CLOSED",
            entry_close_time_ms=int(p.get("entry_close_time_ms") or 0),
            opened_at_ms=int(p.get("opened_at_ms") or 0),
            secondary_rule_checked=bool(p.get("secondary_rule_checked")),
            hist_entry=p.get("hist_entry"),
            meta=meta,
        )

        rep = build_execution_report(
            idempotency_key=idempotency_key,
            symbol=symbol,
            typ="EXITED",
            severity="IMPORTANT",
            detail={"mode": mode, "reason": reason, "close_price": float(close_price or 0.0)},
            ext={"run_id": run_id} if run_id else None,
        )
        publish_execution_report(redis_url, rep)
        return

    # live：最小实现（不做复杂撤单/部分成交处理）
    try:
        c = TradeRestV5Client(base_url=settings.bybit_rest_base_url)
        rr = c.place_order(
            category=settings.bybit_category,
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            order_type="Market",
            qty=str(p["qty_total"]),
            reduce_only=True,
            position_idx=int(settings.bybit_position_idx),
            order_link_id=f"{idempotency_key}:FORCE_EXIT",
        )
        rep = build_execution_report(
            idempotency_key=idempotency_key,
            symbol=symbol,
            typ="EXIT_SUBMITTED",
            severity="IMPORTANT",
            detail={"mode": mode, "reason": reason, "bybit_resp": rr},
            ext={"run_id": run_id} if run_id else None,
        )
        publish_execution_report(redis_url, rep)
    except Exception as e:
        ev = build_risk_event(
            typ="FORCE_EXIT_FAILED",
            severity="IMPORTANT",
            symbol=symbol,
            detail={"error": str(e), "reason": reason},
        )
        publish_risk_event(redis_url, ev)
