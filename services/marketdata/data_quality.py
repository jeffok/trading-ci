# -*- coding: utf-8 -*-
"""Stage 11: market data quality checks (non-trading).

Emits risk_event for observability only. Must not change trading logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from libs.common.time import now_ms


@dataclass
class DataQualityFinding:
    typ: str
    severity: str
    detail: Dict[str, Any]


def check_data_lag(*, close_time_ms: int, lag_threshold_ms: int, source_ts_ms: Optional[int] = None) -> Optional[DataQualityFinding]:
    lag = now_ms() - int(close_time_ms)
    if lag_threshold_ms > 0 and lag > lag_threshold_ms:
        return DataQualityFinding(
            typ="DATA_LAG",
            severity="IMPORTANT" if lag > lag_threshold_ms * 2 else "INFO",
            detail={
                "close_time_ms": int(close_time_ms),
                "lag_ms": int(lag),
                "threshold_ms": int(lag_threshold_ms),
                "source_ts_ms": int(source_ts_ms) if source_ts_ms else None,
            },
        )
    return None


def check_duplicate_bar(*, existing: Optional[Dict[str, Any]], incoming: Dict[str, Any], diff_eps: float = 1e-9) -> Optional[DataQualityFinding]:
    if not existing:
        return None
    keys = ["open", "high", "low", "close", "volume"]
    diffs: Dict[str, Any] = {}
    for k in keys:
        ev = float(existing.get(k) or 0.0)
        iv = float(incoming.get(k) or 0.0)
        if abs(ev - iv) > diff_eps:
            diffs[k] = {"old": ev, "new": iv}
    if diffs:
        return DataQualityFinding(
            typ="BAR_DUPLICATE",
            severity="IMPORTANT",
            detail={
                "close_time_ms": int(incoming["close_time_ms"]),
                "diffs": diffs,
                "existing_source": existing.get("source"),
                "incoming_source": incoming.get("source"),
            },
        )
    return None


def check_price_jump(*, prev_close: Optional[float], close: float, jump_pct_threshold: float) -> Optional[DataQualityFinding]:
    if prev_close is None or prev_close <= 0:
        return None
    pct = abs(close - prev_close) / prev_close
    if jump_pct_threshold > 0 and pct >= jump_pct_threshold:
        return DataQualityFinding(
            typ="PRICE_JUMP",
            severity="IMPORTANT" if pct >= jump_pct_threshold * 2 else "INFO",
            detail={
                "prev_close": float(prev_close),
                "close": float(close),
                "jump_pct": float(pct),
                "threshold_pct": float(jump_pct_threshold),
            },
        )
    return None


def check_volume_anomaly(*, volume: float, recent_volumes: List[float], spike_multiple: float) -> Optional[DataQualityFinding]:
    if spike_multiple <= 0:
        return None
    vols = [float(v) for v in recent_volumes if v is not None and v > 0]
    if len(vols) < 10:
        return None
    vols_sorted = sorted(vols)
    mid = len(vols_sorted) // 2
    median = vols_sorted[mid] if len(vols_sorted) % 2 == 1 else (vols_sorted[mid - 1] + vols_sorted[mid]) / 2.0
    if median <= 0:
        return None
    multiple = float(volume) / median
    if multiple >= spike_multiple:
        return DataQualityFinding(
            typ="VOLUME_ANOMALY",
            severity="IMPORTANT" if multiple >= spike_multiple * 2 else "INFO",
            detail={
                "volume": float(volume),
                "median_volume": float(median),
                "spike_multiple": float(multiple),
                "threshold_multiple": float(spike_multiple),
                "window": len(vols),
            },
        )
    return None
