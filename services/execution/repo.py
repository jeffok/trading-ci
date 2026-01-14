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
import hashlib
from typing import Any, Dict, List, Optional

from libs.common.time import now_ms
from libs.common.config import settings

from libs.db.pg import get_conn


def _json(x: Dict[str, Any]) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def upsert_order(
    database_url: str,
    *,
    order_id: str,
    idempotency_key: str,
    symbol: str,
    purpose: str,
    side: str,
    order_type: str,
    qty: float,
    price: Optional[float],
    reduce_only: bool,
    status: str,
    bybit_order_id: Optional[str],
    bybit_order_link_id: Optional[str],
    payload: Dict[str, Any],
    submitted_at_ms: Optional[int] = None,
    retry_count: int = 0,
    filled_qty: Optional[float] = None,
    avg_price: Optional[float] = None,
    last_fill_at_ms: Optional[int] = None,
) -> None:
    """Upsert order record.

    Note: orders table is schema-light; payload is the canonical carrier. These helper columns
    exist to support Stage 9 abnormal handling (timeouts/partial fills) and quick queries.
    """
    sql = """
    INSERT INTO orders(
      order_id, idempotency_key, symbol, purpose, side, order_type, qty, price, reduce_only,
      status, bybit_order_id, bybit_order_link_id, payload,
      submitted_at_ms, retry_count, filled_qty, avg_price, last_fill_at_ms
    )
    VALUES (
      %(order_id)s,%(idempotency_key)s,%(symbol)s,%(purpose)s,%(side)s,%(order_type)s,%(qty)s,%(price)s,%(reduce_only)s,
      %(status)s,%(bybit_order_id)s,%(bybit_order_link_id)s,%(payload)s::jsonb,
      %(submitted_at_ms)s,%(retry_count)s,%(filled_qty)s,%(avg_price)s,%(last_fill_at_ms)s
    )
    ON CONFLICT (idempotency_key, purpose) DO UPDATE SET
      status=excluded.status,
      bybit_order_id=excluded.bybit_order_id,
      bybit_order_link_id=excluded.bybit_order_link_id,
      submitted_at_ms=COALESCE(excluded.submitted_at_ms, orders.submitted_at_ms),
      retry_count=GREATEST(orders.retry_count, excluded.retry_count),
      filled_qty=COALESCE(excluded.filled_qty, orders.filled_qty),
      avg_price=COALESCE(excluded.avg_price, orders.avg_price),
      last_fill_at_ms=COALESCE(excluded.last_fill_at_ms, orders.last_fill_at_ms),
      updated_at=now(),
      payload=excluded.payload;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                {
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
                    "submitted_at_ms": submitted_at_ms,
                    "retry_count": retry_count,
                    "filled_qty": filled_qty,
                    "avg_price": avg_price,
                    "last_fill_at_ms": last_fill_at_ms,
                },
            )
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


def list_open_positions(database_url: str, *, limit: int = 500) -> List[Dict[str, Any]]:
    """List OPEN positions.

    `limit` exists mainly for observability modules (snapshotter/backtest) to avoid loading too much.
    """
    sql = """SELECT position_id, idempotency_key, symbol, timeframe, side, bias, qty_total, qty_runner,
                    entry_price, primary_sl_price, runner_stop_price, status, entry_close_time_ms,
                    opened_at_ms, secondary_rule_checked, hist_entry, meta
             FROM positions WHERE status='OPEN'
             ORDER BY opened_at_ms DESC
             LIMIT %(limit)s"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"limit": int(limit)})
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
    """Persist execution report.

    Backward compatible: still writes legacy columns (type/severity/payload),
    while also writing schema-aligned columns (plan_id/status/...) if present.
    """
    # If caller passes the full event envelope (recommended), pull from event['payload'].
    ev_payload = payload.get("payload") if isinstance(payload, dict) else None
    if isinstance(ev_payload, dict):
        p = ev_payload
    else:
        p = payload or {}

    sql = """
    INSERT INTO execution_reports(
      report_id, idempotency_key, symbol, type, severity, payload,
      plan_id, status, timeframe, filled_qty, avg_price, reason,
      retry_count, latency_ms, slippage_bps, fill_ratio, ext
    )
    VALUES (
      %(report_id)s,%(idempotency_key)s,%(symbol)s,%(type)s,%(severity)s,%(payload)s::jsonb,
      %(plan_id)s,%(status)s,%(timeframe)s,%(filled_qty)s,%(avg_price)s,%(reason)s,
      %(retry_count)s,%(latency_ms)s,%(slippage_bps)s,%(fill_ratio)s,%(ext)s::jsonb
    );
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
                "plan_id": p.get("plan_id"),
                "status": p.get("status"),
                "timeframe": p.get("timeframe"),
                "filled_qty": p.get("filled_qty"),
                "avg_price": p.get("avg_price"),
                "reason": p.get("reason"),
                "retry_count": p.get("retry_count"),
                "latency_ms": p.get("latency_ms"),
                "slippage_bps": p.get("slippage_bps"),
                "fill_ratio": p.get("fill_ratio"),
                "ext": _json(p.get("ext") or {}),
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


def list_orders_by_status(database_url: str, *, status: str, purpose: Optional[str] = None) -> List[Dict[str, Any]]:
    """List orders by status (and optional purpose)."""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            if purpose:
                cur.execute(
                    """SELECT order_id, idempotency_key, symbol, purpose, side, order_type, qty, price, reduce_only,
                              status, bybit_order_id, bybit_order_link_id, created_at, updated_at,
                              submitted_at_ms, retry_count, filled_qty, avg_price, last_fill_at_ms, payload
                         FROM orders
                        WHERE status=%s AND purpose=%s
                        ORDER BY updated_at DESC""",
                    (status, purpose),
                )
            else:
                cur.execute(
                    """SELECT order_id, idempotency_key, symbol, purpose, side, order_type, qty, price, reduce_only,
                              status, bybit_order_id, bybit_order_link_id, created_at, updated_at,
                              submitted_at_ms, retry_count, filled_qty, avg_price, last_fill_at_ms, payload
                         FROM orders
                        WHERE status=%s
                        ORDER BY updated_at DESC""",
                    (status,),
                )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in rows]


def insert_fill(database_url: str, *, fill_id: str, order_id: str, idempotency_key: str, symbol: str,
                purpose: str, side: str, exec_qty: float, exec_price: float, exec_fee: Optional[float],
                exec_time_ms: Optional[int], bybit_exec_id: Optional[str], bybit_order_id: Optional[str],
                bybit_order_link_id: Optional[str], payload: Dict[str, Any]) -> None:
    """Insert a single fill record (idempotent)."""
    with get_conn(database_url) as conn:
        conn.execute(
            """INSERT INTO fills(
                   fill_id, order_id, idempotency_key, symbol, purpose, side,
                   exec_qty, exec_price, exec_fee, exec_time_ms,
                   bybit_exec_id, bybit_order_id, bybit_order_link_id, payload
                 )
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                 ON CONFLICT (fill_id) DO NOTHING""",
            (
                fill_id,
                order_id,
                idempotency_key,
                symbol,
                purpose,
                side,
                float(exec_qty),
                float(exec_price),
                float(exec_fee) if exec_fee is not None else None,
                int(exec_time_ms) if exec_time_ms is not None else None,
                bybit_exec_id,
                bybit_order_id,
                bybit_order_link_id,
                _json(payload),
            ),
        )
        conn.commit()


def apply_fill_to_order(database_url: str, *, order_id: str, exec_qty: float, exec_price: float,
                        exec_time_ms: Optional[int]) -> None:
    """Update helper aggregate columns on orders for quick access."""
    with get_conn(database_url) as conn:
        row = conn.execute("""SELECT filled_qty, avg_price FROM orders WHERE order_id=%s""", (order_id,)).fetchone()
        old_qty = float(row[0]) if row and row[0] is not None else 0.0
        old_avg = float(row[1]) if row and row[1] is not None else 0.0
        new_qty = old_qty + float(exec_qty)
        new_avg = None if new_qty <= 0 else (old_avg * old_qty + float(exec_price) * float(exec_qty)) / new_qty
        conn.execute(
            """UPDATE orders
                   SET filled_qty=%s,
                       avg_price=%s,
                       last_fill_at_ms=%s,
                       updated_at=now()
                 WHERE order_id=%s""",
            (new_qty, new_avg, int(exec_time_ms) if exec_time_ms is not None else int(now_ms()), order_id),
        )
        conn.commit()




def get_order_fill_progress(database_url: str, *, order_id: str) -> Dict[str, Any] | None:
    """Return order qty and filled_qty helper values."""
    with get_conn(database_url) as conn:
        row = conn.execute(
            """SELECT qty, filled_qty, status, purpose, symbol
                 FROM orders WHERE order_id=%s LIMIT 1""",
            (order_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "qty": float(row[0]) if row[0] is not None else 0.0,
        "filled_qty": float(row[1]) if row[1] is not None else 0.0,
        "status": row[2],
        "purpose": row[3],
        "symbol": row[4],
    }

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


def merge_risk_state_meta(database_url: str, *, trade_date: str, meta_patch: Dict[str, Any]) -> None:
    """Merge meta patch into risk_state.meta (JSONB ||).

    This is used for small auxiliary counters (e.g. consecutive_loss_count) without
    forcing callers to load/overwrite the whole risk_state row.
    """
    sql = """
    UPDATE risk_state
    SET meta = COALESCE(meta, '{}'::jsonb) || %(patch)s::jsonb,
        updated_at = now()
    WHERE trade_date=%(d)s;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"d": trade_date, "patch": _json(meta_patch or {})})
            conn.commit()


def insert_risk_event(
    database_url: str,
    *,
    event_id: str,
    trade_date: str,
    ts_ms: int,
    typ: str,
    severity: str,
    detail: Dict[str, Any],
    symbol: str | None = None,
    retry_after_ms: int | None = None,
    ext: Dict[str, Any] | None = None,
) -> None:
    """Persist risk event.

    Normalizes type/severity to schema enums and writes optional columns.
    """
    from libs.mq.risk_normalize import normalize_risk_type, normalize_risk_severity

    t = normalize_risk_type(typ)
    s = normalize_risk_severity(severity)
    sql = """
    INSERT INTO risk_events(event_id, trade_date, ts_ms, type, severity, detail, symbol, retry_after_ms, ext)
    VALUES (%(id)s,%(d)s,%(ts)s,%(t)s,%(s)s,%(detail)s::jsonb,%(symbol)s,%(retry_after_ms)s,%(ext)s::jsonb);
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                {
                    "id": event_id,
                    "d": trade_date,
                    "ts": int(ts_ms),
                    "t": t,
                    "s": s,
                    "detail": _json(detail or {}),
                    "symbol": symbol,
                    "retry_after_ms": int(retry_after_ms) if retry_after_ms is not None else None,
                    "ext": _json(ext or {}),
                },
            )
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


# ---------------------------
# Stage 7: WS audit + best-effort sync
# ---------------------------

def insert_ws_event(database_url: str, *, topic: str, symbol: Optional[str], payload: Dict[str, Any]) -> None:
    """将原始 WS 消息落库，便于审计与排障（不参与交易逻辑）。"""
    with get_conn(database_url) as conn:
        conn.execute(
            """
            INSERT INTO ws_events(topic, symbol, received_at, payload)
            VALUES (%s, %s, now(), %s::jsonb)
            """,
            (topic, symbol, _json(payload)),
        )
        conn.commit()


# ---------------------------
# Stage 10: wallet snapshots (WS + REST) + drift support
# ---------------------------

SQL_INSERT_WALLET_SNAPSHOT = """
INSERT INTO wallet_snapshots(snapshot_id, ts_ms, source, balance_usdt, equity_usdt, available_usdt, payload)
VALUES (%(id)s,%(ts)s,%(src)s,%(bal)s,%(eq)s,%(avail)s,%(payload)s::jsonb)
ON CONFLICT (snapshot_id) DO NOTHING;
"""


def insert_wallet_snapshot(
    database_url: str,
    *,
    snapshot_id: str,
    ts_ms: int,
    source: str,
    balance_usdt: float | None,
    equity_usdt: float | None,
    available_usdt: float | None,
    payload: Dict[str, Any],
) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                SQL_INSERT_WALLET_SNAPSHOT,
                {
                    "id": snapshot_id,
                    "ts": int(ts_ms),
                    "src": str(source),
                    "bal": balance_usdt,
                    "eq": equity_usdt,
                    "avail": available_usdt,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
            conn.commit()


def get_latest_wallet_snapshot(database_url: str, *, source: str) -> Optional[Dict[str, Any]]:
    sql = """SELECT snapshot_id, ts_ms, source, balance_usdt, equity_usdt, available_usdt, payload
             FROM wallet_snapshots
             WHERE source=%(src)s
             ORDER BY ts_ms DESC
             LIMIT 1"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"src": str(source)})
            row = cur.fetchone()
    if not row:
        return None
    return {
        "snapshot_id": row[0],
        "ts_ms": int(row[1]),
        "source": row[2],
        "balance_usdt": float(row[3]) if row[3] is not None else None,
        "equity_usdt": float(row[4]) if row[4] is not None else None,
        "available_usdt": float(row[5]) if row[5] is not None else None,
        "payload": row[6],
    }


def _parse_wallet_ws_payload(payload: Any, *, coin: str = "USDT") -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Parse Bybit private WS wallet payload best-effort.

    V5 wallet topic typically contains a list of accounts, each with `coin` list.
    We only extract the requested `coin` (default USDT).
    """
    bal = eq = avail = None
    try:
        items = payload if isinstance(payload, list) else [payload]
        for it in items:
            if not isinstance(it, dict):
                continue
            coins = it.get("coin") or it.get("coins") or []
            if not isinstance(coins, list):
                continue
            for c in coins:
                if not isinstance(c, dict):
                    continue
                if str(c.get("coin") or c.get("currency") or "").upper() != str(coin).upper():
                    continue
                if c.get("walletBalance") is not None and str(c.get("walletBalance")) != "":
                    bal = float(c.get("walletBalance"))
                if c.get("equity") is not None and str(c.get("equity")) != "":
                    eq = float(c.get("equity"))
                # available fields vary
                for k in ("availableToWithdraw", "availableBalance", "availableToBorrow", "available"):
                    if c.get(k) is not None and str(c.get(k)) != "":
                        avail = float(c.get(k))
                        break
                return bal, eq, avail
    except Exception:
        return bal, eq, avail
    return bal, eq, avail


def upsert_wallet_snapshot_from_ws(database_url: str, *, payload: Any, ts_ms: Optional[int] = None) -> None:
    """Persist wallet snapshot from WS (for drift detection).

    This is observability-only and must never block trading.
    """
    t = int(ts_ms or now_ms())
    coin = str(getattr(settings, "bybit_wallet_coin", "USDT"))
    bal, eq, avail = _parse_wallet_ws_payload(payload, coin=coin)
    snapshot_id = hashlib.sha256(f"WS|{t}|{coin}".encode("utf-8")).hexdigest()
    insert_wallet_snapshot(
        database_url,
        snapshot_id=snapshot_id,
        ts_ms=t,
        source="WS",
        balance_usdt=bal,
        equity_usdt=eq,
        available_usdt=avail,
        payload={"coin": coin, "raw": payload},
    )


def get_order_by_bybit_ids(database_url: str, *, bybit_order_id: Optional[str], bybit_order_link_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """根据 bybit_order_id 或 order_link_id 反查本地 orders。"""
    if not bybit_order_id and not bybit_order_link_id:
        return None
    with get_conn(database_url) as conn:
        row = None
        if bybit_order_id:
            row = conn.execute(
                """SELECT order_id, idempotency_key, symbol, purpose, payload
                     FROM orders WHERE bybit_order_id = %s LIMIT 1""",
                (bybit_order_id,),
            ).fetchone()
        if row is None and bybit_order_link_id:
            row = conn.execute(
                """SELECT order_id, idempotency_key, symbol, purpose, payload
                     FROM orders WHERE bybit_order_link_id = %s LIMIT 1""",
                (bybit_order_link_id,),
            ).fetchone()
        if row is None:
            return None
        # psycopg returns tuple-like; access by index
        return {
            "order_id": row[0],
            "idempotency_key": row[1],
            "symbol": row[2],
            "purpose": row[3],
            "payload": row[4],
        }


def update_order_status_from_ws(
    database_url: str,
    *,
    order_id: str,
    new_status: str,
    bybit_order_id: Optional[str],
    bybit_order_link_id: Optional[str],
    ws_payload: Dict[str, Any],
) -> None:
    """用 WS 事件更新订单状态（best-effort）。"""
    patch = {"ws_last_update_ms": int(now_ms()), "ws_payload": ws_payload}
    # Stage 9: persist cumExecQty/avgPrice helpers if present
    try:
        cum_qty = ws_payload.get("cumExecQty") or ws_payload.get("cum_exec_qty")
        avg_p = ws_payload.get("avgPrice") or ws_payload.get("avg_price")
        if cum_qty is not None and str(cum_qty) != "":
            patch["cum_exec_qty"] = float(cum_qty)
        if avg_p is not None and str(avg_p) != "":
            patch["avg_price"] = float(avg_p)
    except Exception:
        pass
    with get_conn(database_url) as conn:
        conn.execute(
            """UPDATE orders
                   SET status = %s,
                       bybit_order_id = COALESCE(%s, bybit_order_id),
                       bybit_order_link_id = COALESCE(%s, bybit_order_link_id),
                       payload = payload || %s::jsonb,
                       updated_at = now()
                 WHERE order_id = %s""",
            (new_status, bybit_order_id, bybit_order_link_id, _json(patch), order_id),
        )
        conn.commit()


def append_order_fill_from_ws(database_url: str, *, order_id: str, fill: Dict[str, Any]) -> None:
    """将 execution fill 追加到 orders.payload.fills（数组）。"""
    with get_conn(database_url) as conn:
        conn.execute(
            """UPDATE orders
                   SET payload = jsonb_set(
                        payload,
                        '{fills}',
                        COALESCE(payload->'fills', '[]'::jsonb) || %s::jsonb,
                        true
                   ),
                       updated_at = now()
                 WHERE order_id = %s""",
            (_json([fill]), order_id),
        )
        conn.commit()

    # Stage 9: persist fill into dedicated fills table + update helper aggregates (best-effort)
    try:
        bybit_exec_id = fill.get("execId") or fill.get("exec_id") or fill.get("id")
        fill_id = str(bybit_exec_id) if bybit_exec_id else new_event_id()
        insert_fill(
            database_url,
            fill_id=fill_id,
            order_id=order_id,
            idempotency_key=str(fill.get("idempotency_key") or ""),
            symbol=str(fill.get("symbol") or ""),
            purpose=str(fill.get("purpose") or ""),
            side=str(fill.get("side") or ""),
            exec_qty=float(fill.get("exec_qty") or fill.get("qty") or 0.0),
            exec_price=float(fill.get("exec_price") or fill.get("price") or 0.0),
            exec_fee=(float(fill.get("exec_fee")) if fill.get("exec_fee") is not None and str(fill.get("exec_fee")) != "" else None),
            exec_time_ms=(int(fill.get("exec_time_ms")) if fill.get("exec_time_ms") is not None and str(fill.get("exec_time_ms")) != "" else None),
            bybit_exec_id=str(bybit_exec_id) if bybit_exec_id else None,
            bybit_order_id=str(fill.get("bybit_order_id") or "") or None,
            bybit_order_link_id=str(fill.get("bybit_order_link_id") or "") or None,
            payload=fill,
        )
        apply_fill_to_order(
            database_url,
            order_id=order_id,
            exec_qty=float(fill.get("exec_qty") or fill.get("qty") or 0.0),
            exec_price=float(fill.get("exec_price") or fill.get("price") or 0.0),
            exec_time_ms=(int(fill.get("exec_time_ms")) if fill.get("exec_time_ms") is not None and str(fill.get("exec_time_ms")) != "" else None),
        )
    except Exception:
        # don't fail the WS pipeline
        pass





def merge_position_meta_by_idem(database_url: str, *, idempotency_key: str, patch: Dict[str, Any]) -> None:
    """Merge meta patch into positions.meta for a given idempotency_key (best-effort)."""
    if not idempotency_key:
        return
    with get_conn(database_url) as conn:
        conn.execute(
            """UPDATE positions
                   SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb,
                       updated_at = now()
                 WHERE idempotency_key = %s""",
            (_json(patch or {}), idempotency_key),
        )
        conn.commit()


def merge_open_position_meta_by_symbol(database_url: str, *, symbol: str, patch: Dict[str, Any], timeframe: Optional[str] = None) -> None:
    """Merge meta patch into OPEN positions for a symbol (optionally timeframe)."""
    if not symbol:
        return
    with get_conn(database_url) as conn:
        if timeframe:
            conn.execute(
                """UPDATE positions
                       SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb,
                           updated_at = now()
                     WHERE status='OPEN' AND symbol=%s AND timeframe=%s""",
                (_json(patch or {}), symbol, timeframe),
            )
        else:
            conn.execute(
                """UPDATE positions
                       SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb,
                           updated_at = now()
                     WHERE status='OPEN' AND symbol=%s""",
                (_json(patch or {}), symbol),
            )
        conn.commit()

def upsert_position_snapshot_from_ws(database_url: str, *, payload: Dict[str, Any]) -> None:
    """WS position 快照落库（附加在 risk_state.meta.position_ws）。"""
    sym = payload.get("symbol") or payload.get("s")
    if not sym:
        return
    with get_conn(database_url) as conn:
        # 用 risk_state 保存最新 WS 仓位快照（不影响策略）
        rs = conn.execute(
            """SELECT trade_date, meta FROM risk_state WHERE trade_date = CURRENT_DATE LIMIT 1"""
        ).fetchone()
        meta = rs[1] if rs else {}
        meta = meta or {}
        meta.setdefault("position_ws", {})
        meta["position_ws"][str(sym)] = payload
        if rs:
            conn.execute("""UPDATE risk_state SET meta=%s::jsonb WHERE trade_date=CURRENT_DATE""", (_json(meta),))
        else:
            conn.execute("""INSERT INTO risk_state(trade_date, meta) VALUES (CURRENT_DATE, %s::jsonb)""", (_json(meta),))
        conn.commit()


# Also annotate our OPEN positions meta (symbol-level) for reconcile drift checks (best-effort).
try:
    merge_open_position_meta_by_symbol(
        database_url,
        symbol=str(sym),
        patch={"ws_position": payload, "ws_position_updated_ms": int(now_ms())},
    )
except Exception:
    pass


GET_RUNTIME_FLAG_SQL = """
SELECT value, updated_at
FROM runtime_flags
WHERE name=%(name)s
LIMIT 1;
"""

def get_runtime_flag(database_url: str, *, name: str) -> Optional[dict]:
    """Read a runtime flag value from DB (Stage 11)."""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(GET_RUNTIME_FLAG_SQL, {"name": name})
            r = cur.fetchone()
            if not r:
                return None
            return {"value": str(r[0]), "updated_at": r[1]}
