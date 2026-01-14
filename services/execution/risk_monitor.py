# -*- coding: utf-8 -*-
"""账户级风控监控（Phase 6）"""

from __future__ import annotations

import datetime

from libs.common.config import settings
from libs.common.time import now_ms
from libs.common.id import new_event_id
from libs.bybit.trade_rest_v5 import BybitV5Client
from libs.execution.circuit import eval_drawdown

from services.execution.repo import get_or_init_risk_state, update_risk_state, insert_risk_event, list_open_positions
from services.execution.publisher import build_risk_event, publish_risk_event
from services.execution.executor import close_position_market


def _today_utc_date() -> str:
    return datetime.datetime.utcnow().date().isoformat()


def _bybit() -> BybitV5Client:
    return BybitV5Client(
        base_url=settings.bybit_rest_base_url,
        api_key=settings.bybit_api_key,
        api_secret=settings.bybit_api_secret,
        recv_window_ms=settings.bybit_recv_window,
    )


def _equity_usdt_from_wallet_balance(resp: dict) -> float:
    res = resp.get("result", {}) or {}
    lst = res.get("list", []) or []
    if not lst:
        raise RuntimeError(f"wallet_balance empty: {resp}")
    item = lst[0]
    for k in ["totalEquity", "equity", "walletBalance"]:
        v = item.get(k)
        if v is not None and str(v) != "":
            return float(v)
    coins = item.get("coin", []) or []
    for c in coins:
        if c.get("coin") == "USDT":
            for k in ["equity", "walletBalance"]:
                v = c.get(k)
                if v is not None and str(v) != "":
                    return float(v)
    raise RuntimeError(f"cannot parse equity: {resp}")


def run_risk_monitor_once(database_url: str, redis_url: str) -> None:
    trade_date = _today_utc_date()
    st = get_or_init_risk_state(database_url, trade_date=trade_date, mode=settings.execution_mode)

    if settings.execution_mode != "live":
        return

    if not settings.risk_circuit_enabled:
        return  # 熔断关闭：不更新、不触发 soft/hard

    client = _bybit()
    wb = client.wallet_balance_cached(account_type=settings.bybit_account_type, coin="USDT")
    if wb.get("_degraded"):
        ev = build_risk_event(
            typ="RATE_LIMIT",
            severity="IMPORTANT",
            symbol=None,
            detail={"context": "risk_monitor.wallet_balance_cached", "predicted_wait_ms": wb.get("_predicted_wait_ms"), "stale_ms": wb.get("_stale_ms")},
        )
        publish_risk_event(redis_url, ev)
        insert_risk_event(
            database_url,
            event_id=new_event_id(),
            trade_date=trade_date,
            ts_ms=now_ms(),
            typ="RATE_LIMIT",
            severity="IMPORTANT",
            detail={"context": "risk_monitor.wallet_balance_cached", "predicted_wait_ms": wb.get("_predicted_wait_ms"), "stale_ms": wb.get("_stale_ms")},
        )
    eq = _equity_usdt_from_wallet_balance(wb)

    starting = st["starting_equity"] if st["starting_equity"] is not None else eq
    min_eq = st["min_equity"] if st["min_equity"] is not None else eq
    max_eq = st["max_equity"] if st["max_equity"] is not None else eq

    min_eq = min(float(min_eq), float(eq))
    max_eq = max(float(max_eq), float(eq))

    decision = eval_drawdown(
        starting_equity=float(starting),
        min_equity=float(min_eq),
        soft_pct=float(settings.daily_drawdown_soft_pct),
        hard_pct=float(settings.daily_drawdown_hard_pct),
    )

    soft = bool(st["soft_halt"]) or decision.soft_halt
    hard = bool(st["hard_halt"]) or decision.hard_halt
    kill = bool(st["kill_switch"]) or hard

    update_risk_state(
        database_url,
        trade_date=trade_date,
        starting_equity=float(starting),
        current_equity=float(eq),
        min_equity=float(min_eq),
        max_equity=float(max_eq),
        drawdown_pct=float(decision.drawdown_pct),
        soft_halt=soft,
        hard_halt=hard,
        kill_switch=kill,
        meta={"threshold_soft": settings.daily_drawdown_soft_pct, "threshold_hard": settings.daily_drawdown_hard_pct},
    )

    if decision.soft_halt and not st["soft_halt"]:
        ev = build_risk_event(typ="DAILY_DRAWDOWN_SOFT", severity="IMPORTANT", symbol=None, detail={"drawdown_pct": decision.drawdown_pct})
        publish_risk_event(redis_url, ev)
        insert_risk_event(database_url, event_id=new_event_id(), trade_date=trade_date, ts_ms=now_ms(), typ="DAILY_DRAWDOWN_SOFT", severity="IMPORTANT", detail={"drawdown_pct": decision.drawdown_pct})

    if decision.hard_halt and not st["hard_halt"]:
        ev = build_risk_event(typ="DAILY_DRAWDOWN_HARD", severity="EMERGENCY", symbol=None, detail={"drawdown_pct": decision.drawdown_pct})
        publish_risk_event(redis_url, ev)
        insert_risk_event(database_url, event_id=new_event_id(), trade_date=trade_date, ts_ms=now_ms(), typ="DAILY_DRAWDOWN_HARD", severity="EMERGENCY", detail={"drawdown_pct": decision.drawdown_pct})

        for p in list_open_positions(database_url):
            try:
                close_position_market(database_url, redis_url, idempotency_key=p["idempotency_key"], symbol=p["symbol"], side=p["side"])
            except Exception:
                pass
