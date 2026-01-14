# -*- coding: utf-8 -*-
"""Stage 11: simple account kill switch gate.

Goal:
- When kill switch is ON, block *new entries* (trade_plans) without changing strategy.
- Still allows exits / reduce-only operations (not handled here; executor will call this gate before entry).

Sources of truth:
1) ENV: ACCOUNT_KILL_SWITCH_FORCE_ON=true
2) DB runtime_flags: name=KILL_SWITCH (configurable) value in ('1','true','on','yes')

This module also provides a spam-safe notifier window decision.
"""

from __future__ import annotations

from typing import Optional, Tuple

from libs.common.config import settings
from libs.common.time import now_ms
from services.execution.repo import get_runtime_flag


def _truthy(v: str) -> bool:
    s = (v or "").strip().lower()
    return s in ("1", "true", "on", "yes", "y")


def is_kill_switch_on(*, database_url: str) -> Tuple[bool, Optional[str]]:
    if bool(getattr(settings, "account_kill_switch_force_on", False)):
        return True, "FORCE_ON"
    flag_name = str(getattr(settings, "kill_switch_flag_name", "KILL_SWITCH"))
    try:
        row = get_runtime_flag(database_url, name=flag_name)
    except Exception:
        row = None
    if row and _truthy(row.get("value", "")):
        return True, f"RUNTIME_FLAG:{flag_name}"
    return False, None


def should_emit_kill_switch_alert(*, last_emit_ms: Optional[int]) -> bool:
    win = int(getattr(settings, "kill_switch_window_ms", 300000))
    now = now_ms()
    if last_emit_ms is None:
        return True
    return (now - int(last_emit_ms)) >= win
