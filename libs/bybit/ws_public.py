# -*- coding: utf-8 -*-
"""Bybit V5 Public WebSocket（线性合约）——最小实现：订阅 Kline

Stage 2 以后我们需要：
- 断线自动重连（指数退避）
- 连接成功事件（用于 WS_RECONNECT 可观测性）
- 将收到的 JSON message 回调给上层（marketdata-service）

注意：
- 本模块只做“连接与消息转发”，不解析业务含义；
- 市场数据“缺口检测/回填”由 marketdata.gapfill 负责。
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional

import websockets

from libs.logging import setup_logging

logger = setup_logging("bybit-public-ws")

MessageHandler = Callable[[dict], Awaitable[None]]
OnConnectedHandler = Callable[[int], Any]


@dataclass
class BybitPublicWsClient:
    ws_url: str
    topics: List[str]
    on_message: MessageHandler
    on_connected: Optional[OnConnectedHandler] = None
    ping_interval_s: int = 20

    async def run_forever(self) -> None:
        """永久运行：断线自动重连。"""
        backoff_s = 1.0
        connect_count = 0

        while True:
            connect_count += 1
            try:
                await self._run_once(connect_count=connect_count)
                # 如果正常退出（很少见），立即重连
                backoff_s = 1.0
            except Exception as e:
                logger.warning("ws_run_once_failed", extra={"extra_fields": {"err": str(e), "backoff_s": backoff_s}})
                # 指数退避 + 抖动
                jitter = random.random() * 0.3
                await asyncio.sleep(backoff_s + jitter)
                backoff_s = min(60.0, backoff_s * 2.0)

    async def _run_once(self, *, connect_count: int) -> None:
        """建立一次连接并持续接收消息，直到异常断开。"""
        async with websockets.connect(self.ws_url, ping_interval=None) as ws:
            logger.info("ws_connected", extra={"extra_fields": {"ws_url": self.ws_url, "connect_count": connect_count}})

            # 连接成功回调（用于 WS_RECONNECT 事件）
            if self.on_connected is not None:
                try:
                    r = self.on_connected(int(connect_count))
                    if asyncio.iscoroutine(r):
                        await r
                except Exception:
                    # 连接回调不应影响 WS 主流程
                    pass

            # 订阅主题
            for t in self.topics:
                await ws.send(json.dumps({"op": "subscribe", "args": [t]}))

            # 心跳任务
            ping_task = asyncio.create_task(self._ping_loop(ws))

            try:
                while True:
                    raw = await ws.recv()
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    await self.on_message(obj)
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except Exception:
                    pass

    async def _ping_loop(self, ws) -> None:
        """按固定间隔发送 ping，保持连接活跃。"""
        while True:
            await asyncio.sleep(float(self.ping_interval_s))
            try:
                await ws.send(json.dumps({"op": "ping"}))
            except Exception:
                return
