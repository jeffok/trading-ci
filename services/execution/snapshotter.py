# -*- coding: utf-8 -*-
"""execution-service 资金/仓位快照（Stage 4）

目标：
- LIVE：周期性从交易所抓取 wallet/positions 快照，落库 account_snapshots
- PAPER/BACKTEST：无交易所依赖时，仍可写入派生快照（用于运行监控与复盘）

注意：
- 快照属于“可观测性”，失败不影响交易执行
"""

from __future__ import annotations

import datetime
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from libs.common.config import settings
from libs.common.time import now_ms
from libs.bybit.trade_rest_v5 import BybitV5Client
from libs.common.id import new_event_id
from services.execution.repo import insert_account_snapshot, list_open_positions, insert_risk_event, insert_wallet_snapshot, get_latest_wallet_snapshot
from services.execution.publisher import build_risk_event, publish_risk_event

# Stage 10: module-level de-dup for wallet drift alerts
_WALLET_DRIFT_LAST_EMIT_MS: int | None = None


def _utc_trade_date() -> str:
    return datetime.datetime.utcnow().date().isoformat()


def _mode() -> str:
    m = getattr(settings, "execution_mode", "LIVE").upper()
    return m


def _snapshot_id(ts_ms: int) -> str:
    return hashlib.sha256(f"{_mode()}|{ts_ms}".encode("utf-8")).hexdigest()


def _parse_wallet_payload(payload: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """尽可能从 Bybit wallet payload 中解析 balance/equity/available（字段可能因账户类型不同而变化）。"""
    bal = eq = avail = None
    try:
        # 常见结构：result.list[0].coin[0].walletBalance / equity / availableToWithdraw 等
        lst = payload.get("result", {}).get("list", [])
        if lst and lst[0].get("coin"):
            c = lst[0]["coin"][0]
            for k in ["walletBalance", "equity", "availableToWithdraw", "availableBalance"]:
                if k in c:
                    if k == "walletBalance":
                        bal = float(c[k])
                    elif k == "equity":
                        eq = float(c[k])
                    else:
                        avail = float(c[k])
    except Exception:
        pass
    return bal, eq, avail



def _wallet_drift_pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    denom = abs(b) if abs(b) > 1e-9 else None
    if denom is None:
        return None
    return abs(a - b) / denom


def _should_emit_wallet_drift(last_emit_ms: int | None, now_ms_: int, window_ms: int) -> bool:
    if last_emit_ms is None:
        return True
    return (now_ms_ - int(last_emit_ms)) >= int(window_ms)


def _insert_and_check_wallet_drift(*, ts_ms: int, trade_date: str, wallet_rest: dict) -> None:
    """Persist REST wallet snapshot and compare against latest WS snapshot to emit CONSISTENCY_DRIFT.

    - WS is the primary near-real-time source.
    - REST snapshotter provides a periodic ground truth / fallback.
    """
    coin = str(getattr(settings, "bybit_wallet_coin", "USDT"))
    bal, eq, avail = _parse_wallet_payload(wallet_rest)
    # persist REST wallet snapshot for audit
    snap_id = hashlib.sha256(f"REST|{ts_ms}|{coin}".encode("utf-8")).hexdigest()
    try:
        insert_wallet_snapshot(
            settings.database_url,
            snapshot_id=snap_id,
            ts_ms=ts_ms,
            source="REST",
            balance_usdt=bal,
            equity_usdt=eq,
            available_usdt=avail,
            payload={"coin": coin, "raw": wallet_rest},
        )
    except Exception:
        pass

    if not bool(getattr(settings, "wallet_compare_enabled", True)):
        return

    ws = None
    try:
        ws = get_latest_wallet_snapshot(settings.database_url, source="WS")
    except Exception:
        ws = None
    if not ws:
        return

    max_age = int(getattr(settings, "wallet_ws_max_age_ms", 90_000))
    if (ts_ms - int(ws.get("ts_ms", 0))) > max_age:
        return

    drift_eq = _wallet_drift_pct(eq, ws.get("equity_usdt"))
    drift_bal = _wallet_drift_pct(bal, ws.get("balance_usdt"))
    drift_avail = _wallet_drift_pct(avail, ws.get("available_usdt"))

    threshold = float(getattr(settings, "wallet_drift_threshold_pct", 0.02))
    drift = max([d for d in (drift_eq, drift_bal, drift_avail) if d is not None], default=None)
    if drift is None or drift < threshold:
        return

    # window de-dup (store in redis stream idempotency is best-effort; we store last_emit in ext only)
    window_ms = int(getattr(settings, "wallet_drift_window_ms", 300_000))
    global _WALLET_DRIFT_LAST_EMIT_MS
    if not _should_emit_wallet_drift(_WALLET_DRIFT_LAST_EMIT_MS, ts_ms, window_ms):
        return

    detail = {
        "scope": "wallet",
        "threshold_pct": threshold,
        "drift_pct": drift,
        "rest": {"balance": bal, "equity": eq, "available": avail, "ts_ms": ts_ms},
        "ws": {"balance": ws.get("balance_usdt"), "equity": ws.get("equity_usdt"), "available": ws.get("available_usdt"), "ts_ms": ws.get("ts_ms")},
    }
    ev = build_risk_event(
        typ="CONSISTENCY_DRIFT",
        severity="IMPORTANT",
        symbol=None,
        detail=detail,
        retry_after_ms=None,
        ext={"scope": "wallet"},
        trace_id=None,
    )
    publish_risk_event(settings.redis_url, ev)
    insert_risk_event(
        settings.database_url,
        event_id=new_event_id(),
        trade_date=trade_date,
        ts_ms=ts_ms,
        typ="CONSISTENCY_DRIFT",
        severity="IMPORTANT",
        detail=detail,
    )
    _WALLET_DRIFT_LAST_EMIT_MS = ts_ms

def _parse_positions_payload(payload: Dict[str, Any]) -> Tuple[int, Optional[float]]:
    """返回 position_count 与合计 unrealized pnl（若字段存在）。"""
    pc = 0
    upnl = 0.0
    have = False
    try:
        lst = payload.get("result", {}).get("list", [])
        pc = 0
        for p in lst:
            size = float(p.get("size", 0) or 0)
            if size != 0:
                pc += 1
            if p.get("unrealisedPnl") is not None:
                upnl += float(p.get("unrealisedPnl"))
                have = True
    except Exception:
        return pc, None
    return pc, (upnl if have else None)


async def run_snapshot_loop() -> None:
    interval = float(getattr(settings, "account_snapshot_interval_sec", 30.0))
    while True:
        try:
            await take_one_snapshot()
        except Exception:
            pass
        import asyncio
        await asyncio.sleep(interval)


async def take_one_snapshot() -> None:
    ts = now_ms()
    trade_date = _utc_trade_date()
    mode = _mode()

    if mode == "LIVE":
        client = BybitV5Client(
            base_url=settings.bybit_rest_base_url,
            api_key=settings.bybit_api_key,
            api_secret=settings.bybit_api_secret,
            recv_window_ms=int(getattr(settings, "bybit_recv_window", 5000)),
        )
        wallet = client.wallet_balance_cached(account_type=getattr(settings, "bybit_account_type", "UNIFIED"), coin="USDT")

        # Stage 5: public-first / private-load reduction.
        # If there are no OPEN positions in DB, skip the heavy private position/list call.
        # This does NOT change trading logic; it's purely an observability optimization.
        open_pos = list_open_positions(settings.database_url, limit=10)
        if bool(getattr(settings, "bybit_private_active_symbols_only", True)) and not open_pos:
            positions = {"retCode": 0, "retMsg": "OK", "result": {"list": []}, "_skipped": True}
        else:
            positions = client.position_list_cached(category=getattr(settings, "bybit_category", "linear"), symbol=None)

        # Stage 4: degrade/alerts
        for name, payload in (("snapshotter.wallet_balance_cached", wallet), ("snapshotter.position_list_cached", positions)):
            if isinstance(payload, dict) and payload.get("_degraded"):
                ev = build_risk_event(
                    typ="RATE_LIMIT",
                    severity="IMPORTANT",
                    symbol=None,
                    detail={"context": name, "predicted_wait_ms": payload.get("_predicted_wait_ms"), "stale_ms": payload.get("_stale_ms")},
                )
                publish_risk_event(settings.redis_url, ev)
                insert_risk_event(
                    settings.database_url,
                    event_id=new_event_id(),
                    trade_date=trade_date,
                    ts_ms=ts,
                    typ="RATE_LIMIT",
                    severity="IMPORTANT",
                    detail={"context": name, "predicted_wait_ms": payload.get("_predicted_wait_ms"), "stale_ms": payload.get("_stale_ms")},
                )

        bal, eq, avail = _parse_wallet_payload(wallet)

        # Stage 10: REST wallet snapshot + WS drift detection
        _insert_and_check_wallet_drift(ts_ms=ts, trade_date=trade_date, wallet_rest=wallet)
        pc, upnl = _parse_positions_payload(positions)

        insert_account_snapshot(
            settings.database_url,
            snapshot_id=_snapshot_id(ts),
            ts_ms=ts,
            trade_date=trade_date,
            mode=mode,
            balance_usdt=bal,
            equity_usdt=eq,
            available_usdt=avail,
            unrealized_pnl=upnl,
            position_count=pc,
            payload={"wallet": wallet, "positions": positions},
        )
    else:
        # PAPER/BACKTEST：用 DB 的 open positions 做派生快照
        open_pos = list_open_positions(settings.database_url, limit=200)
        insert_account_snapshot(
            settings.database_url,
            snapshot_id=_snapshot_id(ts),
            ts_ms=ts,
            trade_date=trade_date,
            mode=mode,
            balance_usdt=None,
            equity_usdt=None,
            available_usdt=None,
            unrealized_pnl=None,
            position_count=len(open_pos),
            payload={"derived": {"open_positions": open_pos}},
        )
