"""时间工具：统一毫秒时间戳"""
from __future__ import annotations
import time

def now_ms() -> int:
    return int(time.time() * 1000)
