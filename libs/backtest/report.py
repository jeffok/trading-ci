# -*- coding: utf-8 -*-
"""回测报告汇总（Phase 5）"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from libs.backtest.engine import TradeResult


def summarize(results: List[TradeResult]) -> Dict[str, Any]:
    if not results:
        return {"count": 0, "win_rate": 0.0, "avg_r": 0.0, "sum_r": 0.0, "max_dd_r": 0.0}

    rs = [r.pnl_r for r in results]
    wins = [x for x in rs if x > 0]
    win_rate = len(wins) / len(rs)

    # equity curve in R
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)

    return {
        "count": len(rs),
        "win_rate": float(win_rate),
        "avg_r": float(sum(rs) / len(rs)),
        "sum_r": float(sum(rs)),
        "max_dd_r": float(max_dd),
    }


def to_jsonable(results: List[TradeResult]) -> List[Dict[str, Any]]:
    out = []
    for r in results:
        d = asdict(r)
        d["legs"] = [asdict(x) for x in r.legs]
        out.append(d)
    return out
