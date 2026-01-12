# -*- coding: utf-8 -*-
"""DLQ 查询（Stage 3）

说明：
- DLQ 在 Redis Streams（stream:dlq）中，内容包含：source_stream/message_id/reason/raw_fields。
- API 侧只做“最近 N 条”的只读查询，用于排障。
"""

from __future__ import annotations
from typing import Any, Dict, List
import redis


def read_dlq(redis_url: str, *, count: int = 50) -> List[Dict[str, Any]]:
    r = redis.Redis.from_url(redis_url, decode_responses=True)
    # 取最新的 N 条
    items = r.xrevrange("stream:dlq", max="+", min="-", count=int(count))
    out: List[Dict[str, Any]] = []
    for msg_id, fields in items:
        out.append({"message_id": msg_id, "fields": fields})
    return out
