# -*- coding: utf-8 -*-
"""执行对账/状态机（Phase 4）

目标：在不改变策略规则的前提下，把“分段止盈”真正落地：
- 识别 TP1/TP2 是否成交
- TP1 成交后：把 SL 上移到入场价（保本）
- TP2 成交后：Runner 跟随止损开始“实盘生效”（将 SL 更新为 runner_stop_price）

实现方式（最小可用）：
- 对所有 OPEN positions：
  - 调用 /v5/order/realtime 查询近期订单（包含已成交/已取消）
  - 通过 orderLinkId（我们自己生成）匹配 TP1/TP2 的成交状态
  - 需要更新 SL 时，调用 /v5/position/trading-stop 设置 stopLoss（Full）

注意：
- 我们只有在 TP1/TP2 已成交后才改变 SL，这不会改变策略逻辑，只是把既定规则落地。
- Runner trailing 只有在 TP2 成交后才对交易所生效（避免“全仓 SL”提前影响 TP2）。
"""

from __future__ import annotations

from typing import Any, Dict

from libs.common.config import settings
from libs.bybit.trade_rest_v5 import BybitV5Client

from services.execution.repo import list_open_positions, save_position
from services.execution.publisher import build_execution_report, publish_execution_report


def _bybit() -> BybitV5Client:
    return BybitV5Client(
        base_url=settings.bybit_rest_base_url,
        api_key=settings.bybit_api_key,
        api_secret=settings.bybit_api_secret,
        recv_window_ms=settings.bybit_recv_window,
    )


def reconcile(database_url: str, redis_url: str) -> None:
    if settings.execution_mode != "live":
        return

    client = _bybit()
    for p in list_open_positions(database_url):
        symbol = p["symbol"]
        idem = p["idempotency_key"]

        # 查询近期订单
        rr = client.open_orders(category=settings.bybit_category, symbol=symbol, open_only=0)
        lst = rr.get("result", {}).get("list", []) or []

        tp1_link = idem[:28] + "_TP1"
        tp2_link = idem[:28] + "_TP2"

        tp1_filled = False
        tp2_filled = False
        for it in lst:
            if it.get("orderLinkId") == tp1_link and it.get("orderStatus") == "Filled":
                tp1_filled = True
            if it.get("orderLinkId") == tp2_link and it.get("orderStatus") == "Filled":
                tp2_filled = True

        meta = dict(p.get("meta") or {})
        changed = False

        # TP1 成交 -> SL = entry（保本）
        if tp1_filled and not meta.get("tp1_filled"):
            meta["tp1_filled"] = True
            changed = True
            try:
                client.set_trading_stop(category=settings.bybit_category, symbol=symbol, position_idx=settings.bybit_position_idx,
                                        stop_loss=str(float(p["entry_price"])), tpsl_mode="Full")
                rep = build_execution_report(idempotency_key=idem, symbol=symbol, typ="SL_UPDATE", severity="IMPORTANT",
                                             detail={"reason": "TP1_FILLED_SL_TO_BREAKEVEN", "stop_loss": float(p["entry_price"])})
                publish_execution_report(redis_url, rep)
            except Exception as e:
                rep = build_execution_report(idempotency_key=idem, symbol=symbol, typ="ERROR", severity="IMPORTANT",
                                             detail={"stage": "SET_SL_BE", "error": str(e)})
                publish_execution_report(redis_url, rep)

        # TP2 成交 -> 启用 Runner trailing（后续 bar_close 会更新 runner_stop_price）
        if tp2_filled and not meta.get("tp2_filled"):
            meta["tp2_filled"] = True
            changed = True
            rep = build_execution_report(idempotency_key=idem, symbol=symbol, typ="TP_FILLED", severity="INFO",
                                         detail={"tp": "TP2", "runner_trailing_enabled": True})
            publish_execution_report(redis_url, rep)

        # 如果 runner_stop_price 已存在、且 TP2 已成交 -> 将 stopLoss 更新到 runner_stop_price（Full）
        if meta.get("tp2_filled") and p.get("runner_stop_price") is not None and not meta.get("runner_sl_applied"):
            try:
                client.set_trading_stop(category=settings.bybit_category, symbol=symbol, position_idx=settings.bybit_position_idx,
                                        stop_loss=str(float(p["runner_stop_price"])), tpsl_mode="Full")
                meta["runner_sl_applied"] = True
                changed = True
                rep = build_execution_report(idempotency_key=idem, symbol=symbol, typ="SL_UPDATE", severity="INFO",
                                             detail={"reason": "RUNNER_TRAIL_APPLIED", "stop_loss": float(p["runner_stop_price"])})
                publish_execution_report(redis_url, rep)
            except Exception as e:
                rep = build_execution_report(idempotency_key=idem, symbol=symbol, typ="ERROR", severity="IMPORTANT",
                                             detail={"stage": "APPLY_RUNNER_SL", "error": str(e)})
                publish_execution_report(redis_url, rep)

        if changed:
            save_position(
                database_url,
                position_id=p["position_id"],
                idempotency_key=idem,
                symbol=p["symbol"],
                timeframe=p["timeframe"],
                side=p["side"],
                bias=p["bias"],
                qty_total=p["qty_total"],
                qty_runner=p["qty_runner"],
                entry_price=p["entry_price"],
                primary_sl_price=p["primary_sl_price"],
                runner_stop_price=p["runner_stop_price"],
                status=p["status"],
                entry_close_time_ms=p["entry_close_time_ms"],
                opened_at_ms=p["opened_at_ms"],
                secondary_rule_checked=p["secondary_rule_checked"],
                hist_entry=p["hist_entry"],
                meta=meta,
            )


# compatibility shim: worker expects this symbol

def run_reconcile_once(database_url: str, redis_url: str) -> None:
    """Run a single reconcile pass.

    Kept as a thin wrapper for backward-compat with worker imports.
    """
    return reconcile(database_url, redis_url)
