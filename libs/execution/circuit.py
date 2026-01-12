# -*- coding: utf-8 -*-
"""账户级熔断评估（Phase 6）"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CircuitDecision:
    soft_halt: bool
    hard_halt: bool
    drawdown_pct: float


def eval_drawdown(*, starting_equity: float, min_equity: float, soft_pct: float, hard_pct: float) -> CircuitDecision:
    dd = 0.0
    if starting_equity > 0:
        dd = (starting_equity - min_equity) / starting_equity * 100.0
    return CircuitDecision(soft_halt=dd >= soft_pct, hard_halt=dd >= hard_pct, drawdown_pct=dd)
