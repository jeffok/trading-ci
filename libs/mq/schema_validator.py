"""JSON Schema 校验器（契约优先）"""
from __future__ import annotations
import json, os
from functools import lru_cache
from typing import Any, Dict
from jsonschema import Draft202012Validator, RefResolver

SCHEMA_ROOT = os.path.join(os.path.dirname(__file__), "..", "schemas")
SCHEMA_BASE_URI = "https://schemas.local/"

def _load_all_schemas() -> Dict[str, Dict[str, Any]]:
    """加载所有 schema 文件到内存，用于构建 resolver"""
    schemas = {}
    for root, dirs, files in os.walk(SCHEMA_ROOT):
        for file in files:
            if file.endswith(".json"):
                rel_path = os.path.relpath(os.path.join(root, file), SCHEMA_ROOT)
                # 转换为 URL 路径格式（使用 / 而不是 \）
                url_path = rel_path.replace("\\", "/")
                full_path = os.path.join(root, file)
                with open(full_path, "r", encoding="utf-8") as f:
                    schema = json.load(f)
                    # 使用 schema 的 $id 或构造 URL
                    schema_id = schema.get("$id", f"{SCHEMA_BASE_URI}{url_path}")
                    schemas[schema_id] = schema
    return schemas

@lru_cache(maxsize=128)
def _load_schema(schema_path: str) -> Dict[str, Any]:
    full = os.path.join(SCHEMA_ROOT, schema_path)
    with open(full, "r", encoding="utf-8") as f:
        return json.load(f)

def _create_resolver(schema: Dict[str, Any]) -> RefResolver:
    """创建 RefResolver，将所有 https://schemas.local/ 引用映射到本地文件"""
    schemas = _load_all_schemas()
    
    # 创建 store，包含所有本地 schema
    store = {}
    for schema_id, schema_data in schemas.items():
        store[schema_id] = schema_data
    
    # 创建 resolver，base_uri 使用 schema 的 $id 或默认值
    base_uri = schema.get("$id", SCHEMA_BASE_URI)
    return RefResolver(base_uri=base_uri, referrer=schema, store=store)

@lru_cache(maxsize=128)
def _validator(schema_path: str) -> Draft202012Validator:
    schema = _load_schema(schema_path)
    resolver = _create_resolver(schema)
    return Draft202012Validator(schema, resolver=resolver)

def validate(schema_path: str, obj: Dict[str, Any]) -> None:
    _validator(schema_path).validate(obj)
