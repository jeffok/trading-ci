# -*- coding: utf-8 -*-
"""api-service DB 只读查询（Phase 4）"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from libs.db.pg import get_conn


def _rows(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        row = {}
        for i, c in enumerate(cols):
            row[c] = r[i]
        out.append(row)
    return out


def list_signals(database_url: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = "SELECT signal_id, symbol, timeframe, close_time_ms, bias, vegas_state, hit_count, hits, created_at FROM signals ORDER BY created_at DESC LIMIT %s"
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return _rows(cur)


def list_trade_plans(database_url: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = "SELECT plan_id, symbol, timeframe, close_time_ms, side, entry_price, primary_sl_price, created_at FROM trade_plans ORDER BY created_at DESC LIMIT %s"
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return _rows(cur)


def list_orders(database_url: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = "SELECT order_id, symbol, purpose, side, order_type, qty, price, reduce_only, status, created_at, updated_at FROM orders ORDER BY created_at DESC LIMIT %s"
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return _rows(cur)


def list_positions(database_url: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = "SELECT position_id, symbol, timeframe, side, bias, qty_total, qty_runner, entry_price, primary_sl_price, runner_stop_price, status, created_at, updated_at FROM positions ORDER BY created_at DESC LIMIT %s"
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return _rows(cur)


def list_execution_reports(database_url: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
    SELECT report_id, symbol, type, severity, created_at,
           plan_id, status, timeframe, filled_qty, avg_price, reason
    FROM execution_reports
    ORDER BY created_at DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return _rows(cur)


def get_risk_state(database_url: str, trade_date: str) -> Dict[str, Any]:
    sql = "SELECT trade_date, mode, starting_equity, current_equity, min_equity, max_equity, drawdown_pct, soft_halt, hard_halt, kill_switch, updated_at, meta FROM risk_state WHERE trade_date=%s"
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (trade_date,))
            row = cur.fetchone()
    if not row:
        return {"trade_date": trade_date, "exists": False}
    return {
        "trade_date": str(row[0]),
        "mode": row[1],
        "starting_equity": row[2],
        "current_equity": row[3],
        "min_equity": row[4],
        "max_equity": row[5],
        "drawdown_pct": row[6],
        "soft_halt": bool(row[7]),
        "hard_halt": bool(row[8]),
        "kill_switch": bool(row[9]),
        "updated_at": row[10].isoformat() if row[10] else None,
        "meta": row[11],
        "exists": True,
    }


def list_risk_events(database_url: str, trade_date: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
    SELECT event_id, ts_ms, type, severity, symbol, retry_after_ms, detail
    FROM risk_events
    WHERE trade_date=%s
    ORDER BY ts_ms DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (trade_date, limit))
            return _rows(cur)


# ---------------- Stage 3：复盘查询（snapshots/setups/triggers/pivots/notifications） ----------------

def list_indicator_snapshots(database_url: str, *, symbol: str, timeframe: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
    SELECT snapshot_id, symbol, timeframe, close_time_ms, kind, created_at
    FROM indicator_snapshots
    WHERE symbol=%s AND timeframe=%s
    ORDER BY close_time_ms DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol, timeframe, limit))
            return _rows(cur)


def list_setups(database_url: str, *, symbol: str, timeframe: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
    SELECT setup_id, symbol, timeframe, close_time_ms, bias, setup_type, created_at
    FROM setups
    WHERE symbol=%s AND timeframe=%s
    ORDER BY close_time_ms DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol, timeframe, limit))
            return _rows(cur)


def list_triggers(database_url: str, *, symbol: str, timeframe: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
    SELECT trigger_id, setup_id, symbol, timeframe, close_time_ms, bias, hits, created_at
    FROM triggers
    WHERE symbol=%s AND timeframe=%s
    ORDER BY close_time_ms DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol, timeframe, limit))
            return _rows(cur)


def list_pivots(database_url: str, *, symbol: str, timeframe: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
    SELECT pivot_id, setup_id, symbol, timeframe, pivot_time_ms, pivot_price, pivot_type, segment_no, created_at
    FROM pivots
    WHERE symbol=%s AND timeframe=%s
    ORDER BY pivot_time_ms DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol, timeframe, limit))
            return _rows(cur)


def list_notifications(database_url: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
    SELECT notification_id, stream, severity, status, attempts, next_attempt_at, created_at, sent_at, last_error
    FROM notifications
    ORDER BY created_at DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return _rows(cur)


def list_execution_traces(database_url: str, *, idempotency_key: str, limit: int = 200) -> List[Dict[str, Any]]:
    sql = """
    SELECT trace_row_id, trace_id, idempotency_key, ts_ms, stage, detail, created_at
    FROM execution_traces
    WHERE idempotency_key=%s
    ORDER BY ts_ms ASC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (idempotency_key, limit))
            return _rows(cur)


def list_account_snapshots(database_url: str, *, trade_date: str, limit: int = 200) -> List[Dict[str, Any]]:
    sql = """
    SELECT snapshot_id, ts_ms, trade_date, mode, balance_usdt, equity_usdt, available_usdt, unrealized_pnl, position_count, created_at
    FROM account_snapshots
    WHERE trade_date=%s::date
    ORDER BY ts_ms DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (trade_date, limit))
            return _rows(cur)


def list_backtest_runs(database_url: str, *, symbol: str | None = None, timeframe: str | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
    SELECT run_id, created_at, symbol, timeframe, start_time_ms, end_time_ms, params, summary
    FROM backtest_runs
    WHERE (%s::text IS NULL OR symbol=%s) AND (%s::text IS NULL OR timeframe=%s)
    ORDER BY created_at DESC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol, symbol, timeframe, timeframe, limit))
            return _rows(cur)


def list_backtest_trades(database_url: str, *, run_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    sql = """
    SELECT trade_id, run_id, symbol, timeframe, entry_time_ms, exit_time_ms, side, entry_price, exit_price, pnl_r, reason, legs, created_at
    FROM backtest_trades
    WHERE run_id=%s
    ORDER BY entry_time_ms ASC
    LIMIT %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id, limit))
            return _rows(cur)


def backtest_compare(database_url: str, *, run_id: str, limit_trades: int = 200) -> Dict[str, Any]:
    """按 run_id 聚合：信号->计划->订单/持仓->回测 trades 的闭环核对。"""
    q_signals = "SELECT count(*) FROM signals WHERE (payload->'ext'->>'run_id')=%s"
    q_plans = "SELECT count(*) FROM trade_plans WHERE (payload->'ext'->>'run_id')=%s"
    q_positions_open = "SELECT count(*) FROM positions WHERE status='OPEN' AND (meta->>'run_id')=%s"
    q_positions_closed = "SELECT count(*) FROM positions WHERE status='CLOSED' AND (meta->>'run_id')=%s"
    q_orders = """
        SELECT count(*) FROM orders
        WHERE (payload->>'run_id')=%s
           OR (payload->'trade_plan'->'payload'->'ext'->>'run_id')=%s
    """
    q_reports = """
        SELECT count(*) FROM execution_reports
        WHERE (payload->'detail'->>'run_id')=%s
    """
    from libs.backtest.repo import list_backtest_trades
    trades = list_backtest_trades(database_url, run_id=run_id, limit=limit_trades)

    # summary
    total = len(trades)
    win = sum(1 for t in trades if float(t.get("pnl_r") or 0.0) > 0)
    pnl_sum = sum(float(t.get("pnl_r") or 0.0) for t in trades)
    avg = pnl_sum / max(total, 1)

    # unique idempotency_key（用于联调核对）
    unique_idem = sorted({t.get("idempotency_key") for t in trades if t.get("idempotency_key")})

    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(q_signals, (run_id,))
            signals_cnt = int(cur.fetchone()[0])
            cur.execute(q_plans, (run_id,))
            plans_cnt = int(cur.fetchone()[0])
            cur.execute(q_positions_open, (run_id,))
            pos_open = int(cur.fetchone()[0])
            cur.execute(q_positions_closed, (run_id,))
            pos_closed = int(cur.fetchone()[0])
            cur.execute(q_orders, (run_id, run_id))
            orders_cnt = int(cur.fetchone()[0])
            cur.execute(q_reports, (run_id,))
            reports_cnt = int(cur.fetchone()[0])

    inconsistencies: List[str] = []
    if plans_cnt and total == 0:
        inconsistencies.append("存在 trade_plans 但 backtest_trades=0（可能尚未跑完回放，或 execution 未开启 BACKTEST/PAPER 撮合模拟）")
    if total and pos_open:
        inconsistencies.append("backtest_trades>0 但仍有 OPEN positions（可能回放未结束或退出条件未覆盖）")

    return {
        "run_id": run_id,
        "counts": {
            "signals": signals_cnt,
            "trade_plans": plans_cnt,
            "orders": orders_cnt,
            "execution_reports": reports_cnt,
            "positions_open": pos_open,
            "positions_closed": pos_closed,
            "backtest_trades": total,
            "unique_idempotency_keys": len(unique_idem),
        },
        "trades_summary": {"trades": total, "win_rate": win / max(total, 1), "avg_pnl_r": avg, "sum_pnl_r": pnl_sum},
        "sample_idempotency_keys": unique_idem[:20],
        "inconsistencies": inconsistencies,
        "trades": trades,
    }


def _count_jsonb_run_id(table: str, database_url: str, *, run_id: str) -> int:
    # payload->payload->ext->run_id
    sql = f"""
    SELECT COUNT(1) AS c
    FROM {table}
    WHERE (payload->'payload'->'ext'->>'run_id') = %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _count_orders_run_id(database_url: str, *, run_id: str) -> int:
    sql = """
    SELECT COUNT(1)
    FROM orders
    WHERE (payload->'ext'->>'run_id') = %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _count_positions_run_id(database_url: str, *, run_id: str, status: str | None = None) -> int:
    sql = """
    SELECT COUNT(1)
    FROM positions
    WHERE (meta->>'run_id') = %s
      AND (%s::text IS NULL OR status=%s)
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id, status, status))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def compare_backtest_run(database_url: str, *, run_id: str, limit_trades: int = 50) -> Dict[str, Any]:
    """用于 /v1/backtest-compare：把回放 run_id 的链路产物做一页统计。"""
    # 回放链路：signals/trade_plans/orders/execution_reports/positions/backtest_trades
    counts = {
        "signals": _count_jsonb_run_id("signals", database_url, run_id=run_id),
        "trade_plans": _count_jsonb_run_id("trade_plans", database_url, run_id=run_id),
        "orders": _count_orders_run_id(database_url, run_id=run_id),
        "execution_reports": _count_jsonb_run_id("execution_reports", database_url, run_id=run_id),
        "positions_open": _count_positions_run_id(database_url, run_id=run_id, status="OPEN"),
        "positions_closed": _count_positions_run_id(database_url, run_id=run_id, status="CLOSED"),
    }

    trades = list_backtest_trades(database_url, run_id=run_id, limit=limit_trades)

    hints: List[str] = []
    if counts["trade_plans"] > 0 and len(trades) == 0:
        hints.append("trade_plans>0 但 backtest_trades=0：请确认 execution_mode=BACKTEST/PAPER 且 execution-service 正在消费 stream:bar_close（paper_sim 才会产出 trades）。")
    if counts["positions_open"] > 0:
        hints.append("仍有 OPEN positions：回放可能尚未处理完成，或 TP/SL 未触发（可继续回放更多 bars / 调整区间）。")
    if counts["orders"] == 0 and counts["trade_plans"] > 0:
        hints.append("trade_plans>0 但 orders=0：请确认 execution-service 正在消费 stream:trade_plan。")

    return {"run_id": run_id, "counts": counts, "trades": trades, "hints": hints}
