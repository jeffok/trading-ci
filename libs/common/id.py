"""ID 工具：event_id / trace_id"""
from __future__ import annotations
import uuid

def new_event_id() -> str:
    return uuid.uuid4().hex

def new_trace_id() -> str:
    return uuid.uuid4().hex
