# -*- coding: utf-8 -*-
"""
execution-service 入口

- 使用 FastAPI lifespan（避免 on_event DeprecationWarning）
- 将 run_execution() 放入独立线程，避免阻塞 uvicorn event loop
- worker 崩溃时：把 traceback 打到 stdout（docker logs 能看到）
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
from services.execution.worker import run_execution

SERVICE_NAME = "execution-service"
logger = setup_logging(SERVICE_NAME)

_worker_thread: threading.Thread | None = None


def _run_worker_in_thread() -> None:
    """
    在独立线程里启动 worker（其内部会跑同步阻塞的 redis stream 消费循环）
    任何异常：打印 traceback 到 stdout，并记录日志。
    """
    try:
        asyncio.run(run_execution())
    except Exception:
        tb = traceback.format_exc()
        # ✅ 关键：直接 print，确保 docker logs 一定能看到堆栈
        print(tb, flush=True)
        logger.error(
            "worker_crashed",
            extra={"extra_fields": {"event": "WORKER_CRASHED", "traceback": tb}},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_thread

    logger.info(
        "startup",
        extra={
            "extra_fields": {
                "event": "SERVICE_START",
                "env": getattr(settings, "env", "dev"),
                "mode": getattr(settings, "execution_mode", None),
            }
        },
    )

    # 轻量依赖探测（不阻塞启动）
    try:
        RedisStreamsClient(settings.redis_url).r.ping()
    except Exception as e:
        logger.warning(
            "redis_ping_failed",
            extra={"extra_fields": {"event": "REDIS_PING_FAILED", "error": str(e)}},
        )

    # ✅ 关键：worker 放到独立线程
    _worker_thread = threading.Thread(
        target=_run_worker_in_thread, name="execution-worker", daemon=True
    )
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
        "db_url_present": bool(getattr(settings, "database_url", "")),
        "execution_mode": getattr(settings, "execution_mode", None),
    }


def main():
    # 注意：容器内监听 0.0.0.0，才能被 docker 端口映射访问
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
