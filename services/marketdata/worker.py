"""
marketdata-service 主工作流（Phase 1）

工作流：
1) 解析配置：symbols/timeframes
2) 确保 Redis Streams group 存在（幂等）
3) 可选：REST 回填 bars（写库，不发布事件）
4) 连接 Bybit 公共 WS（linear），订阅 kline
5) 仅当 data[].confirm == true 时：
   - upsert bars 表
   - 发布 bar_close 事件
6) 从 1h bar 派生 8h bar（完成时同样写库+发事件）

注意：Phase 1 只做 marketdata，不做策略计算。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.mq.redis_streams import RedisStreamsClient
from libs.bybit.intervals import bybit_interval_for_system_timeframe
from libs.bybit.market_rest import BybitMarketRestClient
from libs.bybit.ws_public import BybitPublicWsClient

from services.marketdata.config import MarketdataSettings
from services.marketdata.repo_bars import upsert_bar
from services.marketdata.publisher import build_bar_close_event, publish_bar_close
from services.marketdata.derived_8h import Derived8hAggregator


logger = setup_logging("marketdata-service")


def _topics(symbols: List[str], timeframes: List[str]) -> List[str]:
    topics: List[str] = []
    for tf in timeframes:
        interval = bybit_interval_for_system_timeframe(tf)
        if interval is None:
            continue
        for sym in symbols:
            topics.append(f"kline.{interval}.{sym}")
    return topics


def _parse_kline_msg(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """解析 WS kline 消息；只返回“已收盘”的单根 candle。"""
    topic = msg.get("topic")
    if not isinstance(topic, str) or not topic.startswith("kline."):
        return None

    data = msg.get("data")
    if not isinstance(data, list) or not data:
        return None

    c = data[0]
    if not c.get("confirm", False):
        return None

    return {
        "topic": topic,
        "start_ms": int(c["start"]),
        "end_ms": int(c["end"]),
        "interval": str(c["interval"]),
        "open": float(c["open"]),
        "high": float(c["high"]),
        "low": float(c["low"]),
        "close": float(c["close"]),
        "volume": float(c["volume"]),
        "turnover": float(c["turnover"]) if c.get("turnover") is not None else None,
        "ts_ms": int(msg.get("ts") or c.get("timestamp") or 0),
    }


def _system_tf_from_topic(topic: str) -> Tuple[str, str]:
    _, interval, symbol = topic.split(".", 2)
    interval_to_tf = {"15": "15m", "30": "30m", "60": "1h", "240": "4h", "D": "1d"}
    return interval_to_tf.get(interval, interval), symbol


async def rest_backfill(md: MarketdataSettings) -> None:
    """REST 回填：只写库，不发布 bar_close 事件。"""
    if not md.enable_rest_backfill:
        logger.info("rest_backfill_skip", extra={"extra_fields": {"event": "REST_BACKFILL_SKIP"}})
        return

    rest = BybitMarketRestClient(settings.bybit_base_url)

    for sym in md.symbols:
        for tf in md.timeframes:
            interval = bybit_interval_for_system_timeframe(tf)
            if interval is None:
                continue  # 8h 等派生周期不回填
            try:
                candles = rest.get_kline(
                    symbol=sym,
                    interval=interval,
                    category="linear",
                    limit=min(1000, md.backfill_limit),
                )
                candles = list(reversed(candles))  # 正序
                for c in candles:
                    if interval.isdigit():
                        close_time = c["start_ms"] + int(interval) * 60 * 1000 - 1
                    else:
                        # D/W/M 不固定；这里 warmup 用，不做强依赖
                        close_time = c["start_ms"]
                    upsert_bar(
                        settings.database_url,
                        symbol=sym,
                        timeframe=tf,
                        open_time_ms=c["start_ms"],
                        close_time_ms=close_time,
                        open=c["open"],
                        high=c["high"],
                        low=c["low"],
                        close=c["close"],
                        volume=c["volume"],
                        turnover=c.get("turnover"),
                        source="bybit_rest",
                    )
                logger.info(
                    "rest_backfill_ok",
                    extra={"extra_fields": {"event": "REST_BACKFILL_OK", "symbol": sym, "timeframe": tf, "count": len(candles)}},
                )
            except Exception as e:
                logger.warning(
                    "rest_backfill_failed",
                    extra={"extra_fields": {"event": "REST_BACKFILL_FAILED", "symbol": sym, "timeframe": tf, "error": str(e)}},
                )


async def run_marketdata() -> None:
    md = MarketdataSettings.load()

    # 1) 确保 streams group（幂等）
    streams = RedisStreamsClient(settings.redis_url)
    for s in ["stream:bar_close", "stream:risk_event"]:
        streams.ensure_group(s, settings.redis_stream_group)

    # 2) 可选：REST 回填（写库，不发事件）
    await rest_backfill(md)

    # 3) WS 订阅
    topics = _topics(md.symbols, md.timeframes)
    logger.info("ws_subscribe", extra={"extra_fields": {"event": "WS_SUBSCRIBE", "topic_count": len(topics)}})

    agg8h = Derived8hAggregator()

    async def handle(msg: Dict[str, Any]) -> None:
        k = _parse_kline_msg(msg)
        if k is None:
            return

        tf, symbol = _system_tf_from_topic(k["topic"])

        # 4) 写库（原生周期）
        upsert_bar(
            settings.database_url,
            symbol=symbol,
            timeframe=tf,
            open_time_ms=k["start_ms"],
            close_time_ms=k["end_ms"],
            open=k["open"],
            high=k["high"],
            low=k["low"],
            close=k["close"],
            volume=k["volume"],
            turnover=k.get("turnover"),
            source="bybit_ws",
        )

        # 5) 发布 bar_close（原生周期）
        event = build_bar_close_event(
            symbol=symbol,
            timeframe=tf,
            close_time_ms=k["end_ms"],
            source="bybit_ws",
            ohlcv={
                "open": k["open"],
                "high": k["high"],
                "low": k["low"],
                "close": k["close"],
                "volume": k["volume"],
            },
        )
        publish_bar_close(settings.redis_url, event)

        # 6) 派生 8h（输入为 1h bar）
        if tf == "1h" and "8h" in md.timeframes:
            agg_bar, warning = agg8h.push_1h_bar(
                symbol,
                {
                    "start_ms": k["start_ms"],
                    "end_ms": k["end_ms"],
                    "open": k["open"],
                    "high": k["high"],
                    "low": k["low"],
                    "close": k["close"],
                    "volume": k["volume"],
                    "turnover": k.get("turnover"),
                },
            )
            if warning:
                logger.warning("derived_8h_warning", extra={"extra_fields": {"event": "DERIVED_8H_WARN", "symbol": symbol, "warning": warning}})

            if agg_bar is not None:
                # 写库（8h）
                upsert_bar(
                    settings.database_url,
                    symbol=symbol,
                    timeframe="8h",
                    open_time_ms=agg_bar["start_ms"],
                    close_time_ms=agg_bar["end_ms"],
                    open=agg_bar["open"],
                    high=agg_bar["high"],
                    low=agg_bar["low"],
                    close=agg_bar["close"],
                    volume=agg_bar["volume"],
                    turnover=agg_bar.get("turnover"),
                    source="derived_8h",
                )

                # 发布 bar_close（8h）
                ev8 = build_bar_close_event(
                    symbol=symbol,
                    timeframe="8h",
                    close_time_ms=agg_bar["end_ms"],
                    source="derived_8h",
                    ohlcv={
                        "open": agg_bar["open"],
                        "high": agg_bar["high"],
                        "low": agg_bar["low"],
                        "close": agg_bar["close"],
                        "volume": agg_bar["volume"],
                    },
                )
                publish_bar_close(settings.redis_url, ev8)

                logger.info("derived_8h_emit", extra={"extra_fields": {"event": "DERIVED_8H_EMIT", "symbol": symbol, "close_time_ms": agg_bar["end_ms"]}})

    ws = BybitPublicWsClient(
        ws_url=settings.bybit_ws_public_url,
        topics=topics,
        on_message=handle,
        ping_interval_s=20,
    )
    await ws.run_forever()
