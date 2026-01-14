# -*- coding: utf-8 -*-
"""持仓生命周期管理（Phase 4）

本模块实现两件“策略已定义但需要工程落地”的规则：
1) Runner（剩余 20%）跟随止损：ATR 或 Pivot
2) 次日未继续缩短立即退出（secondary_sl_rule）

输入：`stream:bar_close`
依赖：
- bars 表（marketdata 已写入）
- positions 表（execution 已建立）
- libs.strategy.indicators.macd 计算 histogram

实现策略：
- 对所有 OPEN positions：
  - 如果 bar_close 的 symbol/timeframe 匹配该 position 的 timeframe：
    - 更新 Runner 止损（只对 runner_stop_price 进行更严格的保护，不会放松）
    - 检查 secondary rule（只检查一次：entry 后的第一根同周期 bar）
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List

from libs.common.config import settings
from libs.strategy.indicators import macd
from libs.strategy.pivots import pivot_lows, pivot_highs
from libs.execution.atr import atr_sma

from services.execution.repo import list_open_positions, save_position
from services.execution.publisher import (
    build_execution_report,
    publish_execution_report,
    build_risk_event,
    publish_risk_event,
)
from libs.db.pg import get_conn
from services.execution.executor import close_position_market


def _hist_last(close: List[float]) -> Optional[float]:
    _, _, hist = macd(close)
    return None if hist[-1] is None else float(hist[-1])





def _db_get_bars(database_url: str, *, symbol: str, timeframe: str, limit: int = 500) -> List[Dict[str, Any]]:
    """从 bars 表读取最近 N 根K线（按时间升序返回）。"""
    sql = """
    SELECT open, high, low, close, volume, turnover, open_time_ms, close_time_ms
    FROM bars
    WHERE symbol=%(symbol)s AND timeframe=%(timeframe)s
    ORDER BY close_time_ms DESC
    LIMIT %(limit)s
    """

    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"symbol": symbol, "timeframe": timeframe, "limit": limit})
            rows = cur.fetchall()

    # rows is newest->oldest, reverse to chronological order
    rows = list(reversed(rows))
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "open": float(r[0]),
            "high": float(r[1]),
            "low": float(r[2]),
            "close": float(r[3]),
            "volume": float(r[4]) if r[4] is not None else 0.0,
            "turnover": float(r[5]) if r[5] is not None else 0.0,
            "open_time_ms": int(r[6]),
            "close_time_ms": int(r[7]),
        })
    return out


def on_bar_close(database_url: str, redis_url: str, *, bar_close_event: Dict[str, Any]) -> None:
    """execution worker 的生命周期入口（bar_close）。

    目标：保持 worker 调用简单（只传 event），内部完成 bars 拉取与异常告警。
    """
    try:
        update_runner_stop_and_secondary_rule(
            database_url=database_url,
            redis_url=redis_url,
            bar_close_event=bar_close_event,
            bars_provider=lambda symbol, timeframe, limit=500: _db_get_bars(database_url, symbol=symbol, timeframe=timeframe, limit=limit),
        )
    except Exception as e:
        # 不让生命周期异常阻塞消费；通过 risk_event 告警即可
        payload = bar_close_event.get("payload", {}) if isinstance(bar_close_event, dict) else {}
        symbol = payload.get("symbol")
        detail = {
            "error": repr(e),
            "stage": "on_bar_close",
            "timeframe": payload.get("timeframe"),
            "close_time_ms": payload.get("close_time_ms"),
        }
        ev = build_risk_event(typ="LIFECYCLE_ERROR", severity="CRITICAL", symbol=symbol, detail=detail)
        publish_risk_event(redis_url, ev)

def update_runner_stop_and_secondary_rule(
    *,
    database_url: str,
    redis_url: str,
    bar_close_event: Dict[str, Any],
    bars_provider,  # callable(symbol, timeframe, limit)->bars
) -> None:
    payload = bar_close_event["payload"]
    symbol = payload["symbol"]
    timeframe = payload["timeframe"]
    close_time_ms = int(payload["close_time_ms"])

    positions = list_open_positions(database_url)
    for p in positions:
        if p["symbol"] != symbol or p["timeframe"] != timeframe:
            continue

        # 拉取最新 bars
        bars = bars_provider(symbol=symbol, timeframe=timeframe, limit=500)
        if len(bars) < 120:
            continue

        close = [b["close"] for b in bars]
        high = [b["high"] for b in bars]
        low = [b["low"] for b in bars]

        # ---------------- Secondary rule: 只检查 entry 后第一根 bar ----------------
        if getattr(settings, "secondary_rule_enabled", True) and (not p["secondary_rule_checked"]) and close_time_ms > int(p["entry_close_time_ms"]):
            hist_entry = p["hist_entry"]
            hist_now = _hist_last(close)
            ok = True
            if hist_entry is not None and hist_now is not None:
                # LONG：hist 应继续抬高（更接近 0）；SHORT：hist 应继续走低
                if p["bias"] == "LONG":
                    ok = hist_now > float(hist_entry)
                else:
                    ok = hist_now < float(hist_entry)

            # 无法计算时：保守起见，不触发强制退出，只标记已检查
            if not ok:
                rep = build_execution_report(
                    idempotency_key=p["idempotency_key"],
                    symbol=symbol,
                    typ="EXIT_RULE_TRIGGERED",
                    severity="IMPORTANT",
                    detail={
                        "rule": "NEXT_BAR_NOT_SHORTEN_EXIT",
                        "hist_entry": hist_entry,
                        "hist_now": hist_now,
                        "timeframe": timeframe,
                        "close_time_ms": close_time_ms,
                    },
                )
                publish_execution_report(redis_url, rep)
                # Phase 4：直接执行强制退出（reduce-only 市价平仓）
                close_position_market(database_url, redis_url, idempotency_key=p["idempotency_key"], symbol=symbol, side=p["side"], close_price=float(close[-1]), close_time_ms=close_time_ms, reason="secondary_rule")
            # 标记已检查
            save_position(
                database_url,
                position_id=p["position_id"],
                idempotency_key=p["idempotency_key"],
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
                secondary_rule_checked=True,
                hist_entry=p["hist_entry"],
                meta=p["meta"],
            )

        # ---------------- Runner trailing stop ----------------
        # 只更新 runner_stop_price（更严格，不放松）
        if p["qty_runner"] <= 0:
            continue

        new_stop = None
        if settings.runner_trail_mode.upper() == "ATR":
            atr = atr_sma(high, low, close, period=settings.runner_atr_period)
            if atr[-1] is None:
                continue
            atr_val = float(atr[-1]) * float(settings.runner_atr_mult)
            if p["bias"] == "LONG":
                new_stop = close[-1] - atr_val
                if p["runner_stop_price"] is not None:
                    new_stop = max(float(p["runner_stop_price"]), new_stop)
            else:
                new_stop = close[-1] + atr_val
                if p["runner_stop_price"] is not None:
                    new_stop = min(float(p["runner_stop_price"]), new_stop)
        else:
            # PIVOT：用最近的 pivot low/high 作为 stop
            if p["bias"] == "LONG":
                piv = pivot_lows(low)
                if not piv:
                    continue
                new_stop = float(piv[-1].price)
                if p["runner_stop_price"] is not None:
                    new_stop = max(float(p["runner_stop_price"]), new_stop)
            else:
                piv = pivot_highs(high)
                if not piv:
                    continue
                new_stop = float(piv[-1].price)
                if p["runner_stop_price"] is not None:
                    new_stop = min(float(p["runner_stop_price"]), new_stop)

        # 如果 new_stop 有变化就落库 & 发报告
        if new_stop is not None and (p["runner_stop_price"] is None or abs(new_stop - float(p["runner_stop_price"])) > 1e-9):
            save_position(
                database_url,
                position_id=p["position_id"],
                idempotency_key=p["idempotency_key"],
                symbol=p["symbol"],
                timeframe=p["timeframe"],
                side=p["side"],
                bias=p["bias"],
                qty_total=p["qty_total"],
                qty_runner=p["qty_runner"],
                entry_price=p["entry_price"],
                primary_sl_price=p["primary_sl_price"],
                runner_stop_price=float(new_stop),
                status=p["status"],
                entry_close_time_ms=p["entry_close_time_ms"],
                opened_at_ms=p["opened_at_ms"],
                secondary_rule_checked=p["secondary_rule_checked"],
                hist_entry=p["hist_entry"],
                meta=p["meta"],
            )
            rep = build_execution_report(
                idempotency_key=p["idempotency_key"],
                symbol=symbol,
                typ="SL_UPDATE",
                severity="INFO",
                detail={
                    "mode": settings.runner_trail_mode.upper(),
                    "runner_stop_price": float(new_stop),
                    "timeframe": timeframe,
                    "close_time_ms": close_time_ms,
                },
            )
            publish_execution_report(redis_url, rep)
