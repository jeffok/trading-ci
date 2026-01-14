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
from libs.bybit.errors import BybitError, is_rate_limit_error, extract_retry_after_ms
from libs.common.config import settings
from libs.common.time import now_ms
from libs.common.timeframe import timeframe_ms
from libs.common.logging import setup_logging
from libs.execution.risk import InstrumentFilters, calc_qty, split_tp_qty, tp_prices
from libs.strategy.indicators import macd
from libs.mq.locks import acquire_lock, release_lock

from services.execution.publisher import build_execution_report, publish_execution_report, build_risk_event, publish_risk_event
from services.execution.kill_switch import is_kill_switch_on, should_emit_kill_switch_alert
import redis

from services.execution.metrics import compute_fill_ratio, compute_latency_ms, compute_slippage_bps
from services.execution.repo import (
    upsert_order,
    upsert_position,
    get_position_by_idem,
    get_or_init_risk_state,
    list_orders_by_idem,
    count_open_positions,
    find_open_position_same_direction,
    get_active_cooldown,
    get_conn,
)

logger = setup_logging("execution-executor")


def _timeframe_rank(tf: str) -> int:
    """Cycle priority (higher wins): 1d > 4h > 1h.

    Other monitor-only frames are treated as lowest priority.
    """
    t = (tf or "").strip().lower()
    if t == "1d":
        return 3
    if t == "4h":
        return 2
    if t == "1h":
        return 1
    return 0


def _cooldown_bars(tf: str) -> int:
    t = (tf or "").strip().lower()
    if t == "1h":
        return int(getattr(settings, "cooldown_bars_1h", 2))
    if t == "4h":
        return int(getattr(settings, "cooldown_bars_4h", 1))
    if t == "1d":
        return int(getattr(settings, "cooldown_bars_1d", 1))
    return 0


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
    r = c.wallet_balance_cached(account_type=settings.bybit_account_type, coin="USDT")
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


def _infer_hist_entry_from_bars(database_url: str, *, symbol: str, timeframe: str, entry_close_time_ms: int, limit: int = 500) -> Optional[float]:
    """Infer MACD histogram value at entry bar close.

    Used by Stage 6.1 secondary rule. Strategy may omit hist_entry; execution infers it from DB bars to
    avoid secondary rule becoming a no-op.

    Returns None when bars are insufficient or computation fails.
    """
    if entry_close_time_ms <= 0:
        return None
    sql = """
    SELECT close, close_time_ms
    FROM bars
    WHERE symbol=%(symbol)s AND timeframe=%(timeframe)s AND close_time_ms <= %(t)s
    ORDER BY close_time_ms DESC
    LIMIT %(limit)s
    """
    try:
        with get_conn(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"symbol": symbol, "timeframe": timeframe, "t": int(entry_close_time_ms), "limit": int(limit)})
                rows = cur.fetchall()
    except Exception:
        return None
    if not rows:
        return None
    # rows newest->oldest; reverse to chronological
    rows = list(reversed(rows))
    close = [float(r[0]) for r in rows]
    if len(close) < 60:
        return None
    try:
        _macd, _sig, hist = macd(close)
        # find last non-None
        for v in reversed(hist):
            if v is not None:
                return float(v)
    except Exception:
        return None
    return None



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
        # Stage 11: account kill switch gate (block NEW entries only)
        ks_on, ks_reason = is_kill_switch_on(database_url=database_url)
        if ks_on:
            # spam-safe alert window (use redis key)
            last_ms = None
            try:
                r = redis.Redis.from_url(redis_url)
                raw = r.get("kill_switch:last_emit_ms")
                last_ms = int(raw) if raw else None
            except Exception:
                last_ms = None
            if should_emit_kill_switch_alert(last_emit_ms=last_ms):
                evk = build_risk_event(
                    typ="KILL_SWITCH_ON",
                    severity="IMPORTANT",
                    symbol=(payload.get("symbol") if isinstance(payload, dict) else None),
                    detail={
                        "reason": ks_reason,
                        "idempotency_key": idem,
                        "scope": "account",
                        "source": "execution",
                    },
                )
                publish_risk_event(redis_url, evk)
                try:
                    r = redis.Redis.from_url(redis_url)
                    r.set("kill_switch:last_emit_ms", str(evk["ts_ms"]), ex=max(60, int(getattr(settings, "kill_switch_window_ms", 300000)) // 1000))
                except Exception:
                    pass

            rep = build_execution_report(
                typ="REJECTED",
                status="REJECTED",
                idempotency_key=idem,
                symbol=payload.get("symbol"),
                detail={"reason": "KILL_SWITCH_ON", "kill_switch_reason": ks_reason},
                trace_id=trade_plan_event.get("trace_id"),
                ext={"run_id": run_id} if run_id else None,
            )
            publish_execution_report(redis_url, rep)
            return

        symbol = payload["symbol"]
        timeframe = payload["timeframe"]
        side = payload["side"]  # BUY/SELL
        entry = float(payload["entry_price"])
        sl = float(payload["primary_sl_price"])
        risk_pct = float(payload.get("risk_pct") or 0.005)
        hist_entry = payload.get("hist_entry")  # 可选：用于复盘

        # Stage 8: trade_plan lifecycle expiry check (does not change strategy, only prevents executing stale plans)
        expires_at_ms = payload.get("expires_at_ms") or plan_ext.get("expires_at_ms")
        if expires_at_ms is not None:
            try:
                exp = int(expires_at_ms)
                now = now_ms()
                if exp > 0 and now > exp:
                    ev = build_risk_event(
                        typ="SIGNAL_EXPIRED",
                        severity="IMPORTANT",
                        symbol=str(symbol),
                        detail={
                            "plan_id": (plan_ext.get("plan_id") or payload.get("plan_id")),
                            "expires_at_ms": exp,
                            "now_ms": now,
                            "idempotency_key": idem,
                        },
                        trace_id=trade_plan_event.get("trace_id"),
                    )
                    publish_risk_event(redis_url, ev)
                    rep = build_execution_report(
                        idempotency_key=idem,
                        symbol=str(symbol),
                        typ="REJECTED",
                        severity="IMPORTANT",
                        detail={
                            "reason": "SIGNAL_EXPIRED",
                            "timeframe": timeframe,
                            "expires_at_ms": exp,
                            "now_ms": now,
                        },
                        ext={"run_id": run_id} if run_id else None,
                        trace_id=trade_plan_event.get("trace_id"),
                    )
                    publish_execution_report(redis_url, rep)
                    return
            except Exception:
                pass

        # Stage 6.1: Secondary rule hist_entry inference (do not change strategy; execution computes missing indicator)
        # If strategy didn't provide hist_entry, infer from DB bars at entry bar close.
        entry_close_ms = int(payload.get("close_time_ms") or 0)
        if getattr(settings, "secondary_rule_enabled", True) and hist_entry is None:
            inferred = _infer_hist_entry_from_bars(database_url, symbol=symbol, timeframe=timeframe, entry_close_time_ms=entry_close_ms)
            if inferred is not None:
                hist_entry = float(inferred)

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

        # ---------------- Stage 6：执行层“仓位/冷却/互斥”闸门 ----------------
        # 说明：不改变策略信号，只在执行侧做“是否允许开仓”的一致规则。
        gate_now_ms = int(payload.get("close_time_ms") or now_ms())

        # 1) 冷却：止损后，同币种同向在一段 bars 内不允许再次开仓
        if bool(getattr(settings, "cooldown_enabled", True)):
            cd = get_active_cooldown(database_url, symbol=symbol, side=side, timeframe=timeframe, now_ms=gate_now_ms)
            if cd is not None:
                ev = build_risk_event(
                    typ="COOLDOWN_BLOCKED",
                    severity="IMPORTANT",
                    symbol=symbol,
                    detail={
                        "reason": cd.get("reason"),
                        "until_ts_ms": int(cd.get("until_ts_ms") or 0),
                        "timeframe": timeframe,
                    },
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_risk_event(redis_url, ev)

                rep = build_execution_report(
                    idempotency_key=idem,
                    symbol=symbol,
                    typ="REJECTED",
                    severity="IMPORTANT",
                    detail={"reason": "cooldown_blocked", "cooldown": cd},
                    ext={"run_id": run_id} if run_id else None,
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_execution_report(redis_url, rep)
                return

        # 2) 最大同时持仓数：默认 3（可配置）
        max_pos = int(getattr(settings, "max_open_positions", getattr(settings, "max_open_positions_default", 3)))
        if max_pos > 0:
            cur_open = count_open_positions(database_url)
            if cur_open >= max_pos:
                ev = build_risk_event(
                    typ="MAX_POSITIONS_BLOCKED",
                    severity="IMPORTANT",
                    symbol=symbol,
                    detail={"max": max_pos, "current": cur_open},
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_risk_event(redis_url, ev)

                rep = build_execution_report(
                    idempotency_key=idem,
                    symbol=symbol,
                    typ="REJECTED",
                    severity="IMPORTANT",
                    detail={"reason": "max_positions_blocked", "max": max_pos, "current": cur_open},
                    ext={"run_id": run_id} if run_id else None,
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_execution_report(redis_url, rep)
                return

        # 3) 同币种同向互斥 + 周期优先级（1d>4h>1h）
        existed = find_open_position_same_direction(database_url, symbol=symbol, side=side)
        if existed is not None:
            in_rank = _timeframe_rank(timeframe)
            ex_rank = _timeframe_rank(str(existed.get("timeframe") or ""))

            if in_rank <= ex_rank:
                # incoming is not higher priority -> block
                ev = build_risk_event(
                    typ="POSITION_MUTEX_BLOCKED",
                    severity="IMPORTANT",
                    symbol=symbol,
                    detail={
                        "reason": "same_symbol_same_side_position_open",
                        "incoming_timeframe": timeframe,
                        "existing_timeframe": existed.get("timeframe"),
                        "existing_idempotency_key": existed.get("idempotency_key"),
                    },
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_risk_event(redis_url, ev)

                rep = build_execution_report(
                    idempotency_key=idem,
                    symbol=symbol,
                    typ="REJECTED",
                    severity="IMPORTANT",
                    detail={"reason": "position_mutex_blocked", "existing": existed},
                    ext={"run_id": run_id} if run_id else None,
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_execution_report(redis_url, rep)
                return

            # incoming higher priority: close the lower-priority position first (best effort)
            try:
                close_position_market(
                    database_url,
                    redis_url,
                    idempotency_key=str(existed.get("idempotency_key")),
                    symbol=symbol,
                    side=side,
                    close_price=float(entry),
                    close_time_ms=gate_now_ms,
                    reason="mutex_upgrade",
                )
            except Exception as e:
                ev = build_risk_event(
                    typ="POSITION_MUTEX_BLOCKED",
                    severity="IMPORTANT",
                    symbol=symbol,
                    detail={
                        "reason": "mutex_upgrade_close_failed",
                        "error": repr(e),
                        "incoming_timeframe": timeframe,
                        "existing": existed,
                    },
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_risk_event(redis_url, ev)
                # 关闭失败时，为避免双仓并存，直接阻断
                rep = build_execution_report(
                    idempotency_key=idem,
                    symbol=symbol,
                    typ="REJECTED",
                    severity="IMPORTANT",
                    detail={"reason": "mutex_upgrade_close_failed", "existing": existed, "error": repr(e)},
                    ext={"run_id": run_id} if run_id else None,
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_execution_report(redis_url, rep)
                return

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
            try:
                entry_order_type = "Limit" if str(getattr(settings, "execution_entry_order_type", "Market")).upper() == "LIMIT" else "Market"
                entry_link = f"{idem}:ENTRY:0" if entry_order_type == "Limit" else f"{idem}:ENTRY"
                rr = c.place_order(
                    category=settings.bybit_category,
                    symbol=symbol,
                    side=side,
                    order_type=entry_order_type,
                    qty=str(qty_total),
                    price=str(entry) if entry_order_type == "Limit" else None,
                    time_in_force="GTC" if entry_order_type == "Limit" else "IOC",
                    reduce_only=False,
                    position_idx=int(settings.bybit_position_idx),
                    order_link_id=entry_link,
                )
            except BybitError as e:
                # rate-limit / 10006: emit risk_event so notifier can alert; keep execution_report error path
                if is_rate_limit_error(e):
                    ra = extract_retry_after_ms(e)
                    ev = build_risk_event(
                        typ="RATE_LIMIT",
                        severity="IMPORTANT",
                        symbol=symbol,
                        retry_after_ms=int(ra) if ra is not None else None,
                        detail={
                            "ret_code": e.ret_code,
                            "ret_msg": e.ret_msg,
                            "endpoint": "/v5/order/create",
                            "hint": "Bybit 10006 限频；逐交易对监控请优先使用 public API（WS/market），私有接口集中调用并降频。",
                        },
                        trace_id=trade_plan_event.get("trace_id"),
                    )
                    publish_risk_event(redis_url, ev)
                raise
            bybit_order_id = ((rr.get("result") or {}).get("orderId")) or None

            upsert_order(
                database_url,
                order_id=_paper_id("entry", idem),
                idempotency_key=idem,
                symbol=symbol,
                purpose="ENTRY",
                side=side,
                order_type=entry_order_type,
                qty=float(qty_total),
                price=float(entry) if entry_order_type == "Limit" else None,
                reduce_only=False,
                status="SUBMITTED",
                bybit_order_id=bybit_order_id,
                bybit_order_link_id=entry_link,
                payload={
                    "mode": mode,
                    "bybit_resp": rr,
                    "submitted_at_ms": int(now_ms()),
                    "retry_count": 0,
                    "base_price": float(entry),
                    "ext": {"run_id": run_id} if run_id else {},
                },
                submitted_at_ms=int(now_ms()),
                retry_count=0,
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
            except BybitError as e:
                if is_rate_limit_error(e):
                    ra = extract_retry_after_ms(e)
                    ev = build_risk_event(
                        typ="RATE_LIMIT",
                        severity="IMPORTANT",
                        symbol=symbol,
                        retry_after_ms=int(ra) if ra is not None else None,
                        detail={
                            "ret_code": e.ret_code,
                            "ret_msg": e.ret_msg,
                            "endpoint": "/v5/position/trading-stop",
                        },
                        trace_id=trade_plan_event.get("trace_id"),
                    )
                    publish_risk_event(redis_url, ev)

                ev = build_risk_event(
                    typ="SET_SL_FAILED",
                    severity="IMPORTANT",
                    symbol=symbol,
                    detail={"error": str(e), "sl": sl},
                    trace_id=trade_plan_event.get("trace_id"),
                )
                publish_risk_event(redis_url, ev)
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
                # Stage 8 metrics (PAPER/BACKTEST: immediate fill)
                "latency_ms": 0 if mode in ("PAPER", "BACKTEST") else None,
                "slippage_bps": 0.0 if mode in ("PAPER", "BACKTEST") else None,
                "fill_ratio": 1.0 if mode in ("PAPER", "BACKTEST") else None,
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

    def _cancel_tp_orders_db(cancel_reason: str) -> None:
        """Best-effort: mark TP orders as CANCELED in DB.

        Notes:
        - paper/backtest doesn't talk to exchange, so DB status is the source of truth.
        - live mode also updates DB after successful cancel attempts.
        """
        try:
            orders = list_orders_by_idem(database_url, idempotency_key=idempotency_key)
        except Exception:
            return
        for o in orders:
            purpose = str(o.get("purpose") or "").upper()
            status = str(o.get("status") or "").upper()
            if purpose not in ("TP1", "TP2"):
                continue
            if status in ("FILLED", "CANCELED"):
                continue
            payload = dict(o.get("payload") or {})
            payload.setdefault("cancel", {})
            payload["cancel"].update({
                "reason": cancel_reason,
                "time_ms": int(close_time_ms or now_ms()),
            })
            upsert_order(
                database_url,
                order_id=str(o.get("order_id")),
                idempotency_key=idempotency_key,
                symbol=symbol,
                purpose=purpose,
                side=str(o.get("side") or ""),
                order_type=str(o.get("order_type") or "Market"),
                qty=float(o.get("qty") or 0.0),
                price=o.get("price"),
                reduce_only=bool(o.get("reduce_only")),
                status="CANCELED",
                bybit_order_id=o.get("bybit_order_id"),
                bybit_order_link_id=o.get("bybit_order_link_id"),
                payload=payload,
            )

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
        # fallback to last_price captured by paper_sim if no close_price provided
        _cp = close_price
        if _cp is None:
            try:
                _cp = float((meta.get("last_price") or 0.0))
            except Exception:
                _cp = 0.0
        meta["close_price"] = float(_cp or 0.0)
        meta["close_time_ms"] = int(close_time_ms or 0)
        meta["close_reason"] = reason

        # Secondary rule / 强制退出 / 互斥升级：撤销未成交 TP 单（DB 侧幂等）。
        _cancel_tp_orders_db(cancel_reason=f"position_close:{reason}")

        # 计算并记录 pnl_usdt + 连亏次数（仅用于通知/观测，不改变策略）
        try:
            entry = float(p.get("entry_price") or 0.0)
            qty = float(p.get("qty_total") or 0.0)
            side0 = str(p.get("side") or "")
            exit_px = float(meta["close_price"] or 0.0)
            pnl_usdt = (exit_px - entry) * qty if side0 == "BUY" else (entry - exit_px) * qty

            import datetime
            from services.execution.risk_state_ext import update_consecutive_loss_count

            trade_date = datetime.datetime.utcnow().date().isoformat()
            loss_count = update_consecutive_loss_count(
                database_url,
                trade_date=trade_date,
                mode=str(settings.execution_mode),
                pnl_usdt=float(pnl_usdt),
            )
        except Exception:
            pnl_usdt = None
            loss_count = None

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
            detail={
                "mode": mode,
                "reason": reason,
                "close_price": float(meta.get("close_price") or 0.0),
                "entry_price": float(p.get("entry_price") or 0.0),
                "side": p.get("side"),
                "filled_qty": float(p.get("qty_total") or 0.0),
                "avg_price": float(meta.get("close_price") or 0.0),
                "pnl_usdt": float(pnl_usdt) if pnl_usdt is not None else None,
                "timeframe": p.get("timeframe"),
            },
            ext={
                **({"run_id": run_id} if run_id else {}),
                "pnl_usdt": float(pnl_usdt) if pnl_usdt is not None else None,
                "entry_avg_price": float(p.get("entry_price") or 0.0),
                "exit_avg_price": float(meta.get("close_price") or 0.0),
                "consecutive_loss_count": int(loss_count) if loss_count is not None else None,
            },
        )
        publish_execution_report(redis_url, rep)
        return

    # live：最小实现（不做复杂撤单/部分成交处理）
    try:
        c = TradeRestV5Client(base_url=settings.bybit_rest_base_url)

        # Stage 6：在强制平仓前，best-effort 撤销 reduce-only TP1/TP2（避免残留挂单）。
        try:
            orders = list_orders_by_idem(database_url, idempotency_key=idempotency_key)
        except Exception:
            orders = []
        for o in orders:
            purpose = str(o.get("purpose") or "").upper()
            status = str(o.get("status") or "").upper()
            if purpose not in ("TP1", "TP2") or status in ("FILLED", "CANCELED"):
                continue
            try:
                c.cancel_order(
                    category=settings.bybit_category,
                    symbol=symbol,
                    order_id=o.get("bybit_order_id"),
                    order_link_id=o.get("bybit_order_link_id"),
                )
            except BybitError as e:
                if is_rate_limit_error(e):
                    ra = extract_retry_after_ms(e)
                    ev = build_risk_event(
                        typ="RATE_LIMIT",
                        severity="IMPORTANT",
                        symbol=symbol,
                        retry_after_ms=int(ra) if ra is not None else None,
                        detail={
                            "ret_code": e.ret_code,
                            "ret_msg": e.ret_msg,
                            "endpoint": "/v5/order/cancel",
                            "context": "cancel_tp_before_exit",
                        },
                    )
                    publish_risk_event(redis_url, ev)
            # regardless of cancel success, mark as canceled in DB (idempotent)
            try:
                _cancel_tp_orders_db(cancel_reason=f"position_close:{reason}")
            except Exception:
                pass

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
    except BybitError as e:
        if is_rate_limit_error(e):
            ra = extract_retry_after_ms(e)
            ev = build_risk_event(
                typ="RATE_LIMIT",
                severity="IMPORTANT",
                symbol=symbol,
                retry_after_ms=int(ra) if ra is not None else None,
                detail={
                    "ret_code": e.ret_code,
                    "ret_msg": e.ret_msg,
                    "endpoint": "/v5/order/create",
                    "context": "force_exit",
                },
            )
            publish_risk_event(redis_url, ev)
        ev = build_risk_event(
            typ="FORCE_EXIT_FAILED",
            severity="IMPORTANT",
            symbol=symbol,
            detail={"error": str(e), "reason": reason},
        )
        publish_risk_event(redis_url, ev)
    except Exception as e:
        ev = build_risk_event(
            typ="FORCE_EXIT_FAILED",
            severity="IMPORTANT",
            symbol=symbol,
            detail={"error": str(e), "reason": reason},
        )
        publish_risk_event(redis_url, ev)
