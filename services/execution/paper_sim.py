# -*- coding: utf-8 -*-
"""paper/backtest 成交模拟（Stage 6）

目标：在 *不改变策略规则* 的前提下，把“回测/模拟盘的执行闭环”做全：
- ENTRY：Phase 3 已支持 paper 直接认为入场成交
- TP1/TP2：Phase 3 已挂 reduce-only 订单（落库），但 paper/backtest 没有交易所撮合 -> 需要按 OHLC 模拟成交
- SL/Runner SL：live 由交易所触发；paper/backtest 需要按 OHLC 模拟触发并平仓

输入：stream:bar_close（包含 ohlcv）
输出：
- 更新 orders / positions
- 写 execution_traces
- 发布 execution_report
- 写 backtest_trades（run_id 来自 bar_close_event.payload.ext.run_id 或 position.meta.run_id）

关键原则：
- 不“优化”策略：只做执行层的撮合模拟与记录
- 可复现：同一份 bars + 同一套规则 -> 输出一致
- 决策顺序确定：使用一条确定性的“bar 内路径”假设来决定 TP/SL 先后
  - 若 close>=open：假设 open -> high -> low -> close
  - 若 close<open ：假设 open -> low  -> high -> close
  这是行业常用的最小假设，用来避免同根 K 内既触发 TP 又触发 SL 时的歧义。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import hashlib

from libs.common.config import settings
from libs.common.id import new_event_id
from libs.common.time import now_ms
from libs.common.timeframe import timeframe_ms
from services.execution.publisher import build_execution_report, publish_execution_report
from services.execution.trace import trace_step
from services.execution.repo import (
    list_open_positions,
    list_orders_by_idem,
    upsert_order,
    upsert_position,
    upsert_cooldown,
)
from libs.backtest.repo import insert_backtest_trade
from services.execution.risk_state_ext import update_consecutive_loss_count


def _bar_path(o: float, h: float, l: float, c: float) -> List[float]:
    """确定性的 bar 内价格路径（见模块注释）。"""
    if c >= o:
        return [o, h, l, c]
    return [o, l, h, c]


def _segment_levels_in_order(a: float, b: float, levels: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
    """给定线段 a->b，把落在区间内的 level 按移动方向排序返回。"""
    lo, hi = (a, b) if a <= b else (b, a)
    hits = [(name, px) for (name, px) in levels if lo <= px <= hi]
    if not hits:
        return []
    # 上涨：按价格从低到高触发；下跌：从高到低触发
    if b >= a:
        hits.sort(key=lambda x: x[1])
    else:
        hits.sort(key=lambda x: -x[1])
    return hits


def _pnl_r(side: str, entry: float, stop: float, exit_price: float) -> float:
    """按 R 倍数计算收益（用于 backtest_trades.pnl_r）。

    LONG: 1R = entry - stop（>0），pnl_r = (exit-entry)/(entry-stop)
    SHORT: 1R = stop - entry（>0），pnl_r = (entry-exit)/(stop-entry)
    """
    if side == "BUY":
        r = max(entry - stop, 1e-12)
        return (exit_price - entry) / r
    r = max(stop - entry, 1e-12)
    return (entry - exit_price) / r


def _realized_pnl_usdt(side: str, entry: float, legs: List[Dict[str, Any]]) -> float:
    """Compute realized PnL in USDT for linear contracts.

    legs are exit fills: TP1/TP2/SL with qty + price.
    LONG (BUY): (exit-entry)*qty
    SHORT (SELL): (entry-exit)*qty
    """
    pnl = 0.0
    for leg in legs:
        if leg.get("type") not in ("TP1", "TP2", "SL"):
            continue
        try:
            q = float(leg.get("qty") or 0.0)
            px = float(leg.get("price") or 0.0)
        except Exception:
            continue
        if side == "BUY":
            pnl += (px - entry) * q
        else:
            pnl += (entry - px) * q
    return float(pnl)


def _weighted_avg_exit(legs: List[Dict[str, Any]]) -> float | None:
    num = 0.0
    den = 0.0
    for leg in legs:
        if leg.get("type") not in ("TP1", "TP2", "SL"):
            continue
        try:
            q = float(leg.get("qty") or 0.0)
            px = float(leg.get("price") or 0.0)
        except Exception:
            continue
        if q <= 0:
            continue
        num += q * px
        den += q
    if den <= 0:
        return None
    return float(num / den)


def process_paper_bar_close(*, database_url: str, redis_url: str, bar_close_event: Dict[str, Any]) -> None:
    """在 paper/backtest 模式下，基于 bar_close 的 OHLC 模拟撮合。"""
    if settings.execution_mode == "live":
        return

    payload = bar_close_event.get("payload") or {}
    symbol = payload.get("symbol")
    timeframe = payload.get("timeframe")
    close_time_ms = int(payload.get("close_time_ms") or 0)
    ext = payload.get("ext") or {}
    run_id = ext.get("run_id")

    # schema uses object: {open,high,low,close,volume}; keep backward-compat with legacy list [o,h,l,c,...]
    ohlcv = payload.get("ohlcv")
    if isinstance(ohlcv, dict):
        if not all(k in ohlcv for k in ("open", "high", "low", "close")):
            return
        o, h, l, c = float(ohlcv["open"]), float(ohlcv["high"]), float(ohlcv["low"]), float(ohlcv["close"])
    else:
        ohl = ohlcv or []
        if len(ohl) < 4:
            return
        o, h, l, c = float(ohl[0]), float(ohl[1]), float(ohl[2]), float(ohl[3])

    positions = list_open_positions(database_url)
    for p in positions:
        if p.get("symbol") != symbol or p.get("timeframe") != timeframe:
            continue

        meta = dict(p.get("meta") or {})
        # 记录最近价格，便于其它 paper close 走默认价
        meta["last_price"] = c
        meta["last_close_time_ms"] = close_time_ms
        if run_id and not meta.get("run_id"):
            meta["run_id"] = run_id

        idem = p["idempotency_key"]
        entry = float(p["entry_price"])
        primary_sl = float(p["primary_sl_price"])
        runner_stop = float(p["runner_stop_price"]) if p.get("runner_stop_price") is not None else None

        # 当前剩余可平仓数量（qty_open 由 ENTRY 初始化）
        qty_open = float(meta.get("qty_open", p.get("qty_total") or 0.0) or 0.0)
        if qty_open <= 0:
            # 异常：持仓表仍是 OPEN，但没有剩余数量 -> 直接标记 CLOSED
            meta["qty_open"] = 0.0
            meta["status"] = "CLOSED"
            upsert_position(
                database_url,
                position_id=p["position_id"],
                idempotency_key=idem,
                symbol=symbol,
                timeframe=timeframe,
                side=p["side"],
                bias=p["bias"],
                qty_total=float(p["qty_total"]),
                qty_runner=float(p["qty_runner"]),
                entry_price=entry,
                primary_sl_price=primary_sl,
                runner_stop_price=p.get("runner_stop_price"),
                status="CLOSED",
                entry_close_time_ms=int(p["entry_close_time_ms"]),
                opened_at_ms=int(p["opened_at_ms"]),
                secondary_rule_checked=bool(p.get("secondary_rule_checked")),
                hist_entry=p.get("hist_entry"),
                meta=meta,
            )
            continue

        orders = list_orders_by_idem(database_url, idempotency_key=idem)
        tp1 = next((x for x in orders if x.get("purpose") == "TP1"), None)
        tp2 = next((x for x in orders if x.get("purpose") == "TP2"), None)

        tp1_filled = bool(meta.get("tp1_filled"))
        tp2_filled = bool(meta.get("tp2_filled"))

        # 止损“有效价”：TP1 后保本，TP2 后启用 runner_stop（若可用）
        if tp2_filled and runner_stop is not None:
            eff_sl = runner_stop
        elif tp1_filled:
            eff_sl = entry
        else:
            eff_sl = primary_sl

        # 本 bar 可能发生的事件 legs
        legs: List[Dict[str, Any]] = list(meta.get("legs") or [])

        # 构造 bar 内路径并逐段处理
        path = _bar_path(o, h, l, c)

        def fill_tp(purpose: str, tp_order: Dict[str, Any], px: float) -> None:
            nonlocal qty_open, tp1_filled, tp2_filled, eff_sl, legs
            if qty_open <= 0:
                return
            tp_qty = float((tp_order.get("payload") or {}).get("tp_qty") or 0.0)
            tp_qty = min(tp_qty, qty_open)
            if tp_qty <= 0:
                return
            # 更新订单状态
            upsert_order(
                database_url,
                order_id=tp_order["order_id"],
                idempotency_key=idem,
                symbol=symbol,
                purpose=purpose,
                side=tp_order["side"],
                order_type=tp_order["order_type"],
                qty=float(tp_order["qty"]),
                price=float(tp_order["price"]) if tp_order.get("price") is not None else None,
                reduce_only=bool(tp_order["reduce_only"]),
                status="FILLED",
                bybit_order_id=tp_order.get("bybit_order_id") or f"PAPER_{purpose}",
                bybit_order_link_id=tp_order.get("bybit_order_link_id"),
                payload={**(tp_order.get("payload") or {}), "fill_price": px, "fill_time_ms": close_time_ms, "mode": settings.execution_mode, "run_id": meta.get("run_id")},
            )
            qty_open -= tp_qty
            legs.append({"type": purpose, "qty": tp_qty, "price": px, "time_ms": close_time_ms})
            trace_step(database_url, trace_id=str(meta.get("trace_id") or ""), idempotency_key=idem, stage=f"{purpose}_FILLED",
                       detail={"qty": tp_qty, "price": px, "run_id": meta.get("run_id")}, ext={"run_id": meta.get("run_id")})

            rep = build_execution_report(
                idempotency_key=idem,
                symbol=symbol,
                typ=f"{purpose}_FILLED",
                severity="IMPORTANT",
                detail={
                    "mode": settings.execution_mode,
                    "qty": tp_qty,
                    "price": px,
                    "entry_price": entry,
                    "side": p["side"],
                    "timeframe": timeframe,
                    "run_id": meta.get("run_id"),
                },
            )
            publish_execution_report(redis_url, rep)

            if purpose == "TP1":
                tp1_filled = True
                meta["tp1_filled"] = True
                # TP1 后 SL 上移到 entry（保本）
                eff_sl = entry
            if purpose == "TP2":
                tp2_filled = True
                meta["tp2_filled"] = True
                # TP2 后启用 runner_stop（若可用）
                if runner_stop is not None:
                    eff_sl = runner_stop

        def fill_sl(px: float, reason: str) -> None:
            nonlocal qty_open, legs
            if qty_open <= 0:
                return
            legs.append({"type": "SL", "qty": qty_open, "price": px, "time_ms": close_time_ms, "reason": reason})
            trace_step(database_url, trace_id=str(meta.get("trace_id") or ""), idempotency_key=idem, stage="SL_TRIGGERED",
                       detail={"qty": qty_open, "price": px, "reason": reason, "run_id": meta.get("run_id")})
            # 标记出场原因（用于 Telegram 文本）
            # - 未触发 TP1：primary SL
            # - 触发 TP1 且 eff_sl==entry：break-even/secondary exit
            # - 触发 TP2：runner stop（secondary exit）
            if tp2_filled:
                meta["exit_reason"] = "SECONDARY_SL_EXIT"
            elif tp1_filled and abs(float(eff_sl) - float(entry)) < 1e-9:
                meta["exit_reason"] = "SECONDARY_SL_EXIT"
            else:
                meta["exit_reason"] = "PRIMARY_SL_HIT"

            # Stage 6：Primary SL 触发后写入冷却（按 timeframe 的 bar 数）。
            # 只在 PRIMARY_SL_HIT 时进入冷却；secondary_rule/runner 退出不进入冷却。
            try:
                if bool(getattr(settings, "cooldown_enabled", True)) and str(meta.get("exit_reason")) == "PRIMARY_SL_HIT":
                    tf = str(timeframe)
                    bars = 0
                    if tf == "1h":
                        bars = int(getattr(settings, "cooldown_bars_1h", 2))
                    elif tf == "4h":
                        bars = int(getattr(settings, "cooldown_bars_4h", 1))
                    elif tf == "1d":
                        bars = int(getattr(settings, "cooldown_bars_1d", 1))
                    if bars > 0:
                        until_ts_ms = int(close_time_ms) + int(bars) * int(timeframe_ms(tf))
                        upsert_cooldown(
                            database_url,
                            symbol=symbol,
                            side=str(p.get("side") or ""),
                            timeframe=tf,
                            reason="PRIMARY_SL_HIT",
                            until_ts_ms=until_ts_ms,
                            meta={"idempotency_key": idem, "close_time_ms": int(close_time_ms)},
                        )
            except Exception:
                # 冷却写入失败不阻塞回测/模拟撮合
                pass
            qty_open = 0.0

        # 模拟：逐段扫描
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]

            # 需要判断的 level：SL + 未成交 TP
            cand: List[Tuple[str, float]] = [("SL", float(eff_sl))]
            if tp1 and (not tp1_filled) and tp1.get("price") is not None:
                cand.append(("TP1", float(tp1["price"])))
            if tp2 and (not tp2_filled) and tp2.get("price") is not None:
                cand.append(("TP2", float(tp2["price"])))

            ordered = _segment_levels_in_order(a, b, cand)
            if not ordered:
                continue

            # 依次触发
            for name, px in ordered:
                if qty_open <= 0:
                    break
                if name == "SL":
                    fill_sl(px, reason="bar_path")
                    break  # 止损触发后本仓位结束
                if name == "TP1" and tp1 and (not tp1_filled):
                    fill_tp("TP1", tp1, px)
                if name == "TP2" and tp2 and (not tp2_filled):
                    fill_tp("TP2", tp2, px)

        # 落回 meta
        meta["qty_open"] = float(max(qty_open, 0.0))
        meta["legs"] = legs

        # 若已经全部退出 -> 关闭持仓，并写 backtest_trades
        if qty_open <= 0:
            meta["status"] = "CLOSED"
            meta["close_price"] = legs[-1]["price"] if legs else c
            meta["close_time_ms"] = close_time_ms

            # 默认出场原因：TP_HIT / PRIMARY_SL_HIT / SIM
            if not meta.get("exit_reason"):
                meta["exit_reason"] = "TP_HIT" if any(x.get("type") in ("TP1", "TP2") for x in legs) else "SIM"

            # 计算 pnl_r（按“最终退出价”）
            stop_for_r = primary_sl
            exit_price = float(meta["close_price"])
            pnl_r = _pnl_r(p["side"], entry, stop_for_r, exit_price)

            # 写 backtest_trades（trade_id 采用 run_id+idem 哈希，保证幂等）
            rid = str(meta.get("run_id") or run_id or "")
            trade_id = hashlib.sha256(f"{rid}|{idem}".encode("utf-8")).hexdigest() if rid else hashlib.sha256(idem.encode("utf-8")).hexdigest()

            insert_backtest_trade(
                database_url,
                trade_id=trade_id,
                run_id=rid or "replay-unknown",
                symbol=symbol,
                timeframe=timeframe,
                entry_time_ms=int(p["entry_close_time_ms"]),
                exit_time_ms=close_time_ms,
                side="LONG" if p["side"] == "BUY" else "SHORT",
                entry_price=entry,
                exit_price=exit_price,
                pnl_r=float(pnl_r),
                reason=str(meta.get("exit_reason") or "SIM"),
                legs=legs,
                idempotency_key=idem,
            )

            # 计算 USDT 计价的已实现收益（线性合约近似：qty * (exit-entry)；空头反向）
            closed_qty = float(sum(float(x.get("qty") or 0.0) for x in legs))
            # legs 里的 qty 可能只记录了平仓 legs（TP/SL），这里用 closed_qty 作为“总平仓量”
            if closed_qty <= 0:
                closed_qty = float(p.get("qty_total") or 0.0)

            pnl_usdt = 0.0
            wsum = 0.0
            wqty = 0.0
            for x in legs:
                if x.get("type") not in ("TP1", "TP2", "SL"):
                    continue
                q = float(x.get("qty") or 0.0)
                px = float(x.get("price") or 0.0)
                wsum += q * px
                wqty += q
                if p["side"] == "BUY":
                    pnl_usdt += (px - entry) * q
                else:
                    pnl_usdt += (entry - px) * q
            exit_avg = float(wsum / wqty) if wqty > 0 else float(exit_price)

            # 更新“连续亏损次数”（不改变策略，只用于通知/风控观测）
            try:
                import datetime

                trade_date = datetime.datetime.utcnow().date().isoformat()
                loss_count = update_consecutive_loss_count(
                    database_url,
                    trade_date=trade_date,
                    mode=str(settings.execution_mode),
                    pnl_usdt=float(pnl_usdt),
                )
            except Exception:
                loss_count = None

            rep = build_execution_report(
                idempotency_key=idem,
                symbol=symbol,
                typ="POSITION_CLOSED",
                severity="IMPORTANT",
                detail={
                    "mode": settings.execution_mode,
                    "side": p["side"],
                    "timeframe": timeframe,
                    "filled_qty": float(closed_qty),
                    "avg_price": float(exit_avg),
                    "entry_price": float(entry),
                    "close_price": float(exit_avg),
                    "pnl_usdt": float(pnl_usdt),
                    "pnl_r": float(pnl_r),
                    "reason": str(meta.get("exit_reason") or "SIM"),
                    "run_id": meta.get("run_id"),
                },
                ext={
                    "pnl_usdt": float(pnl_usdt),
                    "entry_avg_price": float(entry),
                    "exit_avg_price": float(exit_avg),
                    "consecutive_loss_count": int(loss_count) if loss_count is not None else None,
                    "run_id": meta.get("run_id"),
                },
            )
            publish_execution_report(redis_url, rep)

            upsert_position(
                database_url,
                position_id=p["position_id"],
                idempotency_key=idem,
                symbol=symbol,
                timeframe=timeframe,
                side=p["side"],
                bias=p["bias"],
                qty_total=float(p["qty_total"]),
                qty_runner=float(p["qty_runner"]),
                entry_price=entry,
                primary_sl_price=primary_sl,
                runner_stop_price=p.get("runner_stop_price"),
                status="CLOSED",
                entry_close_time_ms=int(p["entry_close_time_ms"]),
                opened_at_ms=int(p["opened_at_ms"]),
                secondary_rule_checked=bool(p.get("secondary_rule_checked")),
                hist_entry=p.get("hist_entry"),
                meta=meta,
            )
        else:
            # 仍 OPEN -> 更新 meta（含 last_price 等）
            upsert_position(
                database_url,
                position_id=p["position_id"],
                idempotency_key=idem,
                symbol=symbol,
                timeframe=timeframe,
                side=p["side"],
                bias=p["bias"],
                qty_total=float(p["qty_total"]),
                qty_runner=float(p["qty_runner"]),
                entry_price=entry,
                primary_sl_price=primary_sl,
                runner_stop_price=p.get("runner_stop_price"),
                status="OPEN",
                entry_close_time_ms=int(p["entry_close_time_ms"]),
                opened_at_ms=int(p["opened_at_ms"]),
                secondary_rule_checked=bool(p.get("secondary_rule_checked")),
                hist_entry=p.get("hist_entry"),
                meta=meta,
            )
