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
from services.execution.repo import insert_account_snapshot, list_open_positions


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
            recv_window=int(getattr(settings, "bybit_recv_window", 5000)),
        )
        wallet = client.wallet_balance(accountType=getattr(settings, "bybit_account_type", "UNIFIED"), coin="USDT")
        positions = client.position_list(category=getattr(settings, "bybit_category", "linear"))

        bal, eq, avail = _parse_wallet_payload(wallet)
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
