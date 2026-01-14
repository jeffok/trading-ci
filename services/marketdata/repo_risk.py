# -*- coding: utf-8 -*-
"""risk_events 落库（Stage 2）

复用 Phase 6 的 risk_events 表：让数据缺口/回填等质量事件可追溯。
"""

from __future__ import annotations

from typing import Any, Dict

from libs.db.pg import get_conn
from libs.common.json import dumps_json
from libs.mq.risk_normalize import normalize_risk_type, normalize_risk_severity


SQL_INSERT = """
INSERT INTO risk_events(event_id, trade_date, ts_ms, type, severity, detail, symbol, retry_after_ms, ext)
VALUES (%(id)s,%(d)s,%(ts)s,%(t)s,%(s)s,%(detail)s::jsonb,%(symbol)s,%(retry_after_ms)s,%(ext)s::jsonb);
"""


def insert_risk_event(database_url: str, *, event_id: str, trade_date: str, ts_ms: int, typ: str, severity: str, detail: Dict[str, Any], symbol: str | None = None, retry_after_ms: int | None = None, ext: Dict[str, Any] | None = None) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_INSERT, {
                "id": event_id,
                "d": trade_date,
                "ts": int(ts_ms),
                "t": normalize_risk_type(typ),
                "s": normalize_risk_severity(severity),
                "detail": dumps_json(detail),
                "symbol": symbol,
                "retry_after_ms": int(retry_after_ms) if retry_after_ms is not None else None,
                "ext": dumps_json(ext or {}),
            })
            conn.commit()
