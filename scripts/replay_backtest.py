# -*- coding: utf-8 -*-
"""Stage 6：回放回测（REPLAY）脚本

用途：
- 在不改策略的前提下，用历史 bars 回放 `stream:bar_close`
- 让 strategy/execution/notifier/api 等“真实服务链路”跑一遍，产出全量落库与事件
- 配合 paper/backtest 的撮合模拟（services/execution/paper_sim.py），实现回测&模拟盘闭环

前置条件（推荐）：
1) 启动服务（建议用独立 Redis / 独立 DB，避免干扰 live）：
   - EXECUTION_MODE=backtest 或 paper（本脚本仅发布 bar_close，不控制服务端模式）
2) bars 已在 Postgres 的 bars 表中（也可使用 --fetch 从 Bybit REST 拉取一段近似 bars）

示例：
  # 1) 回放 DB 中最近 2000 根 1h bars
  python scripts/replay_backtest.py --symbol BTCUSDT --timeframe 60 --limit 2000

  # 2) 指定区间（close_time_ms），并在发布间隔 5ms（避免压垮消费者）
  python scripts/replay_backtest.py --symbol BTCUSDT --timeframe 60 --start-ms 1700000000000 --end-ms 1700500000000 --sleep-ms 5

注意：
- 本脚本会给每个 bar_close_event.payload.ext 写入 run_id 与 seq
- strategy/execution 会把 run_id 传递到其落库 payload/meta 中，便于 /v1/backtest-compare 查询
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from libs.common.config import settings
from libs.common.logging import setup_logging
from libs.common.time import now_ms
from libs.mq.redis_streams import RedisStreamsClient
from libs.mq.events import publish_event

from services.marketdata.publisher import build_bar_close_event
from services.marketdata.repo_bars import upsert_bar
from libs.bybit.market_rest import MarketRestV5Client
from services.strategy.repo import get_bars, get_bars_range
from libs.backtest.repo import insert_backtest_run, list_backtest_trades


def _gen_run_id(symbol: str, timeframe: str) -> str:
    seed = f"{symbol}|{timeframe}|{now_ms()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _fetch_and_upsert(symbol: str, interval: str, limit: int) -> None:
    """从 Bybit REST 拉取最近 N 根（近似）并写库。"""
    client = MarketRestV5Client(base_url=settings.bybit_http_base)
    bars = client.get_kline(symbol=symbol, interval=interval, limit=limit)
    # 返回按 start_ms 逆序 -> 反转成正序
    bars = list(reversed(bars))
    for b in bars:
        # b: {start_ms, open, high, low, close, volume, turnover?}
        start_ms = int(b["start_ms"])
        o = float(b["open"]); h = float(b["high"]); l = float(b["low"]); c = float(b["close"])
        v = float(b["volume"]); t = float(b.get("turnover")) if b.get("turnover") is not None else None
        # close_time 近似：分钟/小时 interval 可推算；D/W/M 可能误差，但可用于回测 warmup/演示
        # 这里用 libs/bybit/intervals 做推算会更完整，但为了最小化依赖，按常见映射处理
        # interval 以分钟表示：60=1h，240=4h，D=1d
        if interval.isdigit():
            close_ms = start_ms + int(interval) * 60_000
        elif interval.upper() == "D":
            close_ms = start_ms + 24 * 60 * 60_000
        else:
            close_ms = start_ms  # 保守：未知 interval
        upsert_bar(settings.database_url, symbol=symbol, timeframe=interval, open_time_ms=start_ms, close_time_ms=close_ms,
                   open=o, high=h, low=l, close=c, volume=v, turnover=t, source="REST")


def main() -> None:
    setup_logging("scripts/replay_backtest")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--timeframe", required=True, help="与 bars.timeframe 一致：例如 60(1h)/240(4h)/D(1d)")
    ap.add_argument("--limit", type=int, default=0, help="不指定 start/end 时，从 DB 读取最近 N 根 bars 回放")
    ap.add_argument("--start-ms", type=int, default=0)
    ap.add_argument("--end-ms", type=int, default=0)
    ap.add_argument("--run-id", default="")
    ap.add_argument("--sleep-ms", type=int, default=0)
    ap.add_argument("--fetch", action="store_true", help="先从 Bybit REST 拉取近似 bars 写库（用于演示/补洞）")
    ap.add_argument("--fetch-limit", type=int, default=2000)

    args = ap.parse_args()

    symbol = args.symbol.upper()
    tf = args.timeframe
    run_id = args.run_id or _gen_run_id(symbol, tf)

    if args.fetch:
        _fetch_and_upsert(symbol, tf, args.fetch_limit)

    # 选 bars
    bars: List[Dict[str, Any]] = []
    if args.start_ms and args.end_ms:
        bars = get_bars_range(settings.database_url, symbol=symbol, timeframe=tf, start_close_time_ms=args.start_ms, end_close_time_ms=args.end_ms)
    else:
        lim = int(args.limit or 0)
        if lim <= 0:
            raise SystemExit("请使用 --limit 或 --start-ms/--end-ms 指定回放范围")
        # get_bars 返回 close_time DESC -> 反转
        bars = list(reversed(get_bars(settings.database_url, symbol=symbol, timeframe=tf, limit=lim)))

    if not bars:
        raise SystemExit("bars 为空：请确认 bars 表已写入或使用 --fetch")

    client = RedisStreamsClient(args.redis_url if hasattr(args, "redis_url") else settings.redis_url)

    print(f"[replay] run_id={run_id} bars={len(bars)} symbol={symbol} tf={tf}")

    # 发布 bar_close
    for i, b in enumerate(bars, start=1):
        evt = build_bar_close_event(
            symbol=symbol,
            timeframe=tf,
            close_time_ms=int(b["close_time_ms"]),
            source="REPLAY",
            ohlcv=[float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]), float(b["volume"])],
        )
        evt["payload"]["ext"] = {"run_id": run_id, "seq": i}
        publish_event(client, "stream:bar_close", evt, event_type="bar_close")
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    # 生成并落库 backtest_run（summary 依赖 backtest_trades，由 execution paper_sim 写入）
    # 注意：此处不等待消费者跑完；你可根据 bars 数量与机器性能自行 sleep 或在 /v1/backtest-compare 查询进度
    try:
        trades = list_backtest_trades(settings.database_url, run_id=run_id)
        if trades:
            total = len(trades)
            win = sum(1 for t in trades if float(t.get("pnl_r") or 0.0) > 0)
            avg = sum(float(t.get("pnl_r") or 0.0) for t in trades) / max(total, 1)
            summary = {"trades": total, "win_rate": win / max(total, 1), "avg_pnl_r": avg}
        else:
            summary = {"trades": 0, "win_rate": 0.0, "avg_pnl_r": 0.0}

        insert_backtest_run(
            settings.database_url,
            run_id=run_id,
            name=f"REPLAY_{symbol}_{tf}",
            params={"mode": "REPLAY", "symbol": symbol, "timeframe": tf, "bars": len(bars)},
            summary=summary,
        )
    except Exception:
        pass

    print("[replay] done. 建议用 /v1/backtest-compare?run_id=... 检查闭环进度。")


if __name__ == "__main__":
    main()
