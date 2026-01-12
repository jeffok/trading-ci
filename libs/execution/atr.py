# -*- coding: utf-8 -*-
"""ATR(平均真实波幅)（Phase 4）

用于 Runner（剩余 20%）的跟随止损：
- LONG：stop = max(prev_stop, close - ATR * mult)
- SHORT：stop = min(prev_stop, close + ATR * mult)

实现：
- True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
- ATR：使用简单移动平均（SMA）作为最小实现（可读性强）
"""

from __future__ import annotations
from typing import List, Optional


def true_range(high: List[float], low: List[float], close: List[float]) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(close)
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        out[i] = float(tr)
    return out


def atr_sma(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[Optional[float]]:
    if len(close) < period + 1:
        return [None] * len(close)

    tr = true_range(high, low, close)
    out: List[Optional[float]] = [None] * len(close)

    # SMA over TR (skip None at tr[0])
    window: List[float] = []
    for i in range(1, len(close)):
        if tr[i] is None:
            continue
        window.append(tr[i])
        if len(window) > period:
            window.pop(0)
        if len(window) == period:
            out[i] = sum(window) / period
    return out
