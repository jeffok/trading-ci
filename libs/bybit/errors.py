# -*- coding: utf-8 -*-
"""Bybit 返回码与可重试错误判定（Phase 6）

说明：本项目采用“保守可重试集合”：
- HTTP 429 / 5xx / 408
- retMsg/retCode 表现为系统繁忙、超时、频率限制等（字符串匹配）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from libs.common.time import now_ms


@dataclass
class BybitError(Exception):
    http_status: Optional[int]
    ret_code: Optional[int]
    ret_msg: str
    raw: Dict[str, Any]

    def __str__(self) -> str:
        return f"BybitError(http={self.http_status}, retCode={self.ret_code}, msg={self.ret_msg})"


def is_rate_limit_error(exc: Exception) -> bool:
    """Return True if the exception looks like a rate-limit (retCode=10006 or HTTP 429)."""
    if isinstance(exc, BybitError):
        if exc.http_status == 429:
            return True
        if exc.ret_code == 10006:
            return True
    return False


def extract_retry_after_ms(exc: Exception, *, default_ms: int = 1500) -> Optional[int]:
    """Best-effort retry-after extractor.

    Bybit sometimes returns reset timestamp in `retExtInfo` or other keys.
    We try to find a reasonable reset_ts and return milliseconds until reset.
    """
    if not isinstance(exc, BybitError):
        return None

    raw = exc.raw or {}
    # headers may be injected by the REST client under `_headers`
    headers = {}
    try:
        maybe = raw.get("_headers")
        if isinstance(maybe, dict):
            headers = maybe
    except Exception:
        headers = {}

    # RFC: Retry-After (seconds)
    try:
        ra = headers.get("retry-after") or headers.get("Retry-After")
        if ra is not None:
            sec = int(float(ra))
            return int(min(60_000, max(250, sec * 1000)))
    except Exception:
        pass

    # Bybit reset timestamp header (epoch ms)
    try:
        rst = headers.get("x-bapi-limit-reset-timestamp") or headers.get("X-Bapi-Limit-Reset-Timestamp")
        if rst is not None:
            n = int(float(rst))
            if n < 10_000_000_000:
                n = n * 1000
            delta = int(n - now_ms())
            if delta > 0:
                return int(min(60_000, max(250, delta)))
    except Exception:
        pass
    candidates = []
    # common places seen in Bybit payloads
    for path in (
        ("retExtInfo", "rateLimitResetTime"),
        ("retExtInfo", "rateLimitResetTimestamp"),
        ("retExtInfo", "rateLimitReset"),
        ("rateLimitResetTime",),
        ("rateLimitResetTimestamp",),
    ):
        cur: Any = raw
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok:
            candidates.append(cur)

    reset_ts_ms: Optional[int] = None
    for v in candidates:
        try:
            n = int(float(v))
        except Exception:
            continue
        # heuristics: if it's seconds epoch
        if n < 10_000_000_000:
            n = n * 1000
        if n > 0:
            reset_ts_ms = n
            break

    if reset_ts_ms is None:
        return int(default_ms)

    delta = int(reset_ts_ms - now_ms())
    if delta <= 0:
        return int(default_ms)
    # clamp to sane bound
    return int(min(60_000, max(250, delta)))


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
