# -*- coding: utf-8 -*-
"""
strategy-service 主工作流（Phase 2）

输入：Redis Streams `stream:bar_close`
输出：
- `stream:signal`（对所有 timeframes 都可输出）
- `stream:trade_plan`（仅 auto_timeframes：1h/4h/1d）

核心逻辑（严格遵守你给定策略，不做改动）：
1) bar_close 到来后，从 DB 读取该 symbol+timeframe 的 bars（最近 N 根）
2) 检测 MACD histogram 三段背离（顶/底）
3) Vegas 同向强门槛（必须）
4) confirmations：Engulfing/RSI-div/OBV-div/FVG-proximity 至少命中 min_confirmations=2
5) 若满足：
   - 生成 signal 事件（记录命中的 confirmations）
   - 若 timeframe 属于自动下单周期（1h/4h/1d）：生成 trade_plan 事件
     - entry_price：当前收盘价（收盘确认）
     - primary_sl_price：第三极值（第三段 pivot 价格）
     - secondary_sl_rule：NEXT_BAR_NOT_SHORTEN_EXIT（执行层实现）

注意：
- Phase 2 只生成计划，不做任何下单动作。
- 幂等：用 idempotency_key（symbol+tf+close_time+bias）保证重复消息不重复产出。
"""

from __future__ import annotations

import asyncio
import json
import hashlib
from typing import Any, Dict, List, Optional

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.common.time import now_ms
from libs.common.timeframe import timeframe_ms
from libs.mq.redis_streams import RedisStreamsClient
from libs.mq.dlq import publish_dlq
from libs.mq.schema_validator import validate

from libs.strategy.divergence import detect_three_segment_divergence
from libs.strategy.confluence import Candle, vegas_state, engulfing, rsi_divergence, obv_divergence, fvg_proximity
from libs.strategy.scoring import DivergenceFeatures, divergence_strength as div_strength_score, confluence_strength, signal_quality_score

from services.strategy.repo import (
    get_bars,
    save_signal,
    save_trade_plan,
    upsert_setup,
    upsert_trigger,
    upsert_pivot,
)
from services.strategy.publisher import (
    build_signal_event, publish_signal,
    build_trade_plan_event, publish_trade_plan,
    build_risk_event, publish_risk_event,
)

logger = setup_logging("strategy-service")

BAR_CLOSE_SCHEMA = "streams/bar-close.json"
STREAM_BAR_CLOSE = "stream:bar_close"


def _idempotency_key(symbol: str, timeframe: str, close_time_ms: int, bias: str) -> str:
    raw = f"{symbol}|{timeframe}|{close_time_ms}|{bias}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _plan_id(symbol: str, timeframe: str, close_time_ms: int, bias: str) -> str:
    # 计划 ID 也采用可复现方式，方便排障与幂等
    return _idempotency_key(symbol, timeframe, close_time_ms, bias)[:24]


def _setup_id(symbol: str, timeframe: str, close_time_ms: int, bias: str) -> str:
    return "setup_" + _idempotency_key(symbol, timeframe, close_time_ms, bias)[:20]


def _trigger_id(symbol: str, timeframe: str, close_time_ms: int, bias: str) -> str:
    return "trg_" + _idempotency_key(symbol, timeframe, close_time_ms, bias)[-20:]


def _parse_stream_message(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Redis Streams field: data=JSON(envelope)"""
    if "data" not in fields:
        raise ValueError("missing field 'data' in stream message")
    obj = json.loads(fields["data"])
    validate(BAR_CLOSE_SCHEMA, obj)
    return obj


def _timeframe_in_list(tf: str, csv: str) -> bool:
    return tf in [x.strip() for x in csv.split(",") if x.strip()]


async def process_bar_close(event: Dict[str, Any]) -> None:
    payload = event["payload"]
    symbol = payload["symbol"]
    timeframe = payload["timeframe"]
    close_time_ms = int(payload["close_time_ms"])

    # 读取 bars（按时间升序）
    bars = get_bars(settings.database_url, symbol=symbol, timeframe=timeframe, limit=500)
    if len(bars) < 120:
        return

    candles = [Candle(open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b["volume"]) for b in bars]
    close = [c.close for c in candles]
    high = [c.high for c in candles]
    low = [c.low for c in candles]

    # 1) 三段背离检测
    setup = detect_three_segment_divergence(close=close, high=high, low=low)
    if setup is None:
        return

    bias = setup.direction  # LONG/SHORT

    # -------- Phase 5：信号评分（仅用于复盘，不参与决策）--------
    # divergence_strength：0~60
    feat = DivergenceFeatures(
        hist2=float(setup.h2),
        hist3=float(setup.h3),
        price2=float(setup.p2.price),
        price3=float(setup.p3.price),
        i1=int(setup.p1.index),
        i2=int(setup.p2.index),
        i3=int(setup.p3.index),
    )
    div_score = div_strength_score(feat)  # 0~60


    # 2) Vegas 强门槛（同向必须）
    vs = vegas_state(close)
    if bias == "LONG" and vs != "Bullish":
        return
    if bias == "SHORT" and vs != "Bearish":
        return

    # 3) confirmations
    hits: List[str] = []
    if engulfing(candles[-2:], bias):
        hits.append("ENGULFING")
    if rsi_divergence(candles, bias):
        hits.append("RSI_DIV")
    if obv_divergence(candles, bias):
        hits.append("OBV_DIV")
    if fvg_proximity(candles, bias):
        hits.append("FVG_PROXIMITY")

    if len(hits) < settings.min_confirmations:
        return

    # -------- Phase 5：共振评分 + 总分（仅用于复盘，不参与决策）--------
    conf_score = confluence_strength(hit_count=len(hits), min_confirmations=settings.min_confirmations)  # 0~40
    quality_score = signal_quality_score(divergence_score=div_score, confluence_score=conf_score)  # 0~100
    signal_score_int = int(round(quality_score))
    divergence_strength_int = int(round(div_score))
    confluence_strength_int = int(round(conf_score))

    scoring_ext = {
        "signal_quality_score": signal_score_int,
        "divergence_strength": divergence_strength_int,
        "confluence_strength": confluence_strength_int,
        "confirmations_hit": hits,
    }


    # 4) 输出 signal（并落库）
    idem = _idempotency_key(symbol, timeframe, close_time_ms, bias)
    setup_id = _setup_id(symbol, timeframe, close_time_ms, bias)
    trigger_id = _trigger_id(symbol, timeframe, close_time_ms, bias)

    # ---------------- Stage 3：setup/trigger/pivot 落库（不影响决策） ----------------
    # 1) setup：三段背离结构
    try:
        upsert_setup(
            settings.database_url,
            setup_id=setup_id,
            idempotency_key=idem,  # setup 与 signal 同幂等键
            symbol=symbol,
            timeframe=timeframe,
            close_time_ms=close_time_ms,
            bias=bias,
            setup_type="MACD_3SEG_DIVERGENCE",
            payload={
                "p1": {"i": int(setup.p1.index), "price": float(setup.p1.price), "hist": float(setup.h1)},
                "p2": {"i": int(setup.p2.index), "price": float(setup.p2.price), "hist": float(setup.h2)},
                "p3": {"i": int(setup.p3.index), "price": float(setup.p3.price), "hist": float(setup.h3)},
            },
        )

        # 2) pivots：至少把三段对应的 pivot 落库（pivot_time_ms 用 bars 的 close_time_ms 近似）
        # 注意：p1/p2/p3 是序列索引，这里用 candles 索引映射到 close_time_ms。
        # 如果后续需要更精确，可把 pivot_time_ms 绑定到 open_time_ms/close_time_ms 对应的 bar。
        p1_ct = int(bars[int(setup.p1.index)]["close_time_ms"])
        p2_ct = int(bars[int(setup.p2.index)]["close_time_ms"])
        p3_ct = int(bars[int(setup.p3.index)]["close_time_ms"])

        # LONG：低点；SHORT：高点（此处仅用于 pivot_type 复盘标注）
        ptype = "LOW" if bias == "LONG" else "HIGH"

        upsert_pivot(
            settings.database_url,
            pivot_id=f"{setup_id}:1",
            setup_id=setup_id,
            symbol=symbol,
            timeframe=timeframe,
            pivot_time_ms=p1_ct,
            pivot_price=float(setup.p1.price),
            pivot_type=ptype,
            segment_no=1,
            meta={"hist": float(setup.h1), "i": int(setup.p1.index)},
        )
        upsert_pivot(
            settings.database_url,
            pivot_id=f"{setup_id}:2",
            setup_id=setup_id,
            symbol=symbol,
            timeframe=timeframe,
            pivot_time_ms=p2_ct,
            pivot_price=float(setup.p2.price),
            pivot_type=ptype,
            segment_no=2,
            meta={"hist": float(setup.h2), "i": int(setup.p2.index)},
        )
        upsert_pivot(
            settings.database_url,
            pivot_id=f"{setup_id}:3",
            setup_id=setup_id,
            symbol=symbol,
            timeframe=timeframe,
            pivot_time_ms=p3_ct,
            pivot_price=float(setup.p3.price),
            pivot_type=ptype,
            segment_no=3,
            meta={"hist": float(setup.h3), "i": int(setup.p3.index)},
        )
    except Exception:
        pass

    # 3) trigger：共振确认命中项（hits）
    try:
        upsert_trigger(
            settings.database_url,
            trigger_id=trigger_id,
            idempotency_key=idem,  # trigger 与 signal 同幂等键，保证重放不重复
            setup_id=setup_id,
            symbol=symbol,
            timeframe=timeframe,
            close_time_ms=close_time_ms,
            bias=bias,
            hits=hits,
            payload={"hits": hits, "min_confirmations": int(settings.min_confirmations)},
        )
    except Exception:
        pass

    signal_event = build_signal_event(
        symbol=symbol,
        timeframe=timeframe,
        close_time_ms=close_time_ms,
        bias=bias,
        vegas_state=vs,
        hits=hits,
        setup_id=setup_id,
        trigger_id=trigger_id,
        signal_score=signal_score_int,
        divergence_strength=divergence_strength_int,
        ext={"scoring": scoring_ext},
    )
    publish_signal(settings.redis_url, signal_event)

    # signals 表落库（用于 API/复盘）
    save_signal(
        settings.database_url,
        signal_id=signal_event["event_id"],
        idempotency_key=idem,
        symbol=symbol,
        timeframe=timeframe,
        close_time_ms=close_time_ms,
        bias=bias,
        vegas_state=vs,
        hit_count=len(hits),
        hits=hits,
        signal_score=signal_score_int,
        payload=signal_event,
        status="NEW",
        valid_from_ms=int(signal_event["payload"]["close_time_ms"]),
        expires_at_ms=int(signal_event["payload"]["close_time_ms"]) + int(getattr(settings, "signal_ttl_bars", 1)) * timeframe_ms(signal_event["payload"]["timeframe"]),
    )

    logger.info("signal_emitted", extra={"extra_fields": {"event":"SIGNAL_EMIT","symbol":symbol,"timeframe":timeframe,"bias":bias,"hits":hits}})

    # 5) 若是自动下单周期：输出 trade_plan（并落库）
    if _timeframe_in_list(timeframe, settings.auto_timeframes):
        entry_price = close[-1]  # 收盘确认入场
        primary_sl = setup.p3.price  # 第三极值止损（硬规则）

        side = "BUY" if bias == "LONG" else "SELL"
        plan_id = _plan_id(symbol, timeframe, close_time_ms, bias)

        # Stage 8: lifecycle ttl for trade_plan. Default: 1 bar.
        ttl_bars = int(getattr(settings, "trade_plan_ttl_bars", 1))
        ttl_ms = int(timeframe_ms(timeframe) * max(ttl_bars, 1))
        expires_at_ms = int(close_time_ms + ttl_ms)

        ext_payload = {"close_time_ms": close_time_ms, "scoring": scoring_ext}
        if run_id:
            ext_payload["run_id"] = run_id
        ext_payload.update({
            "status": "NEW",
            "valid_from_ms": int(close_time_ms),
            "expires_at_ms": int(expires_at_ms),
        })

        plan_event = build_trade_plan_event(
            plan_id=plan_id,
            idempotency_key=idem,
            symbol=symbol,
            timeframe=timeframe,
            close_time_ms=close_time_ms,
            side=side,
            entry_price=entry_price,
            primary_sl_price=primary_sl,
            setup_id=setup_id,
            trigger_id=trigger_id,
            ext=ext_payload,
        )
        publish_trade_plan(settings.redis_url, plan_event)

        save_trade_plan(
            settings.database_url,
            plan_id=plan_id,
            idempotency_key=idem,
            symbol=symbol,
            timeframe=timeframe,
            close_time_ms=close_time_ms,
            side=side,
            entry_price=entry_price,
            primary_sl_price=primary_sl,
            payload=plan_event,
            status="NEW",
            valid_from_ms=int(close_time_ms),
            expires_at_ms=int(expires_at_ms),
        )

        logger.info("trade_plan_emitted", extra={"extra_fields": {"event":"TRADE_PLAN_EMIT","symbol":symbol,"timeframe":timeframe,"side":side,"plan_id":plan_id}})


async def run_strategy() -> None:
    """
    从 Redis Streams 消费 bar_close，并处理。
    """
    client = RedisStreamsClient(settings.redis_url)
    client.ensure_group(STREAM_BAR_CLOSE, settings.redis_stream_group)
    client.ensure_group("stream:signal", settings.redis_stream_group)
    client.ensure_group("stream:trade_plan", settings.redis_stream_group)
    client.ensure_group("stream:risk_event", settings.redis_stream_group)

    while True:
        msgs = client.read_group(STREAM_BAR_CLOSE, settings.redis_stream_group, settings.redis_stream_consumer, count=20, block_ms=2000)
        if not msgs:
            continue

        for m in msgs:
            try:
                evt = _parse_stream_message(m.fields)
                await process_bar_close(evt)
                client.ack(m.stream, settings.redis_stream_group, m.message_id)
            except Exception as e:
                # 异常事件化：不会让整个服务崩溃，同时便于告警与排障
                logger.warning("bar_close_process_failed", extra={"extra_fields": {"event":"BAR_CLOSE_FAILED","error": str(e)}})
                try:
                    r = build_risk_event(
                        typ="DATA_GAP",
                        severity="IMPORTANT",
                        symbol=None,
                        detail={"where": "strategy-service", "error": str(e)},
                    )
                    publish_risk_event(settings.redis_url, r)
                except Exception:
                    pass
                # 为避免“毒消息”无限重试卡住消费：Phase 2 先 ack 掉，并依靠 risk_event 追踪
                client.ack(m.stream, settings.redis_stream_group, m.message_id)


