# -*- coding: utf-8 -*-
"""notifier-service 入口（Phase 4）

使用 FastAPI Lifespan 替代 on_event，避免 DeprecationWarning。
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient
from services.notifier.worker import run_notifier_stream_consumer, run_retry_loop

SERVICE_NAME = "notifier-service"
logger = setup_logging(SERVICE_NAME)


async def run_notifier() -> None:
    """Run notifier background loops concurrently."""
    await asyncio.gather(
        run_notifier_stream_consumer(),
        run_retry_loop(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    logger.info(
        "startup",
        extra={"extra_fields": {"event": "SERVICE_START", "env": settings.env}},
    )
    app.state.bg_task = asyncio.create_task(run_notifier())

    yield

    # --- shutdown ---
    task: asyncio.Task | None = getattr(app.state, "bg_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


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
        "env": settings.env,
        "service": SERVICE_NAME,
        "redis_ok": redis_ok,
        "telegram_enabled": bool(settings.telegram_bot_token and settings.telegram_chat_id),
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
