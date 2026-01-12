# -*- coding: utf-8 -*-
"""JSON 工具"""
from __future__ import annotations
import json
from typing import Any, Dict

def dumps_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
