"""
Bybit interval 映射

系统内部 timeframes：15m/30m/1h/4h/8h/1d
Bybit V5 Kline interval（官方）：1,3,5,15,30,60,120,240,360,720,D,W,M

注意：官方不提供 8h(480)。
因此：8h candle 通过 1h candle 聚合生成（Phase 1 在 marketdata-service 实现）。
"""

from __future__ import annotations

from typing import Optional


SYSTEM_TF_TO_BYBIT_INTERVAL = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
    # "8h": None  # 明确不支持
}


def bybit_interval_for_system_timeframe(tf: str) -> Optional[str]:
    """返回 Bybit interval 字符串；若该 timeframe 需要派生（如 8h），返回 None。"""
    return SYSTEM_TF_TO_BYBIT_INTERVAL.get(tf)
