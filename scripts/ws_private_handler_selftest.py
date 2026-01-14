# -*- coding: utf-8 -*-
"""Stage 7 自测：不连接交易所，直接喂入模拟 private WS 消息，验证解析与路由不会崩。

用法（建议容器内）：
    python scripts/ws_private_handler_selftest.py

注意：
- 该脚本不写 DB，不依赖 BYBIT key；
- 主要用于保证 handler 能处理常见消息结构。
"""
from __future__ import annotations
import asyncio
import json

from services.execution.ws_private_ingest import handle_private_ws_message

SAMPLES = [
    {
        "topic": "order",
        "data": [{
            "symbol": "BCHUSDT",
            "orderId": "abc",
            "orderLinkId": "link_1",
            "orderStatus": "PartiallyFilled",
            "cumExecQty": "0.5",
            "avgPrice": "617.5"
        }]
    },
    {
        "topic": "execution",
        "data": [{
            "symbol": "BCHUSDT",
            "orderId": "abc",
            "orderLinkId": "link_1",
            "execId": "e1",
            "execQty": "0.5",
            "execPrice": "617.5",
            "cumExecQty": "0.5",
            "leavesQty": "0.71"
        }]
    },
    {
        "topic": "position",
        "data": [{
            "symbol": "BCHUSDT",
            "side": "Buy",
            "size": "1.21",
            "entryPrice": "617.5"
        }]
    },
    {
        "topic": "wallet",
        "data": [{
            "coin": [{"coin": "USDT", "walletBalance": "1000"}]
        }]
    }
]

async def main():
    for i,m in enumerate(SAMPLES, start=1):
        print(f"--- sample {i}: topic={m.get('topic')}")
        await handle_private_ws_message(m)
        print("ok")

if __name__ == "__main__":
    asyncio.run(main())
