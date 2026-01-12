# -*- coding: utf-8 -*-
"""execution-service 入口（Phase 3/4）

新增：后台 worker
- trade_plan consumer
- bar_close consumer（Phase 4）
"""

from __future__ import annotations

import asyncio
from fastapi import FastAPI
import uvicorn

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient
from services.execution.worker import run_execution

SERVICE_NAME = "execution-service"
logger = setup_logging(SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)
_bg_task: asyncio.Task | None = None


@app.on_event("startup")
async def _startup():
    global _bg_task
    logger.info("startup", extra={"extra_fields": {"event":"SERVICE_START","env": settings.env, "mode": settings.execution_mode}})
    try:
        RedisStreamsClient(settings.redis_url).r.ping()
    except Exception as e:
        logger.warning("redis_ping_failed", extra={"extra_fields": {"event":"REDIS_PING_FAILED","error": str(e)}})

    _bg_task = asyncio.create_task(run_execution())


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
        "execution_mode": settings.execution_mode,
        "bybit_rest_base_url": settings.bybit_rest_base_url,
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
