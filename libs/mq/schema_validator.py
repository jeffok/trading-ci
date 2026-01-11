"""JSON Schema 校验器（契约优先）"""
from __future__ import annotations
import json, os
from functools import lru_cache
from typing import Any, Dict
from jsonschema import Draft202012Validator

SCHEMA_ROOT = os.path.join(os.path.dirname(__file__), "..", "schemas")

@lru_cache(maxsize=128)
def _load_schema(schema_path: str) -> Dict[str, Any]:
    full = os.path.join(SCHEMA_ROOT, schema_path)
    with open(full, "r", encoding="utf-8") as f:
        return json.load(f)

@lru_cache(maxsize=128)
def _validator(schema_path: str) -> Draft202012Validator:
    return Draft202012Validator(_load_schema(schema_path))

def validate(schema_path: str, obj: Dict[str, Any]) -> None:
    _validator(schema_path).validate(obj)
