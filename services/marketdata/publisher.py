"""
bar_close 事件发布器（Phase 1）

职责：
- 构造 EventEnvelope + payload
- JSON Schema 校验（发布前）
- 写入 Redis Streams：stream:bar_close
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from libs.common.config import settings
from libs.common.id import new_event_id, new_trace_id
from libs.common.time import now_ms
from libs.mq.events import publish_event
from libs.mq.redis_streams import RedisStreamsClient
from libs.mq.schema_validator import validate


BAR_CLOSE_SCHEMA = "streams/bar-close.json"
STREAM_NAME = "stream:bar_close"


def build_bar_close_event(
    *,
    symbol: str,
    timeframe: str,
    close_time_ms: int,
    source: str,
    ohlcv: Dict[str, Any],
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    event = {
        "event_id": new_event_id(),
        "ts_ms": now_ms(),
        "env": settings.env,
        "service": "marketdata-service",
        "trace_id": trace_id or new_trace_id(),
        "schema_version": 1,
        "meta": {},
        "payload": {
            "symbol": symbol,
            "timeframe": timeframe,
            "close_time_ms": close_time_ms,
            "is_final": True,
            "source": source,
            "ohlcv": ohlcv,
            "ext": {},
        },
        "ext": {},
    }
    validate(BAR_CLOSE_SCHEMA, event)
    return event


def publish_bar_close(redis_url: str, event: Dict[str, Any]) -> str:
    client = RedisStreamsClient(redis_url)
    return publish_event(client, STREAM_NAME, event, event_type="bar_close")
