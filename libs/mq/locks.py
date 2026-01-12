# -*- coding: utf-8 -*-
"""Redis 分布式锁（Stage 1）

用途：
- trade_plan 幂等锁：lock:plan:{idempotency_key}
- 避免重复消费/并发导致的重复下单窗口

实现：
- SET key value NX PX ttl_ms
- 解锁使用 Lua：只有持有同样 value 的客户端才能删除
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Optional

import redis


UNLOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
"""


@dataclass
class RedisLock:
    key: str
    token: str
    ttl_ms: int


def _client(redis_url: str) -> redis.Redis:
    return redis.Redis.from_url(redis_url, decode_responses=True)


def acquire_lock(redis_url: str, key: str, *, ttl_ms: int = 30_000) -> Optional[RedisLock]:
    """尝试获取锁，成功返回 RedisLock，失败返回 None。"""
    c = _client(redis_url)
    token = secrets.token_urlsafe(16)
    ok = c.set(name=key, value=token, nx=True, px=ttl_ms)
    if not ok:
        return None
    return RedisLock(key=key, token=token, ttl_ms=ttl_ms)


def release_lock(redis_url: str, lock: RedisLock) -> None:
    """释放锁（best-effort）。"""
    try:
        c = _client(redis_url)
        c.eval(UNLOCK_LUA, 1, lock.key, lock.token)
    except Exception:
        # 不影响主流程
        return
