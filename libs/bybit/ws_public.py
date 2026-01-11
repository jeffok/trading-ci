"""
Bybit V5 Public WebSocket（线性合约）——最小实现：订阅 Kline

官方要点：
- 连接地址（linear）：wss://stream.bybit.com/v5/public/linear
- 订阅格式：{"op":"subscribe","args":["kline.{interval}.{symbol}"]}
- Kline push：data[].confirm=true 表示 candle 收盘（可用于 bar_close 事件触发）
- 心跳：建议每 20s 发送 {"op":"ping"} 维持连接

本模块目标（Phase 1）：
- 管理连接/重连/心跳
- 将收到的 JSON message 回调给上层（marketdata-service）
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Awaitable, Callable, List

import websockets


MessageHandler = Callable[[dict], Awaitable[None]]


@dataclass
class BybitPublicWsClient:
    ws_url: str
    topics: List[str]
    on_message: MessageHandler
    ping_interval_s: int = 20

    async def run_forever(self) -> None:
        """
        永久在线：断线自动重连（指数退避 + 抖动）。
        """
        backoff_s = 1
        while True:
            try:
                await self._run_once()
                backoff_s = 1  # 正常退出后重置（通常不会发生）
            except Exception:
                sleep_s = min(60, backoff_s) + random.random()
                await asyncio.sleep(sleep_s)
                backoff_s *= 2

    async def _run_once(self) -> None:
        """连接一次，直到异常或被关闭。"""
        async with websockets.connect(self.ws_url, ping_interval=None) as ws:
            # 订阅主题
            await ws.send(json.dumps({"op": "subscribe", "args": self.topics}))

            # 启动心跳任务：建议每 20s 发送 ping 保持连接
            ping_task = asyncio.create_task(self._heartbeat(ws))

            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    await self.on_message(msg)
            finally:
                ping_task.cancel()

    async def _heartbeat(self, ws) -> None:
        """定时发送 ping，维持连接。"""
        while True:
            await asyncio.sleep(self.ping_interval_s)
            try:
                await ws.send(json.dumps({"op": "ping"}))
            except Exception:
                return
