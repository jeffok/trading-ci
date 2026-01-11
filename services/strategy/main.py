"""
strategy-service 入口（Phase 0 骨架）

职责：
- 提供最小可运行 HTTP 服务（/health）
- 验证环境变量与依赖连通性（轻量 ping）
- 为后续 consumer/handler 留出扩展点
"""

from __future__ import annotations

from fastapi import FastAPI
import uvicorn

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient

SERVICE_NAME = "strategy-service"
logger = setup_logging(SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)

@app.get("/health")
def health():
    """健康检查：不做重操作，仅快速探测依赖。"""
    redis_ok = False
    try:
        client = RedisStreamsClient(settings.redis_url)
        client.r.ping()
        redis_ok = True
    except Exception as e:
        logger.warning("redis_ping_failed", extra={"extra_fields": {"event":"REDIS_PING_FAILED","error": str(e)}})

    return {
        "env": settings.env,
        "service": SERVICE_NAME,
        "redis_ok": redis_ok,
        "db_url_present": bool(settings.database_url),
    }

def main():
    logger.info("service_start", extra={"extra_fields": {"event":"SERVICE_START","env": settings.env}})
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
