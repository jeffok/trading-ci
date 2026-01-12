# -*- coding: utf-8 -*-
"""Telegram 通知（可选）

如果不配置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，notifier 只记录日志，不发送网络请求。

注意：
- 本模块使用 urllib，避免引入额外依赖。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional


def send_telegram(*, bot_token: str, chat_id: str, text: str) -> None:
    if not bot_token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
