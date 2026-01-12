# -*- coding: utf-8 -*-
"""Bybit V5 鉴权签名（HMAC_SHA256）

Bybit 官方文档（V5 Integration Guidance）给出的签名拼接规则：
- GET:  timestamp + api_key + recv_window + queryString
- POST: timestamp + api_key + recv_window + jsonBodyString

然后对拼接字符串做 HMAC_SHA256(secret, prehash) 并输出 hex (lowercase)。

注意：
- timestamp 需为毫秒字符串
- jsonBodyString 必须是**你最终发出去的 body** 的字符串形式（建议用 `json.dumps(..., separators=(',', ':'))` 保持紧凑一致）
"""

from __future__ import annotations

import hmac
import hashlib
from typing import Dict


def sign_hmac_sha256(secret: str, prehash: str) -> str:
    """返回小写 hex 签名"""
    return hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).hexdigest()


def build_auth_headers(*, api_key: str, api_secret: str, timestamp_ms: str, recv_window: str, signature: str) -> Dict[str, str]:
    """Bybit V5 需要的 HTTP Headers"""
    return {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-TIMESTAMP": timestamp_ms,
        "X-BAPI-RECV-WINDOW": recv_window,
        "X-BAPI-SIGN": signature,
        "Content-Type": "application/json",
    }
