# -*- coding: utf-8 -*-
"""
共振确认（Phase 2）

你的策略规定：
- Vegas 同向强门槛（必须满足）
- min_confirmations = 2（从 Engulfing / RSI-div / OBV-div / FVG-proximity 中至少命中 2 个）

本模块实现这些确认信号的“最小可用”版本，确保：
- 口径清晰、注释充分
- 不做“提前入场/动态改仓”等会改变策略的行为
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple

from libs.strategy.indicators import ema, rsi as rsi_calc, obv as obv_calc
from libs.strategy.pivots import pivot_highs, pivot_lows


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float


def vegas_state(close: List[float], fast: int = 144, slow: int = 169) -> str:
    """
    Vegas 通道趋势状态（最小实现）
    - Bullish：收盘价 > EMA144 且 > EMA169
    - Bearish：收盘价 < EMA144 且 < EMA169
    - 其他：Neutral

    说明：
    - 这是一个“强门槛方向过滤”，仅用于判定 Bullish/Bearish/Neutral。
    - 不在 Phase 2 引入更复杂的“通道宽度/斜率”规则，避免口径不一致。
    """
    if len(close) < slow:
        return "Neutral"
    e1 = ema(close, fast)
    e2 = ema(close, slow)
    last = close[-1]
    if e1[-1] is None or e2[-1] is None:
        return "Neutral"
    if last > e1[-1] and last > e2[-1]:
        return "Bullish"
    if last < e1[-1] and last < e2[-1]:
        return "Bearish"
    return "Neutral"


def engulfing(last2: List[Candle], direction: str) -> bool:
    """
    Engulfing 形态确认（最小实现）
    - Bullish engulfing：前一根阴线，后一根阳线，且后一根实体包住前一根实体
    - Bearish engulfing：反之

    direction: "LONG" 或 "SHORT"
    """
    if len(last2) < 2:
        return False
    prev, cur = last2[-2], last2[-1]

    prev_body_low = min(prev.open, prev.close)
    prev_body_high = max(prev.open, prev.close)
    cur_body_low = min(cur.open, cur.close)
    cur_body_high = max(cur.open, cur.close)

    if direction == "LONG":
        return (prev.close < prev.open) and (cur.close > cur.open) and (cur_body_low <= prev_body_low) and (cur_body_high >= prev_body_high)
    else:
        return (prev.close > prev.open) and (cur.close < cur.open) and (cur_body_low <= prev_body_low) and (cur_body_high >= prev_body_high)


def rsi_divergence(candles: List[Candle], direction: str, period: int = 14) -> bool:
    """
    RSI 背离确认（最小实现）
    - LONG：价格形成更低低点（pivot_low2 < pivot_low1），而 RSI 在对应点形成更高低点
    - SHORT：价格形成更高高点，而 RSI 形成更低高点

    说明：
    - 只取最近两个 pivot（避免复杂参数导致口径不一）
    - pivot 基于 low/high 序列（分形法）
    """
    if len(candles) < period + 20:
        return False

    close = [c.close for c in candles]
    low = [c.low for c in candles]
    high = [c.high for c in candles]
    r = rsi_calc(close, period=period)

    if direction == "LONG":
        piv = pivot_lows(low)
        if len(piv) < 2:
            return False
        p1, p2 = piv[-2], piv[-1]
        if p2.price >= p1.price:
            return False
        if r[p1.index] is None or r[p2.index] is None:
            return False
        return r[p2.index] > r[p1.index]
    else:
        piv = pivot_highs(high)
        if len(piv) < 2:
            return False
        p1, p2 = piv[-2], piv[-1]
        if p2.price <= p1.price:
            return False
        if r[p1.index] is None or r[p2.index] is None:
            return False
        return r[p2.index] < r[p1.index]


def obv_divergence(candles: List[Candle], direction: str) -> bool:
    """
    OBV 背离确认（最小实现）
    - LONG：价格更低低点，但 OBV 对应点更高
    - SHORT：价格更高高点，但 OBV 对应点更低

    说明：
    - OBV 本身是累计量，易受窗口影响；这里做最小确认：比较 pivot 点的 OBV 值。
    """
    if len(candles) < 50:
        return False

    close = [c.close for c in candles]
    low = [c.low for c in candles]
    high = [c.high for c in candles]
    vol = [c.volume for c in candles]
    o = obv_calc(close, vol)

    if direction == "LONG":
        piv = pivot_lows(low)
        if len(piv) < 2:
            return False
        p1, p2 = piv[-2], piv[-1]
        if p2.price >= p1.price:
            return False
        return o[p2.index] > o[p1.index]
    else:
        piv = pivot_highs(high)
        if len(piv) < 2:
            return False
        p1, p2 = piv[-2], piv[-1]
        if p2.price <= p1.price:
            return False
        return o[p2.index] < o[p1.index]


def fvg_proximity(candles: List[Candle], direction: str, lookback: int = 50) -> bool:
    """
    FVG（Fair Value Gap）接近确认（最小实现）

    常见定义之一：
    - Bullish FVG：第 i 根的 low > 第 i-2 根的 high，形成缺口区间 [high(i-2), low(i)]
    - Bearish FVG：第 i 根的 high < 第 i-2 根的 low，形成缺口区间 [high(i), low(i-2)]

    “proximity” 这里定义为：当前 close 落在最近一个 FVG 区间内。
    说明：这只是“接近关键区间”的确认信号，不改变入场规则。
    """
    if len(candles) < 3:
        return False

    window = candles[-lookback:] if len(candles) > lookback else candles
    cur_close = window[-1].close

    if direction == "LONG":
        # 找最近一个 bullish FVG
        for i in range(len(window) - 1, 1, -1):
            hi_2 = window[i - 2].high
            lo_i = window[i].low
            if lo_i > hi_2:
                # 缺口区间 [hi_2, lo_i]
                return hi_2 <= cur_close <= lo_i
        return False
    else:
        for i in range(len(window) - 1, 1, -1):
            lo_2 = window[i - 2].low
            hi_i = window[i].high
            if hi_i < lo_2:
                # 缺口区间 [hi_i, lo_2]
                return hi_i <= cur_close <= lo_2
        return False
