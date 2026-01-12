# -*- coding: utf-8 -*-
"""
notifier-service 入口（Phase 4）

- 使用 FastAPI lifespan（避免 on_event DeprecationWarning）
- 将 notifier 的两个异步循环放到独立线程运行（避免 redis 同步阻塞卡死 uvicorn）
"""

from __future__ import annotations

import asyncio
import threading
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient
from services.notifier.worker import run_notifier_stream_consumer, run_retry_loop

SERVICE_NAME = "notifier-service"
logger = setup_logging(SERVICE_NAME)

_worker_thread: threading.Thread | None = None


async def _run_all() -> None:
    await asyncio.gather(
        run_notifier_stream_consumer(),
        run_retry_loop(),
    )


def _run_worker_in_thread() -> None:
    try:
        asyncio.run(_run_all())
    except Exception:
        tb = traceback.format_exc()
        print(tb, flush=True)
        logger.error(
            "notifier_worker_crashed",
            extra={"extra_fields": {"event": "WORKER_CRASHED", "traceback": tb}},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_thread

    logger.info(
        "startup",
        extra={"extra_fields": {"event": "SERVICE_START", "env": getattr(settings, "env", "dev")}},
    )

    # 探活（不阻塞启动）
    try:
        RedisStreamsClient(settings.redis_url).r.ping()
    except Exception as e:
        logger.warning(
            f"redis_ping_failed: {e}",
            extra={"extra_fields": {"event": "REDIS_PING_FAILED", "error": str(e)}},
        )

    _worker_thread = threading.Thread(target=_run_worker_in_thread, name="notifier-worker", daemon=True)
    _worker_thread.start()

    yield

    logger.info("shutdown", extra={"extra_fields": {"event": "SERVICE_STOP"}})


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
def health():
    redis_ok = False
    try:
        RedisStreamsClient(settings.redis_url).r.ping()
        redis_ok = True
    except Exception:
        pass

    return {
        "env": getattr(settings, "env", "dev"),
        "service": SERVICE_NAME,
        "redis_ok": redis_ok,
        "telegram_enabled": bool(getattr(settings, "telegram_bot_token", "") and getattr(settings, "telegram_chat_id", "")),
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
