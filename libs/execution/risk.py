# -*- coding: utf-8 -*-
"""执行层风控/仓位计算（Phase 3/4）

策略不变，执行层只做“把策略计划变成可执行的订单”。

仓位计算（核心）：
- 风险金额 = equity * risk_pct
- 单位风险（每 1 合约/1 币的亏损） = abs(entry - stop)
- 目标数量 qty = 风险金额 / 单位风险
- 再根据 instruments-info 的 qtyStep/minOrderQty 做取整与最小值校验

注意：
- 对 USDT 永续（linear），qty 通常表示合约数量（与币数量接近但不完全等同，视合约设计）。
- Phase 4 默认使用简化模型；后续可扩展为：考虑杠杆、保证金模式、手续费、滑点预估等。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple

from libs.execution.rounding import floor_to_step, clamp_min, round_to_tick


@dataclass
class InstrumentFilters:
    qty_step: float
    min_qty: float
    tick_size: float


def calc_qty(*, equity: float, risk_pct: float, entry: float, stop: float, filters: InstrumentFilters) -> float:
    risk_amount = equity * risk_pct
    unit_risk = abs(entry - stop)

    if unit_risk <= 0:
        return 0.0

    raw_qty = risk_amount / unit_risk
    qty = floor_to_step(raw_qty, filters.qty_step)
    qty = clamp_min(qty, filters.min_qty)
    return float(qty)


def split_tp_qty(total_qty: float) -> Tuple[float, float, float]:
    """按策略：TP1 40%，TP2 40%，Runner 20%"""
    tp1 = total_qty * 0.4
    tp2 = total_qty * 0.4
    runner = total_qty - tp1 - tp2
    return float(tp1), float(tp2), float(runner)


def tp_prices(*, side: str, entry: float, stop: float, tick_size: float) -> Tuple[float, float]:
    """按 1R/2R 生成 TP1/TP2 价格，并按 tickSize 对齐"""
    r = abs(entry - stop)
    if side == "BUY":
        p1 = entry + r
        p2 = entry + 2 * r
    else:
        p1 = entry - r
        p2 = entry - 2 * r

    p1 = round_to_tick(p1, tick_size)
    p2 = round_to_tick(p2, tick_size)
    return float(p1), float(p2)
