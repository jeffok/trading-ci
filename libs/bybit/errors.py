# -*- coding: utf-8 -*-
"""Bybit 返回码与可重试错误判定（Phase 6）

说明：本项目采用“保守可重试集合”：
- HTTP 429 / 5xx / 408
- retMsg/retCode 表现为系统繁忙、超时、频率限制等（字符串匹配）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class BybitError(Exception):
    http_status: Optional[int]
    ret_code: Optional[int]
    ret_msg: str
    raw: Dict[str, Any]

    def __str__(self) -> str:
        return f"BybitError(http={self.http_status}, retCode={self.ret_code}, msg={self.ret_msg})"


def is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, BybitError):
        if exc.http_status in (408, 429, 500, 502, 503, 504):
            return True
        msg = (exc.ret_msg or "").lower()
        if any(k in msg for k in ["too many", "rate", "limit", "busy", "timeout", "tempor", "system"]):
            return True
        if exc.ret_code in (10006, 10018):  # 经验值：常见 rate limit / system busy
            return True
        return False

    s = str(exc).lower()
    if any(k in s for k in ["timed out", "timeout", "tempor", "connection", "reset", "429", "502", "503", "504"]):
        return True
    return False
