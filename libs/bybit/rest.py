"""Bybit REST 客户端（骨架，占位）"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class BybitRestClient:
    base_url: str
    api_key: str
    api_secret: str

    def health_ping(self) -> bool:
        return True
