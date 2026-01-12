# -*- coding: utf-8 -*-
"""
scripts/init_streams.py

目的：
- 初始化 Redis Streams 的 consumer group（幂等）
- 适用于：首次部署、Redis 重启/清空后恢复、容器启动时自动执行

本文件特别处理：
- 解决 "ModuleNotFoundError: No module named 'libs.common'"：
  1) 强制把项目根目录插入 sys.path[0]
  2) 如果发现 sys.modules 中已缓存了“错误来源”的 libs（第三方同名包），主动清掉再导入
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List

import redis


# ---------------------------------------------------------------------
# 1) 强制把项目根目录加入 sys.path（放到最前面，优先级最高）
# ---------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # /data/trading-ci
PROJECT_ROOT_STR = str(PROJECT_ROOT)

if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)
else:
    # 确保在最前面
    sys.path.remove(PROJECT_ROOT_STR)
    sys.path.insert(0, PROJECT_ROOT_STR)


# ---------------------------------------------------------------------
# 2) 防御：清理错误来源的 libs（同名冲突/缓存）
#    如果 libs 已经被加载，但不是来自项目根目录，则删除缓存让它重新按 sys.path[0] 解析
# ---------------------------------------------------------------------
def _purge_conflicting_libs() -> None:
    mod = sys.modules.get("libs")
    if not mod:
        return

    # libs 可能是 namespace package，没有 __file__，用 __path__ 判断
    mod_file = getattr(mod, "__file__", None)
    mod_path = getattr(mod, "__path__", None)

    # 判定是否来自项目根目录
    ok = False
    if mod_file and PROJECT_ROOT_STR in str(mod_file):
        ok = True
    if mod_path:
        # __path__ 可能是 _NamespacePath，可遍历
        try:
            for p in list(mod_path):
                if PROJECT_ROOT_STR in str(p):
                    ok = True
                    break
        except Exception:
            pass

    if not ok:
        # 删除缓存，防止后续 import 继续用错误的 libs
        del sys.modules["libs"]


_purge_conflicting_libs()


# ---------------------------------------------------------------------
# 3) 现在再导入项目内部模块（确保一定命中 /data/trading-ci/libs）
# ---------------------------------------------------------------------
from libs.common.config import settings  # noqa: E402
from libs.mq.redis_streams import RedisStreamsClient  # noqa: E402


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
    允许通过环境变量覆盖 streams：
    TRADING_CI_STREAMS="stream:a,stream:b"
    """
    v = os.environ.get("TRADING_CI_STREAMS", "").strip()
    if not v:
        return DEFAULT_STREAMS
    parts = [p.strip() for p in v.split(",") if p.strip()]
    return parts or DEFAULT_STREAMS


def _redis_wait_ready(redis_url: str, *, timeout_sec: int = 60, interval_sec: float = 1.0) -> None:
    """等待 Redis ready（容器启动时常见竞态，必须重试）。"""
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


def main() -> None:
    # 打印 debug，方便你确认到底导入的 libs 来自哪里
    try:
        import libs  # noqa
        libs_file = getattr(libs, "__file__", None)
        libs_path = getattr(libs, "__path__", None)
    except Exception as e:  # pragma: no cover
        libs_file = None
        libs_path = None

    print("=== trading-ci init_streams ===")
    print("python:", sys.executable)
    print("version:", sys.version.replace("\n", " "))
    print("cwd:", os.getcwd())
    print("project_root:", PROJECT_ROOT_STR)
    print("sys.path[0:5]:", sys.path[:5])
    print("libs.__file__:", libs_file)
    print("libs.__path__:", list(libs_path) if libs_path else None)

    redis_url = settings.redis_url
    group = settings.redis_stream_group
    streams = _get_streams()

    print("redis_url:", redis_url)
    print("group:", group)
    print("streams:", streams)

    _redis_wait_ready(redis_url, timeout_sec=int(os.environ.get("REDIS_WAIT_TIMEOUT", "60")))

    client = RedisStreamsClient(redis_url)
    for s in streams:
        client.ensure_group(s, group)

    print("OK: init_streams done")
    print("===============================")


if __name__ == "__main__":
    main()
