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
