"""结构化日志（JSON）

说明：
- 统一输出字段：ts_ms、level、service、event、trace_id（如有）、以及业务键。
- Phase 0 采用轻量 JSON formatter，后续可替换为更强的日志框架。
"""

from __future__ import annotations
import json
import logging
import sys
import time
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts_ms": int(time.time() * 1000),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            payload.update(record.extra_fields)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(service_name: str) -> logging.LoggerAdapter:
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    if not logger.handlers:
        logger.addHandler(handler)

    return logging.LoggerAdapter(logger, {"extra_fields": {"service": service_name}})
