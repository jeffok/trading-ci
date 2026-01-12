# -*- coding: utf-8 -*-
"""行情缺口检测 + 回填 + 顺序补发 bar_close（Stage 2）

核心目标：
- WS 断线/漏包时，避免漏掉 bar_close 导致策略漏信号
- 发现缺口后：REST 回补 bars -> 按时间顺序补发 bar_close

注意：
- 不改变策略；这里只负责数据与事件完整性
- 幂等：bars 以 (symbol,timeframe,close_time_ms) upsert；bar_close 通过 bar_close_emits 预留记录避免重复补发
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

from libs.common.config import settings
from libs.common.id import new_event_id
from libs.common.time import now_ms
from libs.common.timeframe import timeframe_ms
from libs.bybit.market_rest import BybitMarketRestClient
from libs.bybit.intervals import bybit_interval_for_system_timeframe

from services.marketdata.repo_bars import upsert_bar
from services.marketdata.publisher import build_bar_close_event, publish_bar_close
from services.marketdata.repo_emit import reserve_bar_close_emit, rollback_bar_close_emit, get_prev_close_time_ms
from services.marketdata.publisher_risk import build_risk_event, publish_risk_event
from services.marketdata.repo_risk import insert_risk_event


def _utc_trade_date() -> str:
    return datetime.datetime.utcnow().date().isoformat()


def _calc_close_time_ms(tf: str, start_ms: int) -> int:
    """推算 close_time_ms（分钟/小时/日固定周期）。"""
    return int(start_ms) + timeframe_ms(tf) - 1


def _publish_bar_close_idempotent(*, database_url: str, redis_url: str, symbol: str, timeframe: str, close_time_ms: int, source: str) -> None:
    """幂等发布 bar_close：预留 bar_close_emits 成功才发布。"""
    eid = new_event_id()
    ok = reserve_bar_close_emit(database_url, symbol=symbol, timeframe=timeframe, close_time_ms=close_time_ms, event_id=eid, source=source)
    if not ok:
        return
    try:
        ev = build_bar_close_event(symbol=symbol, timeframe=timeframe, close_time_ms=close_time_ms, source=source, trace_id=None)
        publish_bar_close(redis_url, ev)
    except Exception:
        rollback_bar_close_emit(database_url, symbol=symbol, timeframe=timeframe, close_time_ms=close_time_ms, event_id=eid)
        raise


def _emit_risk(*, database_url: str, redis_url: str, typ: str, severity: str, symbol: Optional[str], detail: Dict[str, Any]) -> None:
    ev = build_risk_event(typ=typ, severity=severity, symbol=symbol, detail=detail)
    publish_risk_event(redis_url, ev)
    insert_risk_event(database_url, event_id=ev["event_id"], trade_date=_utc_trade_date(), ts_ms=ev["ts_ms"], typ=typ, severity=severity, detail=detail)


def _rest_backfill_range(*, rest: BybitMarketRestClient, symbol: str, tf: str, start_ms: int, end_ms: int, max_bars: int) -> List[Dict[str, Any]]:
    """回填 [start_ms, end_ms] 范围内的 bars（按 start_ms 正序返回）。"""
    interval = bybit_interval_for_system_timeframe(tf)
    if interval is None:
        return []
    out: List[Dict[str, Any]] = []
    cursor = int(start_ms)
    safety = 0
    tfms = timeframe_ms(tf)
    while cursor <= end_ms and len(out) < max_bars:
        safety += 1
        if safety > 50:
            break
        # Bybit limit <= 1000
        candles = rest.get_kline(symbol=symbol, interval=interval, category="linear", limit=1000, start_ms=cursor, end_ms=end_ms)
        if not candles:
            break
        candles = list(reversed(candles))  # 正序
        # 去重/推进 cursor
        advanced = False
        for c in candles:
            s = int(c["start_ms"])
            if s < start_ms or s > end_ms:
                continue
            out.append(c)
            advanced = True
        if not advanced:
            break
        last = int(candles[-1]["start_ms"])
        nxt = last + tfms
        if nxt <= cursor:
            break
        cursor = nxt
    # sort by start_ms, and drop duplicates
    uniq = {}
    for c in out:
        uniq[int(c["start_ms"])] = c
    return [uniq[k] for k in sorted(uniq.keys())][:max_bars]


def handle_confirmed_candle(*, database_url: str, redis_url: str, symbol: str, timeframe: str, candle: Dict[str, Any], source: str) -> None:
    """处理一根已确认收盘的 candle：检测缺口 -> 回填 -> 顺序补发 -> 落库/发布当前 bar_close。"""
    if not getattr(settings, "marketdata_gapfill_enabled", True):
        # 只做常规落库+发布（由 worker 现有逻辑完成），这里直接返回
        return

    tfms = timeframe_ms(timeframe)

    # candle 结构来自 marketdata.worker._parse_kline_msg
    open_ms = int(candle["open_time_ms"])
    close_ms = int(candle["close_time_ms"])

    # 取 DB 中在当前 bar 之前的最后一根 close_time_ms（用于缺口判定）
    prev_close = get_prev_close_time_ms(database_url, symbol=symbol, timeframe=timeframe, before_close_time_ms=close_ms)

    if prev_close is not None:
        expected_next_open = int(prev_close) + 1
        if open_ms > expected_next_open:
            # 发现缺口
            missing_ms = open_ms - expected_next_open
            missing_bars = int(missing_ms // tfms)
            _emit_risk(
                database_url=database_url,
                redis_url=redis_url,
                typ="DATA_GAP",
                severity="IMPORTANT",
                symbol=symbol,
                detail={"timeframe": timeframe, "prev_close_time_ms": int(prev_close), "next_open_time_ms": open_ms, "missing_bars": missing_bars},
            )

            # 回填范围：从 expected_next_open 到 open_ms - 1
            start_ms = expected_next_open
            end_ms = open_ms - 1
            rest = BybitMarketRestClient(settings.bybit_base_url)
            filled = _rest_backfill_range(
                rest=rest,
                symbol=symbol,
                tf=timeframe,
                start_ms=start_ms,
                end_ms=end_ms,
                max_bars=int(getattr(settings, "marketdata_gapfill_max_bars", 2000)),
            )

            # 写库 + 顺序补发
            for c in filled:
                s = int(c["start_ms"])
                ct = _calc_close_time_ms(timeframe, s)
                upsert_bar(
                    database_url,
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time_ms=s,
                    close_time_ms=ct,
                    open=float(c["open"]),
                    high=float(c["high"]),
                    low=float(c["low"]),
                    close=float(c["close"]),
                    volume=float(c["volume"]),
                    turnover=float(c.get("turnover")) if c.get("turnover") is not None else None,
                    source="bybit_rest_gapfill",
                )
                _publish_bar_close_idempotent(
                    database_url=database_url,
                    redis_url=redis_url,
                    symbol=symbol,
                    timeframe=timeframe,
                    close_time_ms=ct,
                    source="bybit_rest_gapfill",
                )

            _emit_risk(
                database_url=database_url,
                redis_url=redis_url,
                typ="BACKFILL_DONE",
                severity="INFO",
                symbol=symbol,
                detail={"timeframe": timeframe, "filled_bars": len(filled), "range_start_ms": start_ms, "range_end_ms": end_ms},
            )

    # 当前 bar 仍然写库 + 发布（幂等）
    upsert_bar(
        database_url,
        symbol=symbol,
        timeframe=timeframe,
        open_time_ms=open_ms,
        close_time_ms=close_ms,
        open=float(candle["open"]),
        high=float(candle["high"]),
        low=float(candle["low"]),
        close=float(candle["close"]),
        volume=float(candle["volume"]),
        turnover=float(candle.get("turnover")) if candle.get("turnover") is not None else None,
        source=source,
    )
    _publish_bar_close_idempotent(
        database_url=database_url,
        redis_url=redis_url,
        symbol=symbol,
        timeframe=timeframe,
        close_time_ms=close_ms,
        source=source,
    )
