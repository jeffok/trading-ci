# -*- coding: utf-8 -*-
"""Bybit V5 Private WebSocket（线性合约）——最小可用实现（Stage 7）

目标（按需求文档）：
- 订阅私有推送：order / execution / position / wallet
- 断线自动重连（指数退避 + jitter）
- 连接成功后回调（用于发布 WS_RECONNECT risk_event）
- 将原始消息回调给上层（execution-service 用于一致性/对账）
- 不在此模块内写 DB / 发布 stream（保持纯网络层）

注意：
- Bybit 私有 WS 鉴权签名采用：HMAC_SHA256(secret, f"GET/realtime{expires}")
  这是 Bybit 常见写法；如你使用的环境要求不同，可通过 settings 覆盖 auth_path。
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import random
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Awaitable, Callable, Dict, List, Optional

import websockets

logger = logging.getLogger(__name__)

OnMessage = Callable[[Dict[str, Any]], Awaitable[None] | None]
OnConnected = Callable[[int], Awaitable[None] | None]
OnDisconnected = Callable[[str], Awaitable[None] | None]


def _hmac_sha256(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), sha256).hexdigest()


@dataclass
class BybitV5PrivateWsClient:
    ws_url: str
    api_key: str
    api_secret: str
    subscriptions: List[str]

    auth_path: str = "/realtime"  # used to build signing string: GET{auth_path}{expires}
    on_message: Optional[OnMessage] = None
    on_connected: Optional[OnConnected] = None
    on_disconnected: Optional[OnDisconnected] = None

    async def run_forever(self) -> None:
        backoff_s = 1.0
        connect_count = 0
        while True:
            connect_count += 1
            try:
                await self._run_once(connect_count=connect_count)
                backoff_s = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                reason = f"{type(e).__name__}:{e}"
                logger.warning("ws_private_disconnected", extra={"extra_fields": {"reason": reason, "backoff_s": backoff_s}})
                if self.on_disconnected is not None:
                    try:
                        r = self.on_disconnected(reason)
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception:
                        logger.exception("ws_private_on_disconnected_failed")
                jitter = random.random() * 0.3
                await asyncio.sleep(backoff_s + jitter)
                backoff_s = min(60.0, backoff_s * 2.0)

    async def _run_once(self, *, connect_count: int) -> None:
        async with websockets.connect(self.ws_url, ping_interval=None) as ws:
            logger.info("ws_private_connected", extra={"extra_fields": {"ws_url": self.ws_url, "connect_count": connect_count}})
            # connected callback
            if self.on_connected is not None:
                r = self.on_connected(int(connect_count))
                if asyncio.iscoroutine(r):
                    await r

            # auth
            expires = int(time.time() * 1000) + 10_000
            sign_payload = f"GET{self.auth_path}{expires}"
            sig = _hmac_sha256(self.api_secret, sign_payload)
            auth_msg = {"op": "auth", "args": [self.api_key, expires, sig]}
            await ws.send(json.dumps(auth_msg))

            # wait auth response (best-effort)
            auth_ok = False
            for _ in range(20):
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("op") == "auth" or msg.get("type") == "AUTH_RESP":
                    auth_ok = bool(msg.get("success", False)) or msg.get("retCode") in (0, "0")
                    if not auth_ok:
                        raise RuntimeError(f"ws_auth_failed:{msg}")
                    break
            if not auth_ok:
                # Some environments do not echo auth response; continue but log.
                logger.warning("ws_private_auth_no_ack")

            # subscribe
            if self.subscriptions:
                sub_msg = {"op": "subscribe", "args": self.subscriptions}
                await ws.send(json.dumps(sub_msg))

            # recv loop
            while True:
                raw = await ws.recv()
                try:
                    msg = json.loads(raw)
                except Exception:
                    logger.warning("ws_private_bad_json", extra={"extra_fields": {"raw": raw[:200]}})
                    continue
                if self.on_message is not None:
                    try:
                        r = self.on_message(msg)
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception:
                        logger.exception("ws_private_on_message_failed")
