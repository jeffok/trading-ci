# -*- coding: utf-8 -*-
"""execution-service DB 访问（Phase 3/4）

落库目标：
- orders：记录所有创建/撤销/成交的订单（含 purpose）
- positions：记录“由 trade_plan 驱动的持仓生命周期”
- execution_reports：对外可观察的执行回报事件（也会发布到 stream）

幂等：
- orders 使用 (idempotency_key, purpose) 唯一索引，避免重复下单
- positions 使用 idempotency_key 唯一约束，避免重复开仓
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from libs.db.pg import get_conn


def _json(x: Dict[str, Any]) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def upsert_order(database_url: str, *, order_id: str, idempotency_key: str, symbol: str, purpose: str,
                 side: str, order_type: str, qty: float, price: Optional[float], reduce_only: bool,
                 status: str, bybit_order_id: Optional[str], bybit_order_link_id: Optional[str], payload: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO orders(order_id, idempotency_key, symbol, purpose, side, order_type, qty, price, reduce_only, status, bybit_order_id, bybit_order_link_id, payload)
    VALUES (%(order_id)s,%(idempotency_key)s,%(symbol)s,%(purpose)s,%(side)s,%(order_type)s,%(qty)s,%(price)s,%(reduce_only)s,%(status)s,%(bybit_order_id)s,%(bybit_order_link_id)s,%(payload)s::jsonb)
    ON CONFLICT (idempotency_key, purpose) DO UPDATE SET
      status=excluded.status,
      bybit_order_id=excluded.bybit_order_id,
      bybit_order_link_id=excluded.bybit_order_link_id,
      updated_at=now(),
      payload=excluded.payload;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "order_id": order_id,
                "idempotency_key": idempotency_key,
                "symbol": symbol,
                "purpose": purpose,
                "side": side,
                "order_type": order_type,
                "qty": qty,
                "price": price,
                "reduce_only": reduce_only,
                "status": status,
                "bybit_order_id": bybit_order_id,
                "bybit_order_link_id": bybit_order_link_id,
                "payload": _json(payload),
            })
            conn.commit()


def save_position(database_url: str, *, position_id: str, idempotency_key: str, symbol: str, timeframe: str,
                  side: str, bias: str, qty_total: float, qty_runner: float, entry_price: float, primary_sl_price: float,
                  runner_stop_price: Optional[float], status: str, entry_close_time_ms: int, opened_at_ms: int,
                  secondary_rule_checked: bool, hist_entry: Optional[float], meta: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO positions(
      position_id, idempotency_key, symbol, timeframe, side, bias, qty_total, qty_runner,
      entry_price, primary_sl_price, runner_stop_price, status, entry_close_time_ms, opened_at_ms,
      secondary_rule_checked, hist_entry, meta
    ) VALUES (
      %(position_id)s,%(idempotency_key)s,%(symbol)s,%(timeframe)s,%(side)s,%(bias)s,%(qty_total)s,%(qty_runner)s,
      %(entry_price)s,%(primary_sl_price)s,%(runner_stop_price)s,%(status)s,%(entry_close_time_ms)s,%(opened_at_ms)s,
      %(secondary_rule_checked)s,%(hist_entry)s,%(meta)s::jsonb
    )
    ON CONFLICT (idempotency_key) DO UPDATE SET
      runner_stop_price=excluded.runner_stop_price,
      status=excluded.status,
      secondary_rule_checked=excluded.secondary_rule_checked,
      hist_entry=excluded.hist_entry,
      updated_at=now(),
      meta=excluded.meta;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "position_id": position_id,
                "idempotency_key": idempotency_key,
                "symbol": symbol,
                "timeframe": timeframe,
                "side": side,
                "bias": bias,
                "qty_total": qty_total,
                "qty_runner": qty_runner,
                "entry_price": entry_price,
                "primary_sl_price": primary_sl_price,
                "runner_stop_price": runner_stop_price,
                "status": status,
                "entry_close_time_ms": entry_close_time_ms,
                "opened_at_ms": opened_at_ms,
                "secondary_rule_checked": secondary_rule_checked,
                "hist_entry": hist_entry,
                "meta": _json(meta),
            })
            conn.commit()




# Backward-compatible alias: older modules expect `upsert_position`
upsert_position = save_position


def list_open_positions(database_url: str) -> List[Dict[str, Any]]:
    sql = """SELECT position_id, idempotency_key, symbol, timeframe, side, bias, qty_total, qty_runner,
                    entry_price, primary_sl_price, runner_stop_price, status, entry_close_time_ms,
                    opened_at_ms, secondary_rule_checked, hist_entry, meta
             FROM positions WHERE status='OPEN'"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    out = []
    for r in rows:
        out.append({
            "position_id": r[0],
            "idempotency_key": r[1],
            "symbol": r[2],
            "timeframe": r[3],
            "side": r[4],
            "bias": r[5],
            "qty_total": float(r[6]),
            "qty_runner": float(r[7]),
            "entry_price": float(r[8]),
            "primary_sl_price": float(r[9]),
            "runner_stop_price": float(r[10]) if r[10] is not None else None,
            "status": r[11],
            "entry_close_time_ms": int(r[12]),
            "opened_at_ms": int(r[13]),
            "secondary_rule_checked": bool(r[14]),
            "hist_entry": float(r[15]) if r[15] is not None else None,
            "meta": r[16],
        })
    return out


def get_position_by_idem(database_url: str, *, idempotency_key: str) -> Optional[Dict[str, Any]]:
    """按幂等键读取 position（Stage 6：paper/backtest 平仓需要）"""
    sql = """
    SELECT position_id, idempotency_key, symbol, timeframe, side, bias, qty_total, qty_runner,
           entry_price, primary_sl_price, runner_stop_price, status, entry_close_time_ms, opened_at_ms,
           secondary_rule_checked, hist_entry, meta
    FROM positions
    WHERE idempotency_key=%(idempotency_key)s
    LIMIT 1
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"idempotency_key": idempotency_key})
            row = cur.fetchone()
            if not row:
                return None
            return {
                "position_id": row[0],
                "idempotency_key": row[1],
                "symbol": row[2],
                "timeframe": row[3],
                "side": row[4],
                "bias": row[5],
                "qty_total": float(row[6]),
                "qty_runner": float(row[7]),
                "entry_price": float(row[8]),
                "primary_sl_price": float(row[9]),
                "runner_stop_price": float(row[10]) if row[10] is not None else None,
                "status": row[11],
                "entry_close_time_ms": int(row[12]),
                "opened_at_ms": int(row[13]),
                "secondary_rule_checked": bool(row[14]),
                "hist_entry": float(row[15]) if row[15] is not None else None,
                "meta": _json(row[16]),
            }



def save_execution_report(database_url: str, *, report_id: str, idempotency_key: str, symbol: str, typ: str, severity: str, payload: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO execution_reports(report_id, idempotency_key, symbol, type, severity, payload)
    VALUES (%(report_id)s,%(idempotency_key)s,%(symbol)s,%(type)s,%(severity)s,%(payload)s::jsonb);
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "report_id": report_id,
                "idempotency_key": idempotency_key,
                "symbol": symbol,
                "type": typ,
                "severity": severity,
                "payload": _json(payload),
            })
            conn.commit()


def list_orders_by_idem(database_url: str, *, idempotency_key: str) -> List[Dict[str, Any]]:
    """列出某个 trade_plan 对应的订单（用于对账/撤单/状态机）。"""
    sql = """
    SELECT order_id, purpose, side, order_type, qty, price, reduce_only, status, bybit_order_id, bybit_order_link_id, payload
    FROM orders
    WHERE idempotency_key=%(idempotency_key)s
    ORDER BY created_at ASC
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"idempotency_key": idempotency_key})
            rows = cur.fetchall()

    out = []
    for r in rows:
        out.append({
            "order_id": r[0],
            "purpose": r[1],
            "side": r[2],
            "order_type": r[3],
            "qty": float(r[4]),
            "price": float(r[5]) if r[5] is not None else None,
            "reduce_only": bool(r[6]),
            "status": r[7],
            "bybit_order_id": r[8],
            "bybit_order_link_id": r[9],
            "payload": r[10],
        })
    return out


def get_or_init_risk_state(database_url: str, *, trade_date: str, mode: str) -> Dict[str, Any]:
    """读取当天 risk_state；不存在则初始化一行。"""
    sql_sel = "SELECT trade_date, mode, starting_equity, current_equity, min_equity, max_equity, drawdown_pct, soft_halt, hard_halt, kill_switch, meta FROM risk_state WHERE trade_date=%(d)s"
    sql_ins = """
    INSERT INTO risk_state(trade_date, mode, starting_equity, current_equity, min_equity, max_equity, drawdown_pct, soft_halt, hard_halt, kill_switch, meta)
    VALUES (%(d)s,%(mode)s,NULL,NULL,NULL,NULL,NULL,false,false,false,'{}'::jsonb)
    ON CONFLICT (trade_date) DO NOTHING;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_ins, {"d": trade_date, "mode": mode})
            conn.commit()
            cur.execute(sql_sel, {"d": trade_date})
            row = cur.fetchone()
    if not row:
        return {"trade_date": trade_date, "mode": mode, "soft_halt": False, "hard_halt": False, "kill_switch": False, "meta": {}}
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
        "meta": row[10],
    }


def update_risk_state(database_url: str, *, trade_date: str, starting_equity: float, current_equity: float,
                      min_equity: float, max_equity: float, drawdown_pct: float,
                      soft_halt: bool, hard_halt: bool, kill_switch: bool, meta: Dict[str, Any]) -> None:
    sql = """
    UPDATE risk_state SET
      starting_equity=%(starting)s,
      current_equity=%(current)s,
      min_equity=%(min)s,
      max_equity=%(max)s,
      drawdown_pct=%(dd)s,
      soft_halt=%(soft)s,
      hard_halt=%(hard)s,
      kill_switch=%(kill)s,
      meta=%(meta)s::jsonb,
      updated_at=now()
    WHERE trade_date=%(d)s;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "d": trade_date,
                "starting": starting_equity,
                "current": current_equity,
                "min": min_equity,
                "max": max_equity,
                "dd": drawdown_pct,
                "soft": soft_halt,
                "hard": hard_halt,
                "kill": kill_switch,
                "meta": _json(meta),
            })
            conn.commit()


def insert_risk_event(database_url: str, *, event_id: str, trade_date: str, ts_ms: int, typ: str, severity: str, detail: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO risk_events(event_id, trade_date, ts_ms, type, severity, detail)
    VALUES (%(id)s,%(d)s,%(ts)s,%(t)s,%(s)s,%(detail)s::jsonb);
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"id": event_id, "d": trade_date, "ts": ts_ms, "t": typ, "s": severity, "detail": _json(detail)})
            conn.commit()


def count_open_positions(database_url: str) -> int:
    sql = "SELECT COUNT(1) FROM positions WHERE status='OPEN'"
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            n = cur.fetchone()[0]
    return int(n)


def find_open_position_same_direction(database_url: str, *, symbol: str, side: str) -> Optional[Dict[str, Any]]:
    """同币种同向互斥：查找是否已有 OPEN 仓位。"""
    sql = """
    SELECT position_id, idempotency_key, symbol, timeframe, side, status, entry_price, qty_total, opened_at_ms, meta
    FROM positions
    WHERE status='OPEN' AND symbol=%(symbol)s AND side=%(side)s
    ORDER BY opened_at_ms DESC
    LIMIT 1
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"symbol": symbol, "side": side})
            row = cur.fetchone()
    if not row:
        return None
    return {
        "position_id": row[0],
        "idempotency_key": row[1],
        "symbol": row[2],
        "timeframe": row[3],
        "side": row[4],
        "status": row[5],
        "entry_price": row[6],
        "qty_total": float(row[7]) if row[7] is not None else None,
        "opened_at_ms": row[8],
        "meta": row[9],
    }


def upsert_cooldown(database_url: str, *, cooldown_id: str, symbol: str, side: str, timeframe: str,
                    reason: str, until_ts_ms: int, meta: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO cooldowns(cooldown_id, symbol, side, timeframe, reason, until_ts_ms, meta)
    VALUES (%(id)s,%(symbol)s,%(side)s,%(tf)s,%(reason)s,%(until)s,%(meta)s::jsonb)
    ON CONFLICT (cooldown_id) DO NOTHING;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"id": cooldown_id, "symbol": symbol, "side": side, "tf": timeframe,
                              "reason": reason, "until": int(until_ts_ms), "meta": _json(meta)})
            conn.commit()


def get_active_cooldown(database_url: str, *, symbol: str, side: str, timeframe: str, now_ms: int) -> Optional[Dict[str, Any]]:
    sql = """
    SELECT cooldown_id, reason, until_ts_ms, meta
    FROM cooldowns
    WHERE symbol=%(symbol)s AND side=%(side)s AND timeframe=%(tf)s AND until_ts_ms > %(now)s
    ORDER BY until_ts_ms DESC
    LIMIT 1
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"symbol": symbol, "side": side, "tf": timeframe, "now": int(now_ms)})
            row = cur.fetchone()
    if not row:
        return None
    return {"cooldown_id": row[0], "reason": row[1], "until_ts_ms": row[2], "meta": row[3]}


def mark_position_closed(database_url: str, *, position_id: str, closed_at_ms: int, exit_reason: str, meta: Dict[str, Any]) -> None:
    sql = """
    UPDATE positions SET status='CLOSED', closed_at_ms=%(closed)s, exit_reason=%(reason)s, meta=%(meta)s::jsonb
    WHERE position_id=%(pid)s;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"pid": position_id, "closed": int(closed_at_ms), "reason": exit_reason, "meta": _json(meta)})
            conn.commit()


# ---------------- Stage 4：执行复盘增强（execution_traces / account_snapshots） ----------------

SQL_INSERT_TRACE = """
INSERT INTO execution_traces(trace_row_id, trace_id, idempotency_key, ts_ms, stage, detail)
VALUES (%(row)s,%(trace)s,%(idem)s,%(ts)s,%(stage)s,%(detail)s::jsonb)
ON CONFLICT (trace_row_id) DO NOTHING;
"""


def insert_execution_trace(database_url: str, *, trace_row_id: str, trace_id: str, idempotency_key: str, ts_ms: int, stage: str, detail: Dict[str, Any]) -> None:
    """写入执行流程 trace（不影响执行主流程）。"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_INSERT_TRACE, {
                "row": trace_row_id,
                "trace": trace_id,
                "idem": idempotency_key,
                "ts": int(ts_ms),
                "stage": stage,
                "detail": json.dumps(detail, ensure_ascii=False),
            })
            conn.commit()


SQL_INSERT_SNAPSHOT = """
INSERT INTO account_snapshots(snapshot_id, ts_ms, trade_date, mode, balance_usdt, equity_usdt, available_usdt, unrealized_pnl, position_count, payload)
VALUES (%(id)s,%(ts)s,%(d)s,%(mode)s,%(bal)s,%(eq)s,%(avail)s,%(upnl)s,%(pc)s,%(payload)s::jsonb)
ON CONFLICT (snapshot_id) DO NOTHING;
"""


def insert_account_snapshot(database_url: str, *, snapshot_id: str, ts_ms: int, trade_date: str, mode: str,
                           balance_usdt: float | None, equity_usdt: float | None, available_usdt: float | None,
                           unrealized_pnl: float | None, position_count: int, payload: Dict[str, Any]) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_INSERT_SNAPSHOT, {
                "id": snapshot_id,
                "ts": int(ts_ms),
                "d": trade_date,
                "mode": mode,
                "bal": balance_usdt,
                "eq": equity_usdt,
                "avail": available_usdt,
                "upnl": unrealized_pnl,
                "pc": int(position_count),
                "payload": json.dumps(payload, ensure_ascii=False),
            })
            conn.commit()
