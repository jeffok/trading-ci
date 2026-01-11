"""Redis Streams（发布/消费骨架）"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List
import redis

@dataclass
class StreamMessage:
    stream: str
    message_id: str
    fields: Dict[str, Any]

class RedisStreamsClient:
    def __init__(self, redis_url: str):
        self.r = redis.Redis.from_url(redis_url, decode_responses=True)

    def ensure_group(self, stream: str, group: str) -> None:
        """确保 group 存在（幂等）。"""
        try:
            self.r.xgroup_create(stream, group, id="0-0", mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def publish(self, stream: str, payload: Dict[str, Any]) -> str:
        """发布消息到 stream（Phase 0：扁平字段）。"""
        return self.r.xadd(stream, payload)

    def read_group(self, stream: str, group: str, consumer: str, count: int = 10, block_ms: int = 2000) -> List[StreamMessage]:
        """从 consumer group 读取消息。"""
        resp = self.r.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        out: List[StreamMessage] = []
        for (s, msgs) in resp:
            for (mid, fields) in msgs:
                out.append(StreamMessage(stream=s, message_id=mid, fields=fields))
        return out

    def ack(self, stream: str, group: str, message_id: str) -> None:
        self.r.xack(stream, group, message_id)
