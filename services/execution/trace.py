# -*- coding: utf-8 -*-
"""execution-service Trace 便捷函数（Stage 4）

用法：在 executor 关键节点调用 trace_step() 记录结构化 trace。
要求：
- 任何 trace 失败不能影响交易执行
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict

from libs.common.time import now_ms
from services.execution.repo import insert_execution_trace


def trace_step(database_url: str, *, trace_id: str, idempotency_key: str, stage: str, detail: Dict[str, Any]) -> None:
    """写一条 trace 记录。trace_row_id 使用哈希，避免重复写入。"""
    try:
        ts = now_ms()
        row = hashlib.sha256(f"{trace_id}|{idempotency_key}|{stage}|{ts}".encode("utf-8")).hexdigest()
        insert_execution_trace(
            database_url,
            trace_row_id=row,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            ts_ms=ts,
            stage=stage,
            detail=detail,
        )
    except Exception:
        return
