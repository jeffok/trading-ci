# -*- coding: utf-8 -*-
"""通用重试工具（Phase 6）

目标：提高实盘稳定性（不改变策略）。
- 对网络抖动、429/5xx、交易所短暂异常做指数退避重试
- 默认最多重试 3 次，退避 0.5s -> 1s -> 2s（加少量 jitter）
"""

from __future__ import annotations

import random
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


def retry_call(
    fn: Callable[[], T],
    *,
    retry_if: Callable[[Exception], bool],
    max_attempts: int = 3,
    base_delay_sec: float = 0.5,
    max_delay_sec: float = 5.0,
) -> T:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt >= max_attempts or not retry_if(e):
                raise
            delay = min(max_delay_sec, base_delay_sec * (2 ** (attempt - 1)))
            delay = delay * (0.9 + random.random() * 0.2)  # jitter 0.9~1.1
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc
