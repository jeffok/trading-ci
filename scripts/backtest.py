# -*- coding: utf-8 -*-
"""离线回测脚本（Phase 5）

用法示例：
python3 scripts/backtest.py --symbol BTCUSDT --timeframe 1h --limit 5000 --trail ATR

依赖：
- Postgres 已写入 bars（由 marketdata-service 产生）
- 本脚本仅做读操作，不会写订单/持仓

输出：
- reports/backtest_<symbol>_<tf>_<ts>.json
- 终端打印汇总指标（count/win_rate/avg_r/sum_r/max_dd_r）
"""

from __future__ import annotations

import argparse
import hashlib
import time
import json
import os
import time

from libs.common.config import settings
from services.strategy.repo import get_bars
from libs.backtest.engine import backtest
from libs.backtest.report import summarize, to_jsonable
from libs.backtest.repo import insert_backtest_run, insert_backtest_trade


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--timeframe", required=True)
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--trail", choices=["ATR", "PIVOT"], default="ATR")
    ap.add_argument("--atr_period", type=int, default=14)
    ap.add_argument("--atr_mult", type=float, default=2.0)
    ap.add_argument("--write_db", action="store_true", help="将回测 run/trades 落库（backtest_runs/backtest_trades）")
    ap.add_argument("--run_id", default="", help="可选：指定 run_id（不填则自动生成）")
    args = ap.parse_args()

    bars = get_bars(settings.database_url, symbol=args.symbol, timeframe=args.timeframe, limit=args.limit)
    if len(bars) < 200:
        print("bars too few:", len(bars))
        return

    results = backtest(
        symbol=args.symbol,
        timeframe=args.timeframe,
        bars=bars,
        min_confirmations=settings.min_confirmations,
        trail_mode=args.trail,
        atr_period=args.atr_period,
        atr_mult=args.atr_mult,
    )

    summary = summarize(results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    os.makedirs("reports", exist_ok=True)
    ts = int(time.time())
    path = f"reports/backtest_{args.symbol}_{args.timeframe}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": to_jsonable(results)}, f, ensure_ascii=False, indent=2)
    print("saved:", path)

    # Stage 5：可选将回测结果落库，便于 API 查询与长期复盘对比
    if args.write_db:
        run_id = args.run_id.strip() or hashlib.sha256(f"{args.symbol}|{args.timeframe}|{ts}".encode("utf-8")).hexdigest()
        start_ms = int(bars[0].get("open_time_ms") or bars[0].get("ts_ms") or 0)
        end_ms = int(bars[-1].get("close_time_ms") or bars[-1].get("ts_ms") or 0)
        params = {
            "trail": args.trail,
            "atr_period": args.atr_period,
            "atr_mult": args.atr_mult,
            "limit": args.limit,
        }
        insert_backtest_run(
            settings.database_url,
            run_id=run_id,
            symbol=args.symbol,
            timeframe=args.timeframe,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            params=params,
            summary=summary,
        )
        # 逐笔交易落库
        js = to_jsonable(results)
        for idx, tr in enumerate(js):
            trade_id = hashlib.sha256(f"{run_id}|{idx}".encode("utf-8")).hexdigest()
            entry_i = int(tr.get("entry_i", 0))
            exit_i = int(tr.get("exit_i", 0))
            entry_time_ms = int((bars[entry_i].get("close_time_ms") if entry_i < len(bars) else 0) or 0)
            exit_time_ms = int((bars[exit_i].get("close_time_ms") if exit_i < len(bars) else 0) or 0)
            side = tr.get("side")
            side2 = "LONG" if side == "BUY" else ("SHORT" if side == "SELL" else str(side))
            insert_backtest_trade(
                settings.database_url,
                trade_id=trade_id,
                run_id=run_id,
                symbol=args.symbol,
                timeframe=args.timeframe,
                entry_time_ms=entry_time_ms,
                exit_time_ms=exit_time_ms,
                side=side2,
                entry_price=float(tr.get("entry")),
                exit_price=float(tr.get("legs", [])[-1].get("price")) if tr.get("legs") else float(tr.get("entry")),
                pnl_r=float(tr.get("pnl_r")),
                reason=str(tr.get("reason")),
                legs=tr.get("legs", []),
            )
        print("backtest written to db: run_id=", run_id)


if __name__ == "__main__":
    main()
