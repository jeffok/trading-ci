"""bars 表写入（Phase 1）

设计原则：
- 只做“最小必要 SQL”，避免 ORM 增加复杂度
- 以 (symbol,timeframe,close_time_ms) 为主键，保证幂等 upsert
"""

from __future__ import annotations

from typing import Optional

from libs.db.pg import get_conn


UPSERT_SQL = """
INSERT INTO bars (
  symbol, timeframe, open_time_ms, close_time_ms,
  open, high, low, close, volume, turnover, source
) VALUES (
  %(symbol)s, %(timeframe)s, %(open_time_ms)s, %(close_time_ms)s,
  %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(turnover)s, %(source)s
)
ON CONFLICT (symbol, timeframe, close_time_ms)
DO UPDATE SET
  open_time_ms = EXCLUDED.open_time_ms,
  open = EXCLUDED.open,
  high = EXCLUDED.high,
  low = EXCLUDED.low,
  close = EXCLUDED.close,
  volume = EXCLUDED.volume,
  turnover = EXCLUDED.turnover,
  source = EXCLUDED.source,
  updated_at = now();
"""


def upsert_bar(
    database_url: str,
    *,
    symbol: str,
    timeframe: str,
    open_time_ms: int,
    close_time_ms: int,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    turnover: Optional[float],
    source: str,
) -> None:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                UPSERT_SQL,
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time_ms": open_time_ms,
                    "close_time_ms": close_time_ms,
                    "open": open,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "turnover": turnover,
                    "source": source,
                },
            )
            conn.commit()


GET_BAR_SQL = """
SELECT open, high, low, close, volume, turnover, open_time_ms, close_time_ms, source
FROM bars
WHERE symbol=%(symbol)s AND timeframe=%(timeframe)s AND close_time_ms=%(close_time_ms)s
LIMIT 1;
"""

GET_PREV_BAR_SQL = """
SELECT open, high, low, close, volume, turnover, open_time_ms, close_time_ms, source
FROM bars
WHERE symbol=%(symbol)s AND timeframe=%(timeframe)s AND close_time_ms < %(close_time_ms)s
ORDER BY close_time_ms DESC
LIMIT 1;
"""

GET_RECENT_VOLUMES_SQL = """
SELECT volume
FROM bars
WHERE symbol=%(symbol)s AND timeframe=%(timeframe)s AND close_time_ms <= %(close_time_ms)s
ORDER BY close_time_ms DESC
LIMIT %(limit)s;
"""

def get_bar(database_url: str, *, symbol: str, timeframe: str, close_time_ms: int) -> Optional[dict]:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(GET_BAR_SQL, {"symbol": symbol, "timeframe": timeframe, "close_time_ms": int(close_time_ms)})
            r = cur.fetchone()
            if not r:
                return None
            return {
                "open": float(r[0]),
                "high": float(r[1]),
                "low": float(r[2]),
                "close": float(r[3]),
                "volume": float(r[4]),
                "turnover": float(r[5]) if r[5] is not None else None,
                "open_time_ms": int(r[6]),
                "close_time_ms": int(r[7]),
                "source": r[8],
            }

def get_prev_bar(database_url: str, *, symbol: str, timeframe: str, close_time_ms: int) -> Optional[dict]:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(GET_PREV_BAR_SQL, {"symbol": symbol, "timeframe": timeframe, "close_time_ms": int(close_time_ms)})
            r = cur.fetchone()
            if not r:
                return None
            return {
                "open": float(r[0]),
                "high": float(r[1]),
                "low": float(r[2]),
                "close": float(r[3]),
                "volume": float(r[4]),
                "turnover": float(r[5]) if r[5] is not None else None,
                "open_time_ms": int(r[6]),
                "close_time_ms": int(r[7]),
                "source": r[8],
            }

def get_recent_volumes(database_url: str, *, symbol: str, timeframe: str, close_time_ms: int, limit: int = 30) -> list[float]:
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(GET_RECENT_VOLUMES_SQL, {"symbol": symbol, "timeframe": timeframe, "close_time_ms": int(close_time_ms), "limit": int(limit)})
            rows = cur.fetchall() or []
            return [float(r[0]) for r in rows]
