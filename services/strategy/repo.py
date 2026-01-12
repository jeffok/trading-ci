# -*- coding: utf-8 -*-
"""strategy-service 的 DB 访问（Phase 2）

功能：
- 读取 bars（用于指标与结构识别）
- 落库 signals / trade_plans（JSONB）

说明：
- Phase 2 采用 JSONB 存储 payload，减少表结构频繁变更的成本。
- 仍然保留关键字段列（symbol/timeframe/close_time_ms 等）便于索引与查询。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from libs.db.pg import get_conn


GET_BARS_SQL = """
SELECT open, high, low, close, volume, turnover, open_time_ms, close_time_ms
FROM bars
WHERE symbol=%(symbol)s AND timeframe=%(timeframe)s
ORDER BY close_time_ms ASC
LIMIT %(limit)s
"""


def get_bars(database_url: str, *, symbol: str, timeframe: str, limit: int = 500) -> List[Dict[str, Any]]:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(GET_BARS_SQL, {"symbol": symbol, "timeframe": timeframe, "limit": limit})
            rows = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "open": float(r[0]),
            "high": float(r[1]),
            "low": float(r[2]),
            "close": float(r[3]),
            "volume": float(r[4]),
            "turnover": float(r[5]) if r[5] is not None else None,
            "open_time_ms": int(r[6]),
            "close_time_ms": int(r[7]),
        })
    return out


UPSERT_SIGNAL_SQL = """
INSERT INTO signals (
  signal_id, idempotency_key, symbol, timeframe, close_time_ms,
  bias, vegas_state, hit_count, hits, signal_score, payload
) VALUES (
  %(signal_id)s, %(idempotency_key)s, %(symbol)s, %(timeframe)s, %(close_time_ms)s,
  %(bias)s, %(vegas_state)s, %(hit_count)s, %(hits)s::jsonb, %(signal_score)s, %(payload)s::jsonb
)
ON CONFLICT (idempotency_key) DO NOTHING;
"""


def save_signal(database_url: str, *, signal_id: str, idempotency_key: str, symbol: str, timeframe: str, close_time_ms: int,
                bias: str, vegas_state: str, hit_count: int, hits: List[str], signal_score: Optional[int], payload: Dict[str, Any]) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(UPSERT_SIGNAL_SQL, {
                "signal_id": signal_id,
                "idempotency_key": idempotency_key,
                "symbol": symbol,
                "timeframe": timeframe,
                "close_time_ms": close_time_ms,
                "bias": bias,
                "vegas_state": vegas_state,
                "hit_count": hit_count,
                "hits": json.dumps(hits, ensure_ascii=False),
                "signal_score": signal_score,
                "payload": json.dumps(payload, ensure_ascii=False),
            })
            conn.commit()


UPSERT_TRADE_PLAN_SQL = """
INSERT INTO trade_plans (
  plan_id, idempotency_key, symbol, timeframe, close_time_ms,
  side, entry_price, primary_sl_price, payload
) VALUES (
  %(plan_id)s, %(idempotency_key)s, %(symbol)s, %(timeframe)s, %(close_time_ms)s,
  %(side)s, %(entry_price)s, %(primary_sl_price)s, %(payload)s::jsonb
)
ON CONFLICT (idempotency_key) DO NOTHING;
"""


def save_trade_plan(database_url: str, *, plan_id: str, idempotency_key: str, symbol: str, timeframe: str, close_time_ms: int,
                    side: str, entry_price: float, primary_sl_price: float, payload: Dict[str, Any]) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(UPSERT_TRADE_PLAN_SQL, {
                "plan_id": plan_id,
                "idempotency_key": idempotency_key,
                "symbol": symbol,
                "timeframe": timeframe,
                "close_time_ms": close_time_ms,
                "side": side,
                "entry_price": entry_price,
                "primary_sl_price": primary_sl_price,
                "payload": json.dumps(payload, ensure_ascii=False),
            })
            conn.commit()


# ---------------- Stage 3：复盘中间产物落库 ----------------

UPSERT_SNAPSHOT_SQL = """
INSERT INTO indicator_snapshots(snapshot_id, symbol, timeframe, close_time_ms, kind, payload)
VALUES (%(id)s,%(symbol)s,%(tf)s,%(ct)s,%(kind)s,%(payload)s::jsonb)
ON CONFLICT (snapshot_id) DO NOTHING;
"""


def upsert_indicator_snapshot(database_url: str, *, snapshot_id: str, symbol: str, timeframe: str, close_time_ms: int, kind: str, payload: Dict[str, Any]) -> None:
    """写入指标快照（不参与决策，仅用于复盘）。"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(UPSERT_SNAPSHOT_SQL, {
                "id": snapshot_id,
                "symbol": symbol,
                "tf": timeframe,
                "ct": int(close_time_ms),
                "kind": kind,
                "payload": json.dumps(payload, ensure_ascii=False),
            })
            conn.commit()


UPSERT_SETUP_SQL = """
INSERT INTO setups(setup_id, idempotency_key, symbol, timeframe, close_time_ms, bias, setup_type, payload)
VALUES (%(id)s,%(idem)s,%(symbol)s,%(tf)s,%(ct)s,%(bias)s,%(typ)s,%(payload)s::jsonb)
ON CONFLICT (idempotency_key) DO NOTHING;
"""


def upsert_setup(database_url: str, *, setup_id: str, idempotency_key: str, symbol: str, timeframe: str, close_time_ms: int, bias: str, setup_type: str, payload: Dict[str, Any]) -> None:
    """写入 setup（结构识别结果）。"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(UPSERT_SETUP_SQL, {
                "id": setup_id,
                "idem": idempotency_key,
                "symbol": symbol,
                "tf": timeframe,
                "ct": int(close_time_ms),
                "bias": bias,
                "typ": setup_type,
                "payload": json.dumps(payload, ensure_ascii=False),
            })
            conn.commit()


UPSERT_TRIGGER_SQL = """
INSERT INTO triggers(trigger_id, idempotency_key, setup_id, symbol, timeframe, close_time_ms, bias, hits, payload)
VALUES (%(id)s,%(idem)s,%(setup)s,%(symbol)s,%(tf)s,%(ct)s,%(bias)s,%(hits)s::jsonb,%(payload)s::jsonb)
ON CONFLICT (idempotency_key) DO NOTHING;
"""


def upsert_trigger(database_url: str, *, trigger_id: str, idempotency_key: str, setup_id: str, symbol: str, timeframe: str, close_time_ms: int, bias: str, hits: List[str], payload: Dict[str, Any]) -> None:
    """写入 trigger（确认层命中项）。"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(UPSERT_TRIGGER_SQL, {
                "id": trigger_id,
                "idem": idempotency_key,
                "setup": setup_id,
                "symbol": symbol,
                "tf": timeframe,
                "ct": int(close_time_ms),
                "bias": bias,
                "hits": json.dumps(hits, ensure_ascii=False),
                "payload": json.dumps(payload, ensure_ascii=False),
            })
            conn.commit()


UPSERT_PIVOT_SQL = """
INSERT INTO pivots(pivot_id, setup_id, symbol, timeframe, pivot_time_ms, pivot_price, pivot_type, segment_no, meta)
VALUES (%(id)s,%(setup)s,%(symbol)s,%(tf)s,%(pt)s,%(pp)s,%(ptype)s,%(seg)s,%(meta)s::jsonb)
ON CONFLICT (pivot_id) DO NOTHING;
"""


def upsert_pivot(database_url: str, *, pivot_id: str, setup_id: str, symbol: str, timeframe: str,
                pivot_time_ms: int, pivot_price: float, pivot_type: str, segment_no: int, meta: Dict[str, Any]) -> None:
    """写入 pivot 记录（此阶段至少写三段背离的 3 个 pivot）。"""
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(UPSERT_PIVOT_SQL, {
                "id": pivot_id,
                "setup": setup_id,
                "symbol": symbol,
                "tf": timeframe,
                "pt": int(pivot_time_ms),
                "pp": float(pivot_price),
                "ptype": pivot_type,
                "seg": int(segment_no),
                "meta": json.dumps(meta, ensure_ascii=False),
            })
            conn.commit()


def get_bars_range(database_url: str, *, symbol: str, timeframe: str, start_close_time_ms: int, end_close_time_ms: int) -> List[Dict[str, Any]]:
    """按 close_time_ms 范围读取 bars（Stage 6：回放回测使用）。"""
    sql = """
    SELECT open, high, low, close, volume, turnover, open_time_ms, close_time_ms
    FROM bars
    WHERE symbol=%(symbol)s AND timeframe=%(timeframe)s
      AND close_time_ms >= %(start)s AND close_time_ms <= %(end)s
    ORDER BY close_time_ms ASC;
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"symbol": symbol, "timeframe": timeframe, "start": int(start_close_time_ms), "end": int(end_close_time_ms)})
            rows = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "open": float(r[0]),
            "high": float(r[1]),
            "low": float(r[2]),
            "close": float(r[3]),
            "volume": float(r[4]),
            "turnover": float(r[5]) if r[5] is not None else None,
            "open_time_ms": int(r[6]),
            "close_time_ms": int(r[7]),
        })
    return out

