"""
事件发布/消费的统一约定（Phase 1）

Redis Streams 的 field/value 都是字符串。为了保持事件结构完整、便于 JSON Schema 校验，
我们采用：

- 写入字段：
  - data: 事件 envelope 的 JSON 字符串
  - type: 事件类型（可选，便于运维过滤）

好处：
- 事件结构不被扁平化破坏；后续扩展字段无需改 Redis schema。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from libs.mq.redis_streams import RedisStreamsClient


def publish_event(
    client: RedisStreamsClient,
    stream: str,
    event: Dict[str, Any],
    event_type: Optional[str] = None,
) -> str:
    payload: Dict[str, Any] = {"data": json.dumps(event, ensure_ascii=False)}
    if event_type:
        payload["type"] = event_type
    return client.publish(stream, payload)
