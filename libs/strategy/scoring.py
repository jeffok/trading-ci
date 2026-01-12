# -*- coding: utf-8 -*-
"""信号质量评分（Phase 5）

原则：不改变策略决策，只提供“可观测/可复盘”的评分字段。
执行层不依赖该分数（除非你未来显式开启）。

评分范围：0~100
- divergence_strength（0~60）：背离结构强度
- confluence_strength（0~40）：共振确认强度（min_confirmations=2 仍保持不变）

背离强度（示例实现，易读优先）：
- hist_shorten_pct：第三段柱子相对第二段缩短比例，>=15% 给满分（核心建议）
- price_ext_diff：第三段与第二段价格极值差异（差异越明显越强，做归一化）
- symmetry_penalty：三段时间间隔过于失衡时扣分（仅做提示，不做过滤）

注意：这里的计算不追求“学术最优”，目标是：
- 给你一个稳定、可解释的评分，便于排序、回测分桶、复盘。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class DivergenceFeatures:
    # MACD histogram second/third segment magnitude (abs)
    hist2: float
    hist3: float
    # price extremes
    price2: float
    price3: float
    # index positions of segments (for symmetry)
    i1: int
    i2: int
    i3: int


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def divergence_strength(feat: DivergenceFeatures) -> float:
    """0~60"""
    # 1) histogram shorten ratio
    h2 = abs(feat.hist2) if feat.hist2 is not None else 0.0
    h3 = abs(feat.hist3) if feat.hist3 is not None else 0.0
    shorten = 0.0
    if h2 > 1e-12:
        shorten = (h2 - h3) / h2  # 0.15 means 15% shorten
    shorten_score = _clamp(shorten / 0.15, 0.0, 1.0) * 30.0  # up to 30

    # 2) price extreme separation
    pd = abs(feat.price3 - feat.price2)
    # normalize by price2 (avoid scale issues)
    base = abs(feat.price2) if abs(feat.price2) > 1e-12 else 1.0
    rel = pd / base
    price_score = _clamp(rel / 0.01, 0.0, 1.0) * 20.0  # 1% diff -> full 20

    # 3) symmetry penalty (0~10)
    d12 = abs(feat.i2 - feat.i1)
    d23 = abs(feat.i3 - feat.i2)
    sym = 1.0
    if min(d12, d23) > 0:
        ratio = max(d12, d23) / min(d12, d23)
        # ratio <=2 => ok, ratio >=4 => poor
        sym = _clamp((4.0 - ratio) / 2.0, 0.0, 1.0)
    sym_score = sym * 10.0

    return float(shorten_score + price_score + sym_score)  # 0~60


def confluence_strength(*, hit_count: int, min_confirmations: int = 2) -> float:
    """0~40：只按数量给分（不改变规则），>=min_confirmations 之后分数继续提升"""
    if hit_count <= 0:
        return 0.0
    # 从 min_confirmations 起算更有意义
    base = max(0, hit_count - min_confirmations + 1)
    # base=1 => 20, base=2 => 30, base>=3 => 40
    if base <= 0:
        return 10.0
    if base == 1:
        return 20.0
    if base == 2:
        return 30.0
    return 40.0


def signal_quality_score(*, divergence_score: float, confluence_score: float) -> float:
    return float(_clamp(divergence_score + confluence_score, 0.0, 100.0))
