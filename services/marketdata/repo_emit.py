# -*- coding: utf-8 -*-
"""bar_close 发射幂等记录（Stage 2）

做法：
- 在发布 bar_close 前，先向 bar_close_emits 预留一条记录（PK 冲突则说明已经发过）
- 如果发布失败，会 best-effort 回滚预留记录，避免“预留成功但没发出”导致永久丢事件

说明：
- 这是“实用型幂等”，不是严格的 outbox 事务一致性；
- 若你后续需要严格 exactly-once，可改为 outbox + relay。
"""

from __future__ import annotations

from typing import Optional

from libs.db.pg import get_conn

SQL_RESERVE = """
INSERT INTO bar_close_emits(symbol, timeframe, close_time_ms, event_id, source)
VALUES (%(s)s,%(tf)s,%(ct)s,%(eid)s,%(src)s)
ON CONFLICT (symbol, timeframe, close_time_ms) DO NOTHING;
"""

SQL_DELETE = """
DELETE FROM bar_close_emits WHERE symbol=%(s)s AND timeframe=%(tf)s AND close_time_ms=%(ct)s AND event_id=%(eid)s;
"""

SQL_LAST_CLOSE = """
SELECT close_time_ms FROM bars
WHERE symbol=%(s)s AND timeframe=%(tf)s AND close_time_ms < %(ct)s
ORDER BY close_time_ms DESC
LIMIT 1;
"""


def reserve_bar_close_emit(database_url: str, *, symbol: str, timeframe: str, close_time_ms: int, event_id: str, source: str) -> bool:
    """尝试预留一次发射；成功返回 True（允许发布），失败返回 False（已发过）。"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_RESERVE, {"s": symbol, "tf": timeframe, "ct": int(close_time_ms), "eid": event_id, "src": source})
            conn.commit()
            return cur.rowcount == 1


def rollback_bar_close_emit(database_url: str, *, symbol: str, timeframe: str, close_time_ms: int, event_id: str) -> None:
    """发布失败时 best-effort 回滚预留记录。"""
    try:
        with get_conn(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(SQL_DELETE, {"s": symbol, "tf": timeframe, "ct": int(close_time_ms), "eid": event_id})
                conn.commit()
    except Exception:
        return


def get_prev_close_time_ms(database_url: str, *, symbol: str, timeframe: str, before_close_time_ms: int) -> Optional[int]:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_LAST_CLOSE, {"s": symbol, "tf": timeframe, "ct": int(before_close_time_ms)})
            row = cur.fetchone()
    if not row:
        return None
    return int(row[0])
