# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient
from services.execution.worker import run_execution

SERVICE_NAME = "execution-service"
logger = setup_logging(SERVICE_NAME)

_worker_thread: threading.Thread | None = None


def _run_worker_in_thread() -> None:
    try:
        asyncio.run(run_execution())
    except Exception as e:
        logger.exception("worker_crashed", extra={"extra_fields": {"event": "WORKER_CRASHED", "error": str(e)}})


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_thread
    logger.info("startup", extra={"extra_fields": {"event": "SERVICE_START", "env": settings.env, "mode": settings.execution_mode}})

    try:
        RedisStreamsClient(settings.redis_url).r.ping()
    except Exception as e:
        logger.warning("redis_ping_failed", extra={"extra_fields": {"event": "REDIS_PING_FAILED", "error": str(e)}})

    _worker_thread = threading.Thread(target=_run_worker_in_thread, name="execution-worker", daemon=True)
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
        "env": settings.env,
        "service": SERVICE_NAME,
        "redis_ok": redis_ok,
        "db_url_present": bool(settings.database_url),
        "execution_mode": settings.execution_mode,
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
