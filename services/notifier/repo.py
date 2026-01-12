# -*- coding: utf-8 -*-
"""notifier-service DB 持久化（Stage 3）

目标：
- 通知幂等：同一 event_id 只发送一次
- 通知状态可追溯：PENDING/SENT/FAILED，记录 attempts/last_error
- 提供重试：失败后按指数退避计划下次重试时间 next_attempt_at

说明：
- 我们以 event_id 作为 notification_id（主键），天然实现幂等。
- worker 对 Redis Stream 消息：无论发送成功与否都 ACK（避免重复消费造成风暴）。
- 失败时由“重试循环”负责再尝试发送（由 DB 驱动）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import datetime
import json

from libs.db.pg import get_conn


SQL_UPSERT = """
INSERT INTO notifications(notification_id, stream, message_id, schema, severity, text, status, attempts, next_attempt_at, last_error, meta)
VALUES (%(id)s,%(stream)s,%(mid)s,%(schema)s,%(sev)s,%(text)s,%(status)s,%(attempts)s,%(next)s,%(err)s,%(meta)s::jsonb)
ON CONFLICT (notification_id) DO NOTHING;
"""

SQL_MARK_SENT = """
UPDATE notifications
SET status='SENT', sent_at=now(), last_error=NULL
WHERE notification_id=%(id)s;
"""

SQL_MARK_FAILED = """
UPDATE notifications
SET status='FAILED', attempts=%(attempts)s, next_attempt_at=%(next)s, last_error=%(err)s
WHERE notification_id=%(id)s;
"""

SQL_GET = """
SELECT notification_id, status, attempts FROM notifications WHERE notification_id=%(id)s;
"""

SQL_DUE = """
SELECT notification_id, severity, text, attempts
FROM notifications
WHERE status='FAILED' AND next_attempt_at IS NOT NULL AND next_attempt_at <= now() AND attempts < %(max)s
ORDER BY next_attempt_at ASC
LIMIT %(limit)s;
"""


def insert_notification_if_absent(database_url: str, *, notification_id: str, stream: str, message_id: str,
                                 schema: str, severity: str, text: str, meta: Dict[str, Any]) -> None:
    """插入通知记录（幂等）。"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_UPSERT, {
                "id": notification_id,
                "stream": stream,
                "mid": message_id,
                "schema": schema,
                "sev": severity,
                "text": text,
                "status": "PENDING",
                "attempts": 0,
                "next": None,
                "err": None,
                "meta": json.dumps(meta, ensure_ascii=False),
            })
            conn.commit()


def get_notification(database_url: str, *, notification_id: str) -> Optional[Dict[str, Any]]:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_GET, {"id": notification_id})
            row = cur.fetchone()
    if not row:
        return None
    return {"notification_id": row[0], "status": row[1], "attempts": int(row[2])}


def mark_sent(database_url: str, *, notification_id: str) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_MARK_SENT, {"id": notification_id})
            conn.commit()


def mark_failed(database_url: str, *, notification_id: str, attempts: int, next_attempt_at: datetime.datetime, last_error: str) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_MARK_FAILED, {"id": notification_id, "attempts": int(attempts), "next": next_attempt_at, "err": last_error})
            conn.commit()


def list_due_failed(database_url: str, *, max_attempts: int, limit: int = 20) -> List[Dict[str, Any]]:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_DUE, {"max": int(max_attempts), "limit": int(limit)})
            cols = [d[0] for d in cur.description]
            out = []
            for r in cur.fetchall():
                out.append(dict(zip(cols, r)))
            return out


def backoff_seconds(attempts: int) -> int:
    """指数退避：1,2,4,8,16... 上限 300s。"""
    s = 2 ** max(0, attempts - 1)
    return int(min(300, s))
