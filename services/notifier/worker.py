# -*- coding: utf-8 -*-
"""notifier-service worker（Phase 4）

消费：
- stream:execution_report
- stream:risk_event

动作：
- 记录日志
- 可选：Telegram 推送（紧急/重要级别优先）
"""

from __future__ import annotations

import asyncio
import json
import datetime
from typing import Any, Dict

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient
from libs.mq.schema_validator import validate
from libs.mq.dlq import publish_dlq

from services.notifier.repo import (
    insert_notification_if_absent,
    get_notification,
    mark_sent,
    mark_failed,
    list_due_failed,
    backoff_seconds,
)
from services.notifier.telegram import send_telegram

logger = setup_logging("notifier-service")

STREAM_EXEC_REPORT = "stream:execution_report"
STREAM_RISK = "stream:risk_event"

EXEC_REPORT_SCHEMA = "streams/execution-report.json"
RISK_EVENT_SCHEMA = "streams/risk-event.json"


def _parse(fields: Dict[str, Any], schema: str) -> Dict[str, Any]:
    """
    兼容两种发布格式：
    - 新格式：fields["json"] 是 JSON string
    - 旧格式：fields["data"] 是 JSON string
    """
    raw = None
    if "json" in fields:
        raw = fields["json"]
    elif "data" in fields:
        raw = fields["data"]

    if raw is None:
        raise ValueError("missing field 'json' (or legacy 'data')")

    obj = json.loads(raw)
    validate(schema, obj)
    return obj


def _maybe_notify(text: str, severity: str) -> bool:
    # 只对 IMPORTANT/EMERGENCY 推送（可按需调整）
    if severity not in ("IMPORTANT", "EMERGENCY"):
        return False
    send_telegram(bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id, text=text)
    return True


async def run_notifier_stream_consumer() -> None:
    client = RedisStreamsClient(settings.redis_url)
    client.ensure_group(STREAM_EXEC_REPORT, settings.redis_stream_group)
    client.ensure_group(STREAM_RISK, settings.redis_stream_group)

    while True:
        for stream, schema in [(STREAM_EXEC_REPORT, EXEC_REPORT_SCHEMA), (STREAM_RISK, RISK_EVENT_SCHEMA)]:
            msgs = client.read_group(
                stream,
                settings.redis_stream_group,
                settings.redis_stream_consumer,
                count=20,
                block_ms=500,
            )
            if not msgs:
                continue

            for m in msgs:
                try:
                    evt = _parse(m.fields, schema)
                    payload = evt.get("payload", {})
                    sev = payload.get("severity") or payload.get("type") or "INFO"
                    text = json.dumps(payload, ensure_ascii=False)

                    logger.info("notify_event", extra={"extra_fields": {"stream": stream, "payload": payload}})

                    notification_id = evt.get("event_id") or evt.get("report_id") or evt.get("id") or m.message_id
                    notification_id = str(notification_id)

                    # 落库（幂等）
                    try:
                        insert_notification_if_absent(
                            settings.database_url,
                            notification_id=notification_id,
                            stream=stream,
                            message_id=m.message_id,
                            schema=schema,
                            severity=str(sev),
                            text=text,
                            meta={"source": "stream_consume"},
                        )
                    except Exception:
                        pass

                    st = None
                    try:
                        st = get_notification(settings.database_url, notification_id=notification_id)
                    except Exception:
                        st = None

                    if st and st.get("status") == "SENT":
                        client.ack(m.stream, settings.redis_stream_group, m.message_id)
                        continue

                    ok = False
                    err = "send_failed"
                    try:
                        ok = _maybe_notify(text=text, severity=str(sev))
                    except Exception as e:
                        ok = False
                        err = str(e)

                    if ok:
                        try:
                            mark_sent(settings.database_url, notification_id=notification_id)
                        except Exception:
                            pass
                    else:
                        try:
                            attempts = int(st.get("attempts", 0) if st else 0) + 1
                            delay = backoff_seconds(attempts)
                            nxt = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay)
                            mark_failed(
                                settings.database_url,
                                notification_id=notification_id,
                                attempts=attempts,
                                next_attempt_at=nxt,
                                last_error=err,
                            )
                        except Exception:
                            pass

                    client.ack(m.stream, settings.redis_stream_group, m.message_id)

                except Exception as e:
                    try:
                        publish_dlq(
                            settings.redis_url,
                            source_stream=stream,
                            message_id=m.message_id,
                            reason=str(e),
                            raw_fields=m.fields,
                        )
                    except Exception:
                        pass
                    logger.warning(f"notify_failed: {e}", extra={"extra_fields": {"stream": stream, "error": str(e)}})
                    client.ack(m.stream, settings.redis_stream_group, m.message_id)

        await asyncio.sleep(0.1)


async def run_retry_loop() -> None:
    """失败通知重试循环（DB 驱动）。"""
    while True:
        try:
            due = list_due_failed(
                settings.database_url,
                max_attempts=int(settings.notifier_max_attempts),
                limit=20,
            )
            for row in due:
                nid = str(row["notification_id"])
                sev = row["severity"]
                text = row["text"]
                attempts = int(row["attempts"]) + 1

                ok = False
                err = "send_failed"
                try:
                    ok = _maybe_notify(text=text, severity=str(sev))
                except Exception as e:
                    ok = False
                    err = str(e)

                if ok:
                    try:
                        mark_sent(settings.database_url, notification_id=nid)
                    except Exception:
                        pass
                else:
                    delay = backoff_seconds(attempts)
                    nxt = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay)
                    try:
                        mark_failed(settings.database_url, notification_id=nid, attempts=attempts, next_attempt_at=nxt, last_error=err)
                    except Exception:
                        pass
        except Exception:
            pass

        await asyncio.sleep(float(settings.notifier_retry_loop_interval_sec))
