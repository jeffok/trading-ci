# -*- coding: utf-8 -*-
"""
scripts/init_streams.py

用途：
- 初始化 Redis Streams 的 consumer group（幂等）
- 适用于：首次部署、Redis 重启/清空后恢复、容器启动时自动执行

为什么需要这个脚本：
- 采用 `python scripts/init_streams.py` 直接运行脚本时，Python 默认把 sys.path[0] 设为 scripts/，
  可能导致项目根目录（/data/trading-ci）不在模块搜索路径里，从而找不到 libs.common。
- 本脚本会自动把项目根目录加入 sys.path，确保无论从哪里运行都能 import 项目模块。

建议用法：
- 方式1（推荐，最稳）：python -m scripts.init_streams  （需 scripts/__init__.py）
- 方式2：PYTHONPATH="$PWD" python scripts/init_streams.py
- 方式3：直接 python scripts/init_streams.py（本脚本已兼容）

注意：
- 脚本只做“确保存在”，不会删除 stream 或清理数据。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

import redis

# ---------------------------------------------------------------------
# 1) 确保项目根目录在 sys.path 里，避免 `No module named 'libs.common'`
# ---------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../trading-ci
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 现在可以安全 import 项目内部模块
from libs.common.config import settings  # noqa: E402
from libs.mq.redis_streams import RedisStreamsClient  # noqa: E402


# ---------------------------------------------------------------------
# 2) 需要初始化的 Streams 列表（按项目现有约定）
# ---------------------------------------------------------------------
DEFAULT_STREAMS: List[str] = [
    "stream:bar_close",
    "stream:signal",
    "stream:trade_plan",
    "stream:execution_report",
    "stream:risk_event",
    "stream:dlq",
]


def _get_streams() -> List[str]:
    """
    允许通过环境变量覆盖/追加 streams：
    - TRADING_CI_STREAMS="stream:a,stream:b,stream:c"
    """
    v = os.environ.get("TRADING_CI_STREAMS", "").strip()
    if not v:
        return DEFAULT_STREAMS
    parts = [p.strip() for p in v.split(",") if p.strip()]
    return parts or DEFAULT_STREAMS


def _redis_wait_ready(redis_url: str, *, timeout_sec: int = 60, interval_sec: float = 1.0) -> None:
    """
    等待 Redis 就绪：
    - 容器启动时经常出现 Redis 还没 ready 的竞态，因此这里做等待重试。
    """
    start = time.time()
    last_err = None
    while True:
        try:
            r = redis.Redis.from_url(redis_url, decode_responses=True)
            r.ping()
            return
        except Exception as e:
            last_err = e
            if time.time() - start >= timeout_sec:
                raise RuntimeError(f"Redis not ready after {timeout_sec}s: {last_err}") from last_err
            time.sleep(interval_sec)


def _ensure_groups(redis_url: str, group: str, streams: List[str]) -> Tuple[int, int]:
    """
    幂等创建 group：
    - mkstream=True：没有 stream 时也能创建空 stream
    - BUSYGROUP：表示 group 已存在，忽略即可

    返回：
    - created_count：新建 group 数
    - existed_count：已存在 group 数
    """
    client = RedisStreamsClient(redis_url)
    created = 0
    existed = 0

    for s in streams:
        try:
            # 我们把 xgroup_create 的 id 设为 "0-0"：表示从最早开始。
            # 对于新系统一般无所谓，因为消费时用 ">" 只读新消息。
            client.ensure_group(s, group)
            # ensure_group 内部对 BUSYGROUP 做了吞掉处理；
            # 这里无法直接区分是否新建，所以再通过 xinfo_groups 判断一次（轻量级）。
            try:
                groups = client.r.xinfo_groups(s)
                if any(g.get("name") == group for g in groups):
                    # 这里我们不严格区分新建/已存在，只做统计近似：
                    existed += 1
                else:
                    created += 1
            except Exception:
                # 如果 Redis 版本不支持 xinfo_groups 或权限限制，就不强求
                existed += 1
        except redis.ResponseError as e:
            # 若 ensure_group 没吞掉 BUSYGROUP（理论上不会），这里兜底处理
            if "BUSYGROUP" in str(e):
                existed += 1
                continue
            raise

    return created, existed


def main() -> None:
    redis_url = settings.redis_url
    group = settings.redis_stream_group
    streams = _get_streams()

    print("=== trading-ci init_streams ===")
    print("project_root:", str(PROJECT_ROOT))
    print("redis_url:", redis_url)
    print("group:", group)
    print("streams:", streams)

    # 1) 等待 Redis ready
    _redis_wait_ready(redis_url, timeout_sec=int(os.environ.get("REDIS_WAIT_TIMEOUT", "60")))

    # 2) 幂等创建 groups
    created, existed = _ensure_groups(redis_url, group, streams)

    print("OK: init_streams done")
    print("created_groups:", created)
    print("ensured_groups:", existed)
    print("===============================")


if __name__ == "__main__":
    main()
