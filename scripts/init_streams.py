# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Redis Streams 初始化脚本（幂等）

说明：
- 允许用两种方式执行：
  1) `python -m scripts.init_streams`（推荐）
  2) `python scripts/init_streams.py`

`python scripts/init_streams.py` 的执行方式会让 sys.path[0] 变成 `scripts/`，
从而导入不到仓库根目录下的 `libs/*`。这里自动把仓库根目录加入 sys.path，
确保在本地/容器内都能正常运行。
"""

from __future__ import annotations

from pathlib import Path
import sys

# --- make repo root importable ---
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import redis

from libs.common.config import settings
from libs.common.retry import retry_call
from libs.mq.redis_streams import RedisStreamsClient

STREAMS = [
    "stream:dlq",
    "stream:bar_close",
    "stream:signal",
    "stream:trade_plan",
    "stream:execution_report",
    "stream:risk_event",
]

def main():
    def _ensure() -> None:
        c = RedisStreamsClient(settings.redis_url)
        # 先 ping 一次，避免连接问题在 ensure_group 里被吞成不直观的错误
        c.r.ping()
        for s in STREAMS:
            c.ensure_group(s, settings.redis_stream_group)

    retry_call(
        _ensure,
        retry_if=lambda e: isinstance(
            e,
            (
                redis.exceptions.ConnectionError,
                redis.exceptions.TimeoutError,
            ),
        ),
        max_attempts=20,
        base_delay_sec=0.5,
        max_delay_sec=3.0,
    )

    print("OK: streams + groups ensured")

if __name__ == "__main__":
    main()
