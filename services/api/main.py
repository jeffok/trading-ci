# -*- coding: utf-8 -*-
"""api-service（Phase 4）

提供只读查询接口：
- /signals
- /trade-plans
- /orders
- /positions
- /execution-reports
"""

from __future__ import annotations

from fastapi import FastAPI, Request
import uvicorn

from libs.common.config import settings
from libs.common.logging import setup_logging
from services.api.dlq import read_dlq
from services.api.repo import (
    list_signals,
    list_trade_plans,
    list_orders,
    list_positions,
    list_execution_reports,
    get_risk_state,
    list_risk_events,
    list_indicator_snapshots,
    list_setups,
    list_triggers,
    list_pivots,
    list_notifications,
    list_execution_traces,
    list_account_snapshots,
    list_backtest_runs,
    list_backtest_trades,
    compare_backtest_run,
)

SERVICE_NAME = "api-service"
logger = setup_logging(SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)


@app.get("/health")
def health():
    return {"env": settings.env, "service": SERVICE_NAME}


@app.get("/signals")
def signals(limit: int = 50):
    return {"items": list_signals(settings.database_url, limit=limit)}


@app.get("/trade-plans")
def trade_plans(limit: int = 50):
    return {"items": list_trade_plans(settings.database_url, limit=limit)}


@app.get("/orders")
def orders(limit: int = 50):
    return {"items": list_orders(settings.database_url, limit=limit)}


@app.get("/positions")
def positions(limit: int = 50):
    return {"items": list_positions(settings.database_url, limit=limit)}


@app.get("/execution-reports")
def execution_reports(limit: int = 50):
    return {"items": list_execution_reports(settings.database_url, limit=limit)}


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()


@app.get("/risk-state")
def risk_state(trade_date: str):
    return get_risk_state(settings.database_url, trade_date=trade_date)


@app.get("/risk-events")
def risk_events(trade_date: str, limit: int = 50):
    return {"items": list_risk_events(settings.database_url, trade_date=trade_date, limit=limit)}


def _require_admin(request) -> None:
    token = request.headers.get("X-Admin-Token", "")
    if not settings.admin_token or token != settings.admin_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/v1/admin/kill-switch")
def admin_kill_switch(payload: dict, request: Request):
    """设置/清除 kill-switch（写入 risk_state）。

    payload:
      - enabled: bool

    Header:
      - X-Admin-Token: <ADMIN_TOKEN>
    """
    _require_admin(request)
    import datetime
    trade_date = datetime.datetime.utcnow().date().isoformat()
    enabled = bool(payload.get("enabled", False))
    # 这里直接更新 risk_state：若不存在则初始化
    st = get_risk_state(settings.database_url, trade_date=trade_date)
    if not st.get("exists"):
        # 调用 execution repo 的 init 逻辑不方便；这里用 SQL 简化
        from services.api.repo import get_conn
        with get_conn(settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO risk_state(trade_date, mode, kill_switch) VALUES (%s,%s,%s) ON CONFLICT(trade_date) DO NOTHING;",
                    (trade_date, settings.execution_mode, enabled),
                )
                conn.commit()

    from services.api.repo import get_conn
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE risk_state SET kill_switch=%s, updated_at=now() WHERE trade_date=%s;", (enabled, trade_date))
            conn.commit()

    return {"trade_date": trade_date, "kill_switch": enabled}


@app.post("/v1/admin/risk-circuit")
def admin_risk_circuit(payload: dict, request: Request):
    """查询当前进程的 risk_circuit_enabled 配置（注意：这是环境变量级别，不是动态配置）。"""
    _require_admin(request)
    return {"risk_circuit_enabled": bool(settings.risk_circuit_enabled)}


# ---------------- Stage 3：/v1 规范化接口（保留旧路径兼容） ----------------

@app.get("/v1/signals")
def v1_signals(limit: int = 50):
    return {"items": list_signals(settings.database_url, limit=limit)}


@app.get("/v1/trade-plans")
def v1_trade_plans(limit: int = 50):
    return {"items": list_trade_plans(settings.database_url, limit=limit)}


@app.get("/v1/orders")
def v1_orders(limit: int = 50):
    return {"items": list_orders(settings.database_url, limit=limit)}


@app.get("/v1/positions")
def v1_positions(limit: int = 50):
    return {"items": list_positions(settings.database_url, limit=limit)}


@app.get("/v1/execution-reports")
def v1_execution_reports(limit: int = 50):
    return {"items": list_execution_reports(settings.database_url, limit=limit)}


@app.get("/v1/risk-state")
def v1_risk_state(trade_date: str):
    return get_risk_state(settings.database_url, trade_date=trade_date)


@app.get("/v1/risk-events")
def v1_risk_events(trade_date: str, limit: int = 50):
    return {"items": list_risk_events(settings.database_url, trade_date=trade_date, limit=limit)}


@app.get("/v1/indicator-snapshots")
def v1_indicator_snapshots(symbol: str, timeframe: str, limit: int = 50):
    return {"items": list_indicator_snapshots(settings.database_url, symbol=symbol, timeframe=timeframe, limit=limit)}


@app.get("/v1/setups")
def v1_setups(symbol: str, timeframe: str, limit: int = 50):
    return {"items": list_setups(settings.database_url, symbol=symbol, timeframe=timeframe, limit=limit)}


@app.get("/v1/triggers")
def v1_triggers(symbol: str, timeframe: str, limit: int = 50):
    return {"items": list_triggers(settings.database_url, symbol=symbol, timeframe=timeframe, limit=limit)}


@app.get("/v1/pivots")
def v1_pivots(symbol: str, timeframe: str, limit: int = 50):
    return {"items": list_pivots(settings.database_url, symbol=symbol, timeframe=timeframe, limit=limit)}


@app.get("/v1/notifications")
def v1_notifications(limit: int = 50):
    return {"items": list_notifications(settings.database_url, limit=limit)}


@app.get("/v1/config")
def v1_config():
    """返回脱敏配置（不包含密钥/私钥）。"""
    cfg = settings.model_dump(by_alias=True)
    # 脱敏：删除所有可能敏感字段
    redacted_keys = [
        "BYBIT_API_KEY",
        "BYBIT_API_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "ADMIN_TOKEN",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "REDIS_URL",
    ]
    for k in list(cfg.keys()):
        if k in redacted_keys or "SECRET" in k or "PASSWORD" in k or "KEY" in k and k != "BYBIT_CATEGORY":
            cfg[k] = "***REDACTED***"
    return {"config": cfg}


@app.get("/v1/dlq")
def v1_dlq(limit: int = 50, request: Request = None):
    """查询 DLQ（需要管理员口令）。"""
    _require_admin(request)
    return {"items": read_dlq(settings.redis_url, count=limit)}


# ---------------- Stage 4：执行复盘与资金快照查询 ----------------

@app.get("/v1/execution-traces")
def v1_execution_traces(idempotency_key: str, limit: int = 200):
    return {"items": list_execution_traces(settings.database_url, idempotency_key=idempotency_key, limit=limit)}


@app.get("/v1/account-snapshots")
def v1_account_snapshots(trade_date: str, limit: int = 200):
    return {"items": list_account_snapshots(settings.database_url, trade_date=trade_date, limit=limit)}


# ---------------- Stage 5：回测查询 ----------------

@app.get("/v1/backtest-runs")
def v1_backtest_runs(symbol: str | None = None, timeframe: str | None = None, limit: int = 50):
    return {"items": list_backtest_runs(settings.database_url, symbol=symbol, timeframe=timeframe, limit=limit)}


@app.get("/v1/backtest-trades")
def v1_backtest_trades(run_id: str, limit: int = 500):
    return {"items": list_backtest_trades(settings.database_url, run_id=run_id, limit=limit)}


# ---------------- Stage 7：回放闭环核对 ----------------

@app.get("/v1/backtest-compare")
def v1_backtest_compare(run_id: str, limit_trades: int = 50):
    return compare_backtest_run(settings.database_url, run_id=run_id, limit_trades=limit_trades)
