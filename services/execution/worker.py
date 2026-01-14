# -*- coding: utf-8 -*-
"""execution-service worker

职责：
- 消费 stream:trade_plan -> execute_trade_plan（下单/落库/回报）
- 消费 stream:bar_close -> 生命周期维护（runner trailing / 次日规则） + paper/backtest 撮合模拟
- 后台：reconcile / 风控监控 / 持仓同步 / 资金快照

原则：
- 避免毒消息卡死：异常记录并 ack，同时通过 risk_event 事件化。
"""

from __future__ import annotations

import asyncio
import traceback

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.common.time import now_ms
from libs.mq.redis_streams import RedisStreamsClient
from libs.mq.schemas import TRADE_PLAN_SCHEMA, BAR_CLOSE_SCHEMA

from services.execution.executor import execute_trade_plan
from services.execution.lifecycle import on_bar_close
from services.execution.paper_sim import process_paper_bar_close
from services.execution.reconcile import run_reconcile_once
from services.execution.ws_private_ingest import run_private_ws_ingest_loop
from services.execution.risk_monitor import run_risk_monitor_once
from services.execution.position_sync import sync_positions
from services.execution.snapshotter import run_snapshot_loop
from services.execution.publisher import build_risk_event, publish_risk_event

logger = setup_logging("execution-service")


def _parse(fields: dict, schema: dict) -> dict:
    """将扁平字段还原为 event dict。"""
    if "json" in fields:
        import json
        return json.loads(fields["json"])
    if "data" in fields:
        import json
        return json.loads(fields["data"])
    return fields


async def run_trade_plan_consumer() -> None:
    client = RedisStreamsClient(settings.redis_url)
    client.ensure_group("stream:trade_plan", settings.redis_stream_group)
    consumer = f"{settings.redis_stream_consumer}-tradeplan"

    while True:
        msgs = client.read_group("stream:trade_plan", settings.redis_stream_group, consumer, count=20, block_ms=2000)
        if not msgs:
            continue

        for m in msgs:
            try:
                evt = _parse(m.fields, TRADE_PLAN_SCHEMA)

                # 延迟告警
                if settings.alert_stream_lag_enabled:
                    try:
                        lag = int(now_ms() - int(evt.get("ts_ms", 0)))
                        if lag > int(settings.alert_trade_plan_lag_ms):
                            ev = build_risk_event(
                                typ="PROCESSING_LAG",
                                severity="IMPORTANT",
                                symbol=evt.get("payload", {}).get("symbol"),
                                detail={"stream": "stream:trade_plan", "lag_ms": lag, "message_id": m.message_id},
                                trace_id=evt.get("trace_id"),
                            )
                            publish_risk_event(settings.redis_url, ev)
                    except Exception:
                        pass

                execute_trade_plan(settings.database_url, settings.redis_url, trade_plan_event=evt)

            except Exception as e:
                tb = traceback.format_exc()
                # ✅ 关键：直接打印堆栈，docker logs 必然可见
                print(tb, flush=True)
                # ✅ 关键：把 error 拼进 message（你当前日志格式不显示 extra_fields）
                # 防止错误消息中包含未转义的格式化字符串
                error_str = str(e).replace("{", "{{").replace("}", "}}")
                logger.warning(f"trade_plan_process_failed: {error_str}", extra={"extra_fields": {"event": "TRADE_PLAN_FAILED", "error": str(e)}})

                try:
                    ev = build_risk_event(
                        typ="TRADE_PLAN_FAILED",
                        severity="IMPORTANT",
                        symbol=None,
                        detail={"where": "execution-service", "error": str(e), "message_id": m.message_id},
                    )
                    publish_risk_event(settings.redis_url, ev)
                except Exception:
                    pass
            finally:
                client.ack(m.stream, settings.redis_stream_group, m.message_id)


async def run_bar_close_consumer() -> None:
    client = RedisStreamsClient(settings.redis_url)
    client.ensure_group("stream:bar_close", settings.redis_stream_group)
    consumer = f"{settings.redis_stream_consumer}-barclose"

    while True:
        msgs = client.read_group("stream:bar_close", settings.redis_stream_group, consumer, count=200, block_ms=2000)
        if not msgs:
            continue

        for m in msgs:
            try:
                evt = _parse(m.fields, BAR_CLOSE_SCHEMA)

                if settings.alert_stream_lag_enabled:
                    try:
                        lag = int(now_ms() - int(evt.get("ts_ms", 0)))
                        if lag > int(settings.alert_bar_close_lag_ms):
                            ev = build_risk_event(
                                typ="PROCESSING_LAG",
                                severity="INFO",
                                symbol=evt.get("payload", {}).get("symbol"),
                                detail={"stream": "stream:bar_close", "lag_ms": lag, "message_id": m.message_id},
                                trace_id=evt.get("trace_id"),
                            )
                            publish_risk_event(settings.redis_url, ev)
                    except Exception:
                        pass

                on_bar_close(settings.database_url, settings.redis_url, bar_close_event=evt)

                if str(settings.execution_mode).upper() in ("PAPER", "BACKTEST"):
                    process_paper_bar_close(database_url=settings.database_url, redis_url=settings.redis_url, bar_close_event=evt)

            except Exception as e:
                tb = traceback.format_exc()
                print(tb, flush=True)
                logger.warning(f"bar_close_process_failed: {e}", extra={"extra_fields": {"event": "BAR_CLOSE_FAILED", "error": str(e)}})
                try:
                    ev = build_risk_event(
                        typ="BAR_CLOSE_FAILED",
                        severity="INFO",
                        symbol=None,
                        detail={"where": "execution-service", "error": str(e), "message_id": m.message_id},
                    )
                    publish_risk_event(settings.redis_url, ev)
                except Exception:
                    pass
            finally:
                client.ack(m.stream, settings.redis_stream_group, m.message_id)


async def run_reconcile_loop() -> None:
    while True:
        try:
            run_reconcile_once(settings.database_url, settings.redis_url)
        except Exception as e:
            logger.warning(f"reconcile_failed: {e}", extra={"extra_fields": {"event": "RECONCILE_FAILED", "error": str(e)}})
        await asyncio.sleep(5.0)


async def run_risk_monitor_loop() -> None:
    while True:
        try:
            run_risk_monitor_once(settings.database_url, settings.redis_url)
        except Exception as e:
            logger.warning(f"risk_monitor_failed: {e}", extra={"extra_fields": {"event": "RISK_MONITOR_FAILED", "error": str(e)}})
        await asyncio.sleep(float(settings.risk_monitor_interval_sec))


async def run_position_sync_loop() -> None:
    while True:
        try:
            sync_positions(settings.database_url, settings.redis_url)
        except Exception as e:
            logger.warning(f"position_sync_failed: {e}", extra={"extra_fields": {"event": "POSITION_SYNC_FAILED", "error": str(e)}})
        await asyncio.sleep(10.0)


async def run_execution() -> None:
    await asyncio.gather(
        run_trade_plan_consumer(),
        run_bar_close_consumer(),
        run_reconcile_loop(),
        run_risk_monitor_loop(),
        run_position_sync_loop(),
        run_snapshot_loop(),
        run_private_ws_ingest_loop(),
    )
