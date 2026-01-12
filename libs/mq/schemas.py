"""Schema constants for stream events.

Execution/Strategy services expect to import schema dicts from here.

Schemas are stored as JSON files under `libs/schemas/`.
"""

from __future__ import annotations

from typing import Any, Dict

from libs.mq.schema_validator import _load_schema  # internal cached loader

# Stream schemas
TRADE_PLAN_SCHEMA: Dict[str, Any] = _load_schema("streams/trade-plan.json")
BAR_CLOSE_SCHEMA: Dict[str, Any] = _load_schema("streams/bar-close.json")
SIGNAL_SCHEMA: Dict[str, Any] = _load_schema("streams/signal.json")
EXECUTION_REPORT_SCHEMA: Dict[str, Any] = _load_schema("streams/execution-report.json")
RISK_EVENT_SCHEMA: Dict[str, Any] = _load_schema("streams/risk-event.json")

__all__ = [
    "TRADE_PLAN_SCHEMA",
    "BAR_CLOSE_SCHEMA",
    "SIGNAL_SCHEMA",
    "EXECUTION_REPORT_SCHEMA",
    "RISK_EVENT_SCHEMA",
]
