# -*- coding: utf-8 -*-
"""Backtest 落库（Stage 5）

目标：
- backtest_runs：一次回测的参数与汇总指标
- backtest_trades：逐笔交易（含分段 legs）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import json

from libs.db.pg import get_conn


SQL_INSERT_RUN = """
INSERT INTO backtest_runs(run_id, symbol, timeframe, start_time_ms, end_time_ms, params, summary)
VALUES (%(id)s,%(symbol)s,%(tf)s,%(start)s,%(end)s,%(params)s::jsonb,%(summary)s::jsonb)
ON CONFLICT (run_id) DO NOTHING;
"""

SQL_INSERT_TRADE = """
INSERT INTO backtest_trades(trade_id, run_id, symbol, timeframe, entry_time_ms, exit_time_ms, side, entry_price, exit_price, pnl_r, reason, legs, idempotency_key, idempotency_key)
VALUES (%(id)s,%(run)s,%(symbol)s,%(tf)s,%(et)s,%(xt)s,%(side)s,%(ep)s,%(xp)s,%(pnl)s,%(reason)s,%(legs)s::jsonb,%(idem)s)
ON CONFLICT (trade_id) DO NOTHING;
"""


def insert_backtest_run(database_url: str, *, run_id: str, symbol: str, timeframe: str, start_time_ms: int | None, end_time_ms: int | None,
                        params: Dict[str, Any], summary: Dict[str, Any]) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_INSERT_RUN, {
                "id": run_id,
                "symbol": symbol,
                "tf": timeframe,
                "start": start_time_ms,
                "end": end_time_ms,
                "params": json.dumps(params, ensure_ascii=False),
                "summary": json.dumps(summary, ensure_ascii=False),
            })
            conn.commit()


def insert_backtest_trade(database_url: str, *, trade_id: str, run_id: str, symbol: str, timeframe: str,
                          entry_time_ms: int, exit_time_ms: int, side: str,
                          entry_price: float, exit_price: float, pnl_r: float, reason: str,
                          legs: List[Dict[str, Any]], idempotency_key: str | None = None) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_INSERT_TRADE, {
                "id": trade_id,
                "run": run_id,
                "symbol": symbol,
                "tf": timeframe,
                "et": int(entry_time_ms),
                "xt": int(exit_time_ms),
                "side": side,
                "ep": float(entry_price),
                "xp": float(exit_price),
                "pnl": float(pnl_r),
                "reason": reason,
                "legs": json.dumps(legs, ensure_ascii=False),
                "idem": idempotency_key,
            })
            conn.commit()


def list_backtest_trades(database_url: str, *, run_id: str, limit: int = 100000) -> List[Dict[str, Any]]:
    """读取某个 run 的 trades（Stage 6：REPLAY 回放后做快速 summary / API compare）。"""
    sql = """
    SELECT trade_id, run_id, symbol, timeframe, entry_time_ms, exit_time_ms, side, entry_price, exit_price, pnl_r, reason, legs, idempotency_key
    FROM backtest_trades
    WHERE run_id=%(run_id)s
    ORDER BY exit_time_ms ASC
    LIMIT %(limit)s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"run_id": run_id, "limit": int(limit)})
            rows = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "trade_id": r[0],
            "run_id": r[1],
            "symbol": r[2],
            "timeframe": r[3],
            "entry_time_ms": int(r[4]),
            "exit_time_ms": int(r[5]),
            "side": r[6],
            "entry_price": float(r[7]),
            "exit_price": float(r[8]),
            "pnl_r": float(r[9]),
            "reason": r[10],
            "legs": _json(r[11]),
            "idempotency_key": r[12],
        })
    return out
