"""
marketdata-service 入口（Phase 1）

使用 FastAPI Lifespan 替代 on_event，避免 DeprecationWarning。

启动后后台任务 run_marketdata():
- Bybit Public WS 订阅 Kline
- candle 收盘后写库 + 发布 bar_close 事件

保留：/health 供容器编排探测。
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
from services.marketdata.worker import run_marketdata

SERVICE_NAME = "marketdata-service"
logger = setup_logging(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    logger.info(
        "startup",
        extra={"extra_fields": {"event": "SERVICE_START", "env": settings.env}},
    )

    # 轻量依赖探测（不强制失败）
    try:
        RedisStreamsClient(settings.redis_url).r.ping()
    except Exception as e:
        logger.warning(
            "redis_ping_failed",
            extra={"extra_fields": {"event": "REDIS_PING_FAILED", "error": str(e)}},
        )

    app.state.bg_task = asyncio.create_task(run_marketdata())

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
        "db_url_present": bool(settings.database_url),
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
