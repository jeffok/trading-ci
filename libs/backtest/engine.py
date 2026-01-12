# -*- coding: utf-8 -*-
"""回测引擎（Phase 5）

目标：
- 复用现有 strategy 逻辑（背离 + Vegas + confirmations）
- 在不改变策略规则的前提下，用“可解释、可复现”的方式模拟执行：
  - 入场：bar_close 的 close（收盘确认）
  - 止损：第三极值（primary_sl_price）
  - 止盈：TP1=1R 40%，TP2=2R 40%，Runner 20% trailing（ATR 或 Pivot）
  - 次日规则：下一根同周期 K 线未继续缩短（hist 不继续走向 0）则退出

重要说明：
- K 线内部的“先碰到 TP 还是 SL”在只有 OHLC 的情况下无法完全确定。
  本引擎默认采用保守假设：同一根 K 同时满足 TP 与 SL 时，优先认为 SL 先触发。
  这样不会夸大收益（避免过拟合/自嗨回测）。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from libs.strategy.divergence import detect_three_segment_divergence
from libs.strategy.confluence import Candle, vegas_state, engulfing, rsi_divergence, obv_divergence, fvg_proximity
from libs.strategy.indicators import macd
from libs.execution.atr import atr_sma
from libs.strategy.pivots import pivot_lows, pivot_highs


@dataclass
class TradeLeg:
    price: float
    qty_pct: float  # 0~1
    typ: str        # ENTRY/TP1/TP2/EXIT/SL


@dataclass
class TradeResult:
    symbol: str
    timeframe: str
    entry_i: int
    exit_i: int
    side: str  # BUY/SELL
    entry: float
    sl_initial: float
    tp1: float
    tp2: float
    legs: List[TradeLeg]
    pnl_r: float
    reason: str


def _hist_last(close: List[float]) -> Optional[float]:
    _, _, hist = macd(close)
    v = hist[-1]
    return None if v is None else float(v)


def _r(entry: float, sl: float) -> float:
    return abs(entry - sl)


def backtest(
    *,
    symbol: str,
    timeframe: str,
    bars: List[Dict[str, Any]],
    min_confirmations: int = 2,
    auto_only: bool = True,
    trail_mode: str = "ATR",
    atr_period: int = 14,
    atr_mult: float = 2.0,
) -> List[TradeResult]:
    """返回所有交易结果（单位仓位：1.0）"""
    results: List[TradeResult] = []

    # 回测从足够指标长度之后开始
    for i in range(120, len(bars)):
        window = bars[max(0, i - 500): i + 1]
        candles = [Candle(open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b.get("volume", 0.0)) for b in window]

        close = [c.close for c in candles]
        high = [c.high for c in candles]
        low = [c.low for c in candles]

        setup = detect_three_segment_divergence(close=close, high=high, low=low)
        if setup is None:
            continue

        bias = setup.direction  # LONG/SHORT

        # Vegas 强门槛
        vs = vegas_state(close)
        if bias == "LONG" and vs != "Bullish":
            continue
        if bias == "SHORT" and vs != "Bearish":
            continue

        hits: List[str] = []
        if engulfing(candles[-2:], bias):
            hits.append("ENGULFING")
        if rsi_divergence(close=close, high=high, low=low, bias=bias):
            hits.append("RSI_DIV")
        if obv_divergence(close=close, volume=[c.volume for c in candles], bias=bias):
            hits.append("OBV_DIV")
        if fvg_proximity(candles=candles, bias=bias):
            hits.append("FVG_PROXIMITY")

        if len(hits) < min_confirmations:
            continue

        # 入场
        entry = float(candles[-1].close)
        sl = float(setup.p3.price)
        r = _r(entry, sl)
        if r <= 0:
            continue

        side = "BUY" if bias == "LONG" else "SELL"
        tp1 = entry + r if side == "BUY" else entry - r
        tp2 = entry + 2 * r if side == "BUY" else entry - 2 * r

        legs: List[TradeLeg] = [TradeLeg(price=entry, qty_pct=1.0, typ="ENTRY")]
        remaining = 1.0
        sl_active = sl
        moved_to_be = False
        runner_enabled = False
        runner_stop: Optional[float] = None

        # 记录 entry 时 histogram（用于次日规则）
        hist_entry = _hist_last(close)

        exit_i = i
        reason = "TIMEOUT"
        pnl_r = 0.0

        # 从下一根 K 开始推进
        for j in range(i + 1, len(bars)):
            b = bars[j]
            hi = float(b["high"])
            lo = float(b["low"])
            cl = float(b["close"])

            # 次日规则：只检查一次（下一根同周期 K 的 close）
            if j == i + 1:
                # 重新计算到当前 close 的 hist
                close2 = [x["close"] for x in bars[max(0, j - 500): j + 1]]
                hist_now = _hist_last(close2)
                ok = True
                if hist_entry is not None and hist_now is not None:
                    if bias == "LONG":
                        ok = hist_now > hist_entry
                    else:
                        ok = hist_now < hist_entry
                if not ok:
                    # 退出：按当前 close
                    legs.append(TradeLeg(price=cl, qty_pct=remaining, typ="EXIT"))
                    pnl_r = (cl - entry) / r if side == "BUY" else (entry - cl) / r
                    exit_i = j
                    reason = "NEXT_BAR_NOT_SHORTEN_EXIT"
                    remaining = 0.0
                    break

            # 先检查止损（保守：同一根 K 同时 hit TP/SL 时按 SL 先发生）
            if remaining > 0:
                if side == "BUY" and lo <= sl_active:
                    legs.append(TradeLeg(price=sl_active, qty_pct=remaining, typ="SL"))
                    pnl_r = (sl_active - entry) / r  # negative
                    remaining = 0.0
                    exit_i = j
                    reason = "STOP_LOSS"
                    break
                if side == "SELL" and hi >= sl_active:
                    legs.append(TradeLeg(price=sl_active, qty_pct=remaining, typ="SL"))
                    pnl_r = (entry - sl_active) / r  # negative
                    remaining = 0.0
                    exit_i = j
                    reason = "STOP_LOSS"
                    break

            # TP1
            if remaining > 0.6:  # 还没做过 TP1
                if (side == "BUY" and hi >= tp1) or (side == "SELL" and lo <= tp1):
                    legs.append(TradeLeg(price=tp1, qty_pct=0.4, typ="TP1"))
                    remaining -= 0.4
                    # TP1 后 SL 移到 BE
                    sl_active = entry
                    moved_to_be = True

            # TP2
            if remaining > 0.2:  # 还没做过 TP2（TP2 做完剩 20%）
                if (side == "BUY" and hi >= tp2) or (side == "SELL" and lo <= tp2):
                    legs.append(TradeLeg(price=tp2, qty_pct=0.4, typ="TP2"))
                    remaining -= 0.4
                    runner_enabled = True

            # Runner trailing stop（只对剩余 20%）
            if remaining > 0 and runner_enabled:
                # 更新 runner_stop：使用当前窗口的 ATR 或 pivot
                win = bars[max(0, j - 500): j + 1]
                close_w = [float(x["close"]) for x in win]
                high_w = [float(x["high"]) for x in win]
                low_w = [float(x["low"]) for x in win]

                new_stop = None
                if trail_mode.upper() == "ATR":
                    atr = atr_sma(high_w, low_w, close_w, period=atr_period)
                    if atr[-1] is not None:
                        v = float(atr[-1]) * float(atr_mult)
                        new_stop = cl - v if side == "BUY" else cl + v
                else:
                    if side == "BUY":
                        piv = pivot_lows(low_w)
                        if piv:
                            new_stop = float(piv[-1].price)
                    else:
                        piv = pivot_highs(high_w)
                        if piv:
                            new_stop = float(piv[-1].price)

                if new_stop is not None:
                    if runner_stop is None:
                        runner_stop = new_stop
                    else:
                        runner_stop = max(runner_stop, new_stop) if side == "BUY" else min(runner_stop, new_stop)
                    # runner 的止损不能比全仓 sl_active 更宽松（安全起见取更严格）
                    if side == "BUY":
                        sl_active = max(sl_active, runner_stop)
                    else:
                        sl_active = min(sl_active, runner_stop)

            # 如果跑到最后还没退出：当作持有到最后 close
            if j == len(bars) - 1 and remaining > 0:
                legs.append(TradeLeg(price=cl, qty_pct=remaining, typ="EXIT"))
                pnl_r = (cl - entry) / r if side == "BUY" else (entry - cl) / r
                remaining = 0.0
                exit_i = j
                reason = "END_OF_DATA"

        results.append(TradeResult(
            symbol=symbol, timeframe=timeframe, entry_i=i, exit_i=exit_i,
            side=side, entry=entry, sl_initial=sl, tp1=tp1, tp2=tp2,
            legs=legs, pnl_r=float(pnl_r), reason=reason
        ))

    return results
