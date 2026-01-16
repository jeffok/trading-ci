# -*- coding: utf-8 -*-
"""周期工具（Stage 1）"""

from __future__ import annotations

from typing import Dict

TF_TO_MS: Dict[str, int] = {
    "1m": 1 * 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "8h": 8 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def timeframe_ms(tf: str) -> int:
    if tf not in TF_TO_MS:
        raise ValueError(f"unsupported timeframe: {tf}")
    return TF_TO_MS[tf]
