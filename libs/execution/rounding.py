# -*- coding: utf-8 -*-
"""数量与价格取整工具（Phase 3/4）

Bybit 对不同合约品种有不同的精度：
- qtyStep：下单数量步进
- minOrderQty：最小下单数量
- tickSize：价格步进

这些字段可以通过 /v5/market/instruments-info 拿到。
"""

from __future__ import annotations

import math


def floor_to_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step) * step


def round_to_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    return round(price / tick) * tick


def clamp_min(x: float, min_value: float) -> float:
    return x if x >= min_value else 0.0


def clamp(x: float, min_value: float, max_value: float) -> float:
    """限制值在 [min_value, max_value] 范围内"""
    if x < min_value:
        return min_value
    if x > max_value:
        return max_value
    return x
