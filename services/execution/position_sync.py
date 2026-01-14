# -*- coding: utf-8 -*-
"""持仓同步（Stage 1）

目的：
- live 模式下，定期把 DB 中 OPEN 的 positions 与交易所实际持仓对齐
- 当交易所持仓 size=0（已被 SL/TP/手工平仓）时，更新 DB 为 CLOSED
- 若判断为 STOP_LOSS，则写入 cooldown（按 timeframe bars）

说明：
- 我们采用“保守识别”：若 TP1 未成交则认为更可能是 SL（用于冷却）。
  你后续可通过 private WS 或成交回报进一步精确 exit_reason。
"""

from __future__ import annotations

from typing import Any, Dict
import datetime

from libs.common.config import settings
from libs.common.time import now_ms
from libs.common.id import new_event_id
from libs.common.timeframe import timeframe_ms
from libs.bybit.trade_rest_v5 import BybitV5Client

from services.execution.repo import list_open_positions, mark_position_closed, upsert_cooldown, insert_risk_event
from services.execution.publisher import build_execution_report, publish_execution_report, build_risk_event, publish_risk_event


def _bybit() -> BybitV5Client:
    return BybitV5Client(
        base_url=settings.bybit_rest_base_url,
        api_key=settings.bybit_api_key,
        api_secret=settings.bybit_api_secret,
        recv_window_ms=settings.bybit_recv_window,
    )


def _cooldown_bars(tf: str) -> int:
    if tf == "1h":
        return int(settings.cooldown_bars_1h)
    if tf == "4h":
        return int(settings.cooldown_bars_4h)
    if tf == "1d":
        return int(settings.cooldown_bars_1d)
    return int(settings.cooldown_bars_1h)


def sync_positions(database_url: str, redis_url: str) -> None:
    if settings.execution_mode != "live":
        return

    client = _bybit()
    trade_date = datetime.datetime.utcnow().date().isoformat()
    for p in list_open_positions(database_url):
        symbol = p["symbol"]
        idem = p["idempotency_key"]
        tf = p["timeframe"]

        try:
            pos = client.position_list_cached(category=settings.bybit_category, symbol=symbol)
            if isinstance(pos, dict) and pos.get("_degraded"):
                ev = build_risk_event(
                    typ="RATE_LIMIT",
                    severity="IMPORTANT",
                    symbol=symbol,
                    detail={"context": "position_sync.position_list_cached", "predicted_wait_ms": pos.get("_predicted_wait_ms"), "stale_ms": pos.get("_stale_ms")},
                )
                publish_risk_event(redis_url, ev)
                insert_risk_event(
                    database_url,
                    event_id=new_event_id(),
                    trade_date=trade_date,
                    ts_ms=now_ms(),
                    typ="RATE_LIMIT",
                    severity="IMPORTANT",
                    detail={"context": "position_sync.position_list_cached", "predicted_wait_ms": pos.get("_predicted_wait_ms"), "stale_ms": pos.get("_stale_ms"), "symbol": symbol},
                )
            lst = pos.get("result", {}).get("list", []) or []
            size = 0.0
            if lst:
                try:
                    size = float(lst[0].get("size", "0") or "0")
                except Exception:
                    size = 0.0

            if size > 0:
                continue  # still open on exchange

            # exchange says closed
            meta = dict(p.get("meta") or {})
            tp1 = bool(meta.get("tp1_filled"))
            exit_reason = "EXCHANGE_CLOSED"

            # 保守：未触发 TP1 -> 更可能是 SL（用于冷却）
            if settings.cooldown_enabled and (not tp1):
                exit_reason = "STOP_LOSS"
                bars = _cooldown_bars(tf)
                until = now_ms() + bars * timeframe_ms(tf)
                upsert_cooldown(
                    database_url,
                    cooldown_id=new_event_id(),
                    symbol=symbol,
                    side=p["side"],
                    timeframe=tf,
                    reason="STOP_LOSS",
                    until_ts_ms=until,
                    meta={"bars": bars, "source": "position_sync"},
                )
                rep = build_execution_report(
                    idempotency_key=idem, symbol=symbol, typ="COOLDOWN_SET", severity="IMPORTANT",
                    detail={"timeframe": tf, "bars": bars, "until_ts_ms": until}
                )
                publish_execution_report(redis_url, rep)

            mark_position_closed(database_url, position_id=p["position_id"], closed_at_ms=now_ms(), exit_reason=exit_reason, meta=meta)

            rep = build_execution_report(idempotency_key=idem, symbol=symbol, typ="POSITION_CLOSED", severity="INFO",
                                         detail={"exit_reason": exit_reason, "timeframe": tf})
            publish_execution_report(redis_url, rep)
        except Exception as e:
            rep = build_execution_report(idempotency_key=idem, symbol=symbol, typ="ERROR", severity="IMPORTANT",
                                         detail={"stage": "POSITION_SYNC", "error": str(e)})
            publish_execution_report(redis_url, rep)
