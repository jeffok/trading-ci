# -*- coding: utf-8 -*-
"""Stage 8: execution quality metrics.

Compute observability metrics without changing any execution/strategy logic.

Definitions:
- latency_ms: time from order submission to fill timestamp (first fill or full fill when available)
- slippage_bps: (avg_fill_price - reference_price) / reference_price * 10000
- fill_ratio: filled_qty / planned_qty, clamped to [0, 1]

The caller decides which timestamps/prices are the "reference" ones.
"""

from __future__ import annotations

from typing import Optional


def compute_latency_ms(*, submit_ts_ms: Optional[int], fill_ts_ms: Optional[int]) -> Optional[int]:
    """Return latency_ms or None if timestamps missing/invalid."""
    if submit_ts_ms is None or fill_ts_ms is None:
        return None
    try:
        s = int(submit_ts_ms)
        f = int(fill_ts_ms)
    except Exception:
        return None
    if f < s:
        return None
    return f - s


def compute_slippage_bps(*, avg_fill_price: Optional[float], reference_price: Optional[float]) -> Optional[float]:
    """Return slippage in basis points (bps) or None if prices invalid."""
    if avg_fill_price is None or reference_price is None:
        return None
    try:
        a = float(avg_fill_price)
        r = float(reference_price)
    except Exception:
        return None
    if r <= 0:
        return None
    return (a - r) / r * 10000.0


def compute_fill_ratio(*, filled_qty: Optional[float], planned_qty: Optional[float]) -> Optional[float]:
    """Return filled_qty / planned_qty in [0, 1], or None if invalid."""
    if filled_qty is None or planned_qty is None:
        return None
    try:
        f = float(filled_qty)
        p = float(planned_qty)
    except Exception:
        return None
    if p <= 0:
        return None
    x = f / p
    if x < 0:
        x = 0.0
    if x > 1:
        x = 1.0
    return x
