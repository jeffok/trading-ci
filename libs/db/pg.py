"""Postgres 访问层（极简 psycopg3）"""
from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator
import psycopg

@contextmanager
def get_conn(database_url: str) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()
