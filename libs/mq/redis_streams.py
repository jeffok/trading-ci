# -*- coding: utf-8 -*-
"""Redis Streams（发布/消费/运维工具）

说明：
- 项目采用 Redis Streams 作为服务间事件总线。
- 早期版本仅封装 publish/read/ack；CI/回放需要 group 初始化、滞后(lag)与 pending 监控能力，
  因此在不增加复杂依赖的前提下补齐常用运维接口。

重要原则：
- 所有方法都尽量“幂等”与“容错”：在 CI/回放场景下，重复调用不会破坏状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import redis


@dataclass
class StreamMessage:
    stream: str
    message_id: str
    fields: Dict[str, Any]


class RedisStreamsClient:
    def __init__(self, redis_url: str):
        self.r = redis.Redis.from_url(redis_url, decode_responses=True)

    # ---------------- publish/consume ----------------

    def publish(self, stream: str, payload: Dict[str, Any]) -> str:
        """发布消息到 stream（扁平字段）"""
        return self.r.xadd(stream, payload)

    def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_ms: int = 2000,
    ) -> List[StreamMessage]:
        """从 consumer group 读取消息（只读新消息：">"）。"""
        resp = self.r.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        out: List[StreamMessage] = []
        for (s, msgs) in resp:
            for (mid, fields) in msgs:
                out.append(StreamMessage(stream=s, message_id=mid, fields=fields))
        return out

    def ack(self, stream: str, group: str, message_id: str) -> None:
        self.r.xack(stream, group, message_id)

    # ---------------- admin helpers ----------------

    def ensure_group(self, stream: str, group: str) -> None:
        """确保 stream 与 group 存在（幂等）。"""
        try:
            # mkstream=True：即使 stream 为空也创建
            self.r.xgroup_create(stream, group, id="0-0", mkstream=True)
        except redis.ResponseError as e:
            # BUSYGROUP 表示已存在
            if "BUSYGROUP" in str(e):
                return
            raise

    def delete_stream(self, stream: str) -> None:
        """删除整个 stream（CI/回放独立环境可用）。"""
        self.r.delete(stream)

    def pending_count(self, stream: str, group: str) -> int:
        """返回 group 未 ack 的 pending 数量（XPENDING summary）。"""
        try:
            summary = self.r.xpending(stream, group)
            # redis-py 返回 dict: {'pending': 0, 'min': None, 'max': None, 'consumers': []}
            if isinstance(summary, dict):
                return int(summary.get("pending", 0))
            # 兼容旧返回
            if isinstance(summary, (list, tuple)) and summary:
                return int(summary[0])
        except redis.ResponseError:
            return 0
        return 0

    def group_lag(self, stream: str, group: str) -> Optional[int]:
        """返回 group lag（XINFO GROUPS 中的 lag 字段）。若 Redis 版本不支持则返回 None。"""
        try:
            groups = self.r.xinfo_groups(stream)
            for g in groups:
                if g.get("name") == group:
                    # Redis 7+ 通常会返回 lag
                    if "lag" in g and g["lag"] is not None:
                        return int(g["lag"])
                    return None
        except redis.ResponseError:
            return None
        return None

    def stream_length(self, stream: str) -> int:
        try:
            return int(self.r.xlen(stream))
        except redis.ResponseError:
            return 0
