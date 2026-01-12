# -*- coding: utf-8 -*-
"""marketdata-service 配置（Phase 1）

- MARKETDATA_SYMBOLS：订阅的交易对列表
- MARKETDATA_TIMEFRAMES：系统时间框架（15m,30m,1h,4h,8h,1d）
- MARKETDATA_ENABLE_REST_BACKFILL：是否在启动时进行 REST 回填（写库但不发布事件）
- MARKETDATA_BACKFILL_LIMIT：每个 (symbol,timeframe) 回填数量（上限 1000）
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import List


def _csv(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class MarketdataSettings:
    gapfill_enabled: bool
    gapfill_max_bars: int

    symbols: List[str]
    timeframes: List[str]
    enable_rest_backfill: bool
    backfill_limit: int

    @staticmethod
    def load() -> "MarketdataSettings":
        return MarketdataSettings(
            symbols=_csv("MARKETDATA_SYMBOLS", "BTCUSDT"),
            timeframes=_csv("MARKETDATA_TIMEFRAMES", "15m,30m,1h,4h,8h,1d"),
            enable_rest_backfill=os.getenv("MARKETDATA_ENABLE_REST_BACKFILL", "true").lower() == "true",
            backfill_limit=int(os.getenv("MARKETDATA_BACKFILL_LIMIT", "500")),
            gapfill_enabled=os.getenv("MARKETDATA_GAPFILL_ENABLED", "true").lower() == "true",
            gapfill_max_bars=int(os.getenv("MARKETDATA_GAPFILL_MAX_BARS", "2000")),
        )
