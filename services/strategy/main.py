# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient
from services.strategy.worker import run_strategy

SERVICE_NAME = "strategy-service"
logger = setup_logging(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "startup",
        extra={"extra_fields": {"event": "SERVICE_START", "env": settings.env}},
    )

    try:
        RedisStreamsClient(settings.redis_url).r.ping()
    except Exception as e:
        logger.warning(
            "redis_ping_failed",
            extra={"extra_fields": {"event": "REDIS_PING_FAILED", "error": str(e)}},
        )

    app.state.bg_task = asyncio.create_task(run_strategy())
    yield

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
        "db_url_present": bool(settings.database_url),
    }


def main():
    # ✅ 关键：必须 0.0.0.0 才能被 docker 端口映射访问
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
