# -*- coding: utf-8 -*-
"""risk_events 落库（Stage 2）

复用 Phase 6 的 risk_events 表：让数据缺口/回填等质量事件可追溯。
"""

from __future__ import annotations

from typing import Any, Dict

from libs.db.pg import get_conn
from libs.common.json import dumps_json


SQL_INSERT = """
INSERT INTO risk_events(event_id, trade_date, ts_ms, type, severity, detail)
VALUES (%(id)s,%(d)s,%(ts)s,%(t)s,%(s)s,%(detail)s::jsonb);
"""


def insert_risk_event(database_url: str, *, event_id: str, trade_date: str, ts_ms: int, typ: str, severity: str, detail: Dict[str, Any]) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_INSERT, {"id": event_id, "d": trade_date, "ts": int(ts_ms), "t": typ, "s": severity, "detail": dumps_json(detail)})
            conn.commit()
