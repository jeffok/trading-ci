# -*- coding: utf-8 -*-
"""
MACD 柱形图三段顶/底背离检测（Phase 2）

你给定的硬规则：
- MACD histogram 三段顶/底背离（核心入场结构）
- 收盘确认入场（marketdata 已保证只在收盘触发 bar_close）
- 第三极值止损（本模块输出第三段极值 price）
- 次日未继续缩短立即退出（属于执行/风控阶段；Phase 2 只产出计划中的 secondary_sl_rule）

实现要点（最小可用且可解释）：
1) 用分形 pivot 识别价格的局部高/低点
2) 从最近的 pivot 中选取 3 个同类极值点（低点序列/高点序列）
3) 判断“价格创新高/新低”与“histogram 走弱”是否成立
   - LONG（底背离）：price 低点逐步降低；histogram 在对应点逐步抬高（更不负）
   - SHORT（顶背离）：price 高点逐步抬高；histogram 在对应点逐步降低（更不正）

注意：
- 这是 Phase 2 的第一版口径：强调清晰与可落地。
- 后续可在“不改变策略定义”的前提下增加：背离强度评分、成交量确认、时间对称性评分等（默认仅评分，不改变决策）。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from libs.strategy.indicators import macd
from libs.strategy.pivots import pivot_highs, pivot_lows, Pivot


@dataclass
class DivergenceSetup:
    direction: str            # "LONG" or "SHORT"
    p1: Pivot
    p2: Pivot
    p3: Pivot
    h1: float                 # histogram value at p1
    h2: float
    h3: float


def detect_three_segment_divergence(
    *,
    close: List[float],
    high: List[float],
    low: List[float],
) -> Optional[DivergenceSetup]:
    """
    在给定序列上检测最近的三段背离。
    若找到，返回 DivergenceSetup，否则 None。

    说明：
    - 为保证“收盘确认入场”，调用方应在 bar_close 后执行。
    - 本函数只输出结构与关键点，并不决定是否下单（还需 Vegas+确认信号门槛）。
    """
    if len(close) < 120:
        # 数据太少：MACD/EMA 不稳定，直接跳过
        return None

    _, _, hist = macd(close)

    # 1) 计算价格 pivot
    lows = pivot_lows(low)
    highs = pivot_highs(high)

    # 辅助函数：hist 值必须存在
    def hist_at(p: Pivot) -> Optional[float]:
        v = hist[p.index]
        return None if v is None else float(v)

    # 2) 尝试底背离（LONG）：取最近三个 pivot low
    if len(lows) >= 3:
        p1, p2, p3 = lows[-3], lows[-2], lows[-1]
        h1 = hist_at(p1)
        h2 = hist_at(p2)
        h3 = hist_at(p3)
        if h1 is not None and h2 is not None and h3 is not None:
            # 价格更低低点（创新低），而 histogram 在对应点逐步抬高（走弱但回升）
            if (p1.price > p2.price > p3.price) and (h1 < h2 < h3):
                return DivergenceSetup(direction="LONG", p1=p1, p2=p2, p3=p3, h1=h1, h2=h2, h3=h3)

    # 3) 尝试顶背离（SHORT）：取最近三个 pivot high
    if len(highs) >= 3:
        p1, p2, p3 = highs[-3], highs[-2], highs[-1]
        h1 = hist_at(p1)
        h2 = hist_at(p2)
        h3 = hist_at(p3)
        if h1 is not None and h2 is not None and h3 is not None:
            # 价格更高高点（创新高），而 histogram 在对应点逐步降低（走弱）
            if (p1.price < p2.price < p3.price) and (h1 > h2 > h3):
                return DivergenceSetup(direction="SHORT", p1=p1, p2=p2, p3=p3, h1=h1, h2=h2, h3=h3)

    return None
