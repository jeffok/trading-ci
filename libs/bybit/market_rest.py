"""
Bybit V5 Market REST（最小子集）：Get Kline

官方文档：GET /v5/market/kline
- category 默认 linear
- interval 支持：1,3,5,15,30,60,120,240,360,720,D,W,M
- 返回 list 为字符串数组，按 startTime 逆序

本模块只实现 marketdata-service Phase 1 需要的：
- 拉取最近 N 根 K 线用于“启动回填/补洞”（写库，不发布事件）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class BybitMarketRestClient:
    base_url: str

    def get_kline(
        self,
        *,
        symbol: str,
        interval: str,
        category: str = "linear",
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: int = 200,
        timeout_s: float = 10.0,
    ) -> List[Dict[str, Any]]:
        """
        拉取 K 线，并转为统一结构：
        {
          start_ms, open, high, low, close, volume, turnover?
        }

        注意：REST 返回只包含 startTime；endTime 在分钟类 interval 可推算，D/W/M 不固定。
        Phase 1 的回填用于 warmup，允许近似；真实收盘以 WS 为准。
        """
        params: Dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_ms is not None:
            params["start"] = start_ms
        if end_ms is not None:
            params["end"] = end_ms

        url = f"{self.base_url.rstrip('/')}/v5/market/kline"
        with httpx.Client(timeout=timeout_s) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()

        if data.get("retCode") != 0:
            raise RuntimeError(
                f"bybit_get_kline_failed retCode={data.get('retCode')} retMsg={data.get('retMsg')}"
            )

        raw_list = data["result"]["list"]  # reverse by startTime
        out: List[Dict[str, Any]] = []
        for row in raw_list:
            out.append(
                {
                    "start_ms": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "turnover": float(row[6]) if len(row) > 6 else None,
                }
            )
        return out
