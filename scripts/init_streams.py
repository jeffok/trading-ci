"""Redis Streams 初始化脚本（幂等）"""
from __future__ import annotations
from libs.common.config import settings
from libs.mq.redis_streams import RedisStreamsClient

STREAMS = [
  "stream:bar_close",
  "stream:signal",
  "stream:trade_plan",
  "stream:execution_report",
  "stream:risk_event",
]

def main():
    c = RedisStreamsClient(settings.redis_url)
    for s in STREAMS:
        c.ensure_group(s, settings.redis_stream_group)
    print("OK: streams + groups ensured")

if __name__ == "__main__":
    main()
