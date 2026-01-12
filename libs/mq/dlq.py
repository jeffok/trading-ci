# -*- coding: utf-8 -*-
"""Dead Letter Queue（Phase 6）"""

from __future__ import annotations

from typing import Any, Dict

from libs.common.time import now_ms
from libs.common.id import new_event_id
from libs.mq.events import publish_event
from libs.mq.redis_streams import RedisStreamsClient

DLQ_STREAM = "stream:dlq"


def publish_dlq(redis_url: str, *, source_stream: str, message_id: str, reason: str, raw_fields: Dict[str, Any]) -> str:
    evt = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "payload": {
            "source_stream": source_stream,
            "message_id": message_id,
            "reason": reason,
            "raw_fields": raw_fields,
        },
    }
    client = RedisStreamsClient(redis_url)
    return publish_event(client, DLQ_STREAM, evt, event_type="dlq")
