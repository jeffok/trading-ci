# -*- coding: utf-8 -*-
"""notifier-service 入口（Phase 4）"""

from __future__ import annotations

import asyncio
from fastapi import FastAPI
import uvicorn

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient
from services.notifier.worker import run_notifier_stream_consumer, run_retry_loop

SERVICE_NAME = "notifier-service"
logger = setup_logging(SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)
_bg_task: asyncio.Task | None = None

async def run_notifier() -> None:
    """Run notifier background loops concurrently."""
    await asyncio.gather(
        run_notifier_stream_consumer(),
        run_retry_loop(),
    )



@app.on_event("startup")
async def _startup():
    global _bg_task
    logger.info("startup", extra={"extra_fields": {"event":"SERVICE_START","env": settings.env}})
    _bg_task = asyncio.create_task(run_notifier())


@app.on_event("shutdown")
async def _shutdown():
    global _bg_task
    if _bg_task:
        _bg_task.cancel()


@app.get("/health")
def health():
    redis_ok = False
    try:
        RedisStreamsClient(settings.redis_url).r.ping()
        redis_ok = True
    except Exception:
        pass
    return {
        "env": settings.env,
        "service": SERVICE_NAME,
        "redis_ok": redis_ok,
        "telegram_enabled": bool(settings.telegram_bot_token and settings.telegram_chat_id),
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()