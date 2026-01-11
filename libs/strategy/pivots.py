# -*- coding: utf-8 -*-
"""
Pivot/分形点检测（Phase 2）

用途：
- 三段背离需要识别“局部高点/低点”。
- 本实现采用类似 Williams Fractal 的方法：
  pivot_high：当前高点 > 左右各 N 根高点
  pivot_low ：当前低点 < 左右各 N 根低点

说明：
- 这是一种稳定、可解释的极值识别方式。
- 注意：它只是“极值识别手段”，并不改变你的策略定义（策略仍是三段背离）。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List


@dataclass
class Pivot:
    index: int
    price: float


def pivot_highs(high: List[float], left: int = 2, right: int = 2) -> List[Pivot]:
    pivots: List[Pivot] = []
    for i in range(left, len(high) - right):
        h = high[i]
        if all(h > high[i - k] for k in range(1, left + 1)) and all(h > high[i + k] for k in range(1, right + 1)):
            pivots.append(Pivot(index=i, price=float(h)))
    return pivots


def pivot_lows(low: List[float], left: int = 2, right: int = 2) -> List[Pivot]:
    pivots: List[Pivot] = []
    for i in range(left, len(low) - right):
        l = low[i]
        if all(l < low[i - k] for k in range(1, left + 1)) and all(l < low[i + k] for k in range(1, right + 1)):
            pivots.append(Pivot(index=i, price=float(l)))
    return pivots
