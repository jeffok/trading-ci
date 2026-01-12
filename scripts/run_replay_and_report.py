# -*- coding: utf-8 -*-
"""一键回放 + 等待链路消费完成 + 自动生成回测报告（Stage 7）

设计目标：
- 适合你现在的工程形态：多服务容器化，但 DB/Redis 外置或独立启动
- 不强依赖 API 服务是否在线：报告优先直接查 Postgres；若提供 --api-url 则额外拉取 compare 信息
- 不改变策略：该脚本只做“回放 + 等待 + 汇总报告”

典型用法：
  # 1) 确保服务已启动（strategy/execution/api）
  # 2) 一键跑回放并生成报告
  python scripts/run_replay_and_report.py --symbol BTCUSDT --timeframe 60 --limit 2000

产物：
- reports/replay_<run_id>.json
- reports/replay_<run_id>.md
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from libs.common.config import settings
from libs.db.pg import get_conn
from libs.mq.redis_streams import RedisStreamsClient


STREAMS = [
    "stream:bar_close",
    "stream:signal",
    "stream:trade_plan",
    "stream:execution_report",
    "stream:risk_event",
    "stream:dlq",
]


def _db_count_jsonb_run_id(table: str, run_id: str) -> int:
    sql = f"""
    SELECT COUNT(1)
    FROM {table}
    WHERE (payload->'payload'->'ext'->>'run_id') = %s
    """
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _db_count_orders_run_id(run_id: str) -> int:
    sql = """SELECT COUNT(1) FROM orders WHERE (payload->'ext'->>'run_id')=%s"""
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _db_count_positions(run_id: str, status: str) -> int:
    sql = """SELECT COUNT(1) FROM positions WHERE (meta->>'run_id')=%s AND status=%s"""
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id, status))
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _db_list_backtest_trades(run_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    sql = """SELECT trade_id, run_id, symbol, timeframe, entry_time_ms, exit_time_ms, side, entry_price, exit_price, pnl_r, reason, legs
             FROM backtest_trades WHERE run_id=%s ORDER BY entry_time_ms ASC LIMIT %s"""
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id, limit))
            cols = [d.name for d in cur.description]
            out = []
            for row in cur.fetchall():
                out.append({cols[i]: row[i] for i in range(len(cols))})
            return out


def _wait_until_idle(redis_url: str, group: str, run_id: str, *, timeout_sec: int = 300, stable_sec: int = 5) -> Dict[str, Any]:
    """等待链路“基本空闲”。

判定条件（全部满足）：
- 所有关键 streams 的 XPENDING=0（该 group 下没有未 ack 的消息）
- positions_open(run_id)=0（说明 paper_sim 已把持仓出清，或本次没有触发开仓）

注意：
- 这不是严格的“全局完成”证明（因为策略可能不触发），但能覆盖 CI/回放的主要闭环。
"""
    c = RedisStreamsClient(redis_url)
    for s in STREAMS:
        c.ensure_group(s, group)

    start = time.time()
    stable_start: Optional[float] = None

    while True:
        pend = {s: c.pending_count(s, group) for s in STREAMS}
        open_pos = _db_count_positions(run_id, "OPEN")

        all_zero = all(int(v) == 0 for v in pend.values())
        done = all_zero and open_pos == 0

        if done:
            if stable_start is None:
                stable_start = time.time()
            if (time.time() - stable_start) >= stable_sec:
                return {"pending": pend, "positions_open": open_pos, "wait_sec": int(time.time() - start)}
        else:
            stable_start = None

        if (time.time() - start) > timeout_sec:
            return {"pending": pend, "positions_open": open_pos, "wait_sec": int(time.time() - start), "timeout": True}

        time.sleep(1.0)


def _render_md(run_id: str, args: argparse.Namespace, stats: Dict[str, Any], trades: List[Dict[str, Any]], wait: Dict[str, Any], api_compare: Optional[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append(f"# trading-ci 回放报告")
    lines.append("")
    lines.append(f"- run_id: `{run_id}`")
    lines.append(f"- symbol: `{args.symbol}`  timeframe: `{args.timeframe}`  limit: `{args.limit}`")
    lines.append(f"- mode(EXECUTION_MODE): `{settings.execution_mode}`")
    lines.append(f"- redis_url: `{settings.redis_url}`")
    lines.append(f"- database: `{settings.database_url}`")
    lines.append("")
    lines.append("## 等待链路空闲结果")
    lines.append(f"- wait_sec: {wait.get('wait_sec')}  timeout: {bool(wait.get('timeout', False))}")
    lines.append(f"- positions_open: {wait.get('positions_open')} ")
    lines.append("- pending:")

    for k,v in (wait.get("pending") or {}).items():
        lines.append(f"  - {k}: {v}")

    lines.append("")
    lines.append("## 产物统计（按 run_id 过滤）")
    for k,v in stats.items():
        lines.append(f"- {k}: {v}")

    lines.append("")
    lines.append("## backtest_trades（前 50 条）")
    if not trades:
        lines.append("- （空）")
    else:
        lines.append("| idx | side | pnl_r | entry_time_ms | exit_time_ms | reason | idempotency_key | trade_id |")
        lines.append("|---:|---|---:|---:|---:|---|---|---|")
        for i,tr in enumerate(trades[:50], start=1):
            legs = tr.get("legs") or []
            idem = ""
            if isinstance(legs, list) and legs:
                idem = str(legs[0].get("idempotency_key", "")) if isinstance(legs[0], dict) else ""
            lines.append(f"| {i} | {tr.get('side')} | {tr.get('pnl_r')} | {tr.get('entry_time_ms')} | {tr.get('exit_time_ms')} | {tr.get('reason')} | {idem} | {tr.get('trade_id')} |")

    if api_compare is not None:
        lines.append("")
        lines.append("## API /v1/backtest-compare 返回（可选）")
        lines.append("```json")
        lines.append(json.dumps(api_compare, ensure_ascii=False, indent=2))
        lines.append("```")

    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--timeframe", required=True, help="与 bars.timeframe 一致，例如 60/240/D")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--run-id", default="", help="可选：指定 run_id（不填则 replay_backtest 会生成）")
    ap.add_argument("--timeout-sec", type=int, default=300)
    ap.add_argument("--api-url", default="", help="可选：如 http://127.0.0.1:8000，脚本会额外拉取 /v1/backtest-compare")
    args = ap.parse_args()

    # 1) 确保 streams/groups
    c = RedisStreamsClient(settings.redis_url)
    for s in STREAMS:
        c.ensure_group(s, settings.redis_stream_group)

    # 2) 执行回放（复用 replay_backtest.py 的 main 逻辑：直接 import 调用）
    from scripts.replay_backtest import main as replay_main  # noqa

    # 通过 sys.argv 方式最简单稳定（避免重写 replay 逻辑）
    import sys
    run_id = args.run_id.strip()
    argv = [
        "scripts/replay_backtest.py",
        "--symbol", args.symbol,
        "--timeframe", args.timeframe,
        "--limit", str(args.limit),
    ]
    if run_id:
        argv += ["--run-id", run_id]
    sys.argv = argv
    replay_main()

    # replay_main 可能生成 run_id（stdout 已打印）。为了拿到 run_id，我们从 bars 回放事件里取最近 run_id：
    if not run_id:
        # 从 Redis 最末一条 bar_close 读取 ext.run_id（只用于报告，逻辑上足够可靠）
        try:
            last = c.r.xrevrange("stream:bar_close", count=1)
            if last:
                _mid, fields = last[0]
                evt = json.loads(fields.get("json")) if "json" in fields else fields
                run_id = ((evt.get("payload") or {}).get("ext") or {}).get("run_id") or ""
        except Exception:
            run_id = ""

    if not run_id:
        raise SystemExit("无法获取 run_id：建议显式传 --run-id")

    # 3) 等待链路处理完成/空闲
    wait = _wait_until_idle(settings.redis_url, settings.redis_stream_group, run_id, timeout_sec=args.timeout_sec)

    # 4) 统计 + trades
    stats = {
        "signals": _db_count_jsonb_run_id("signals", run_id),
        "trade_plans": _db_count_jsonb_run_id("trade_plans", run_id),
        "orders": _db_count_orders_run_id(run_id),
        "execution_reports": _db_count_jsonb_run_id("execution_reports", run_id),
        "positions_open": _db_count_positions(run_id, "OPEN"),
        "positions_closed": _db_count_positions(run_id, "CLOSED"),
        "backtest_trades": len(_db_list_backtest_trades(run_id, limit=100000)),
    }
    trades = _db_list_backtest_trades(run_id, limit=200)

    api_compare = None
    if args.api_url.strip():
        try:
            api_compare = requests.get(f"{args.api_url.rstrip('/')}/v1/backtest-compare", params={"run_id": run_id, "limit_trades": 50}, timeout=10.0).json()
        except Exception:
            api_compare = None

    # 5) 输出报告
    Path("reports").mkdir(exist_ok=True)
    out_json = Path("reports") / f"replay_{run_id}.json"
    out_md = Path("reports") / f"replay_{run_id}.md"

    blob = {"run_id": run_id, "stats": stats, "wait": wait, "trades": trades, "api_compare": api_compare}
    out_json.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(_render_md(run_id, args, stats, trades, wait, api_compare), encoding="utf-8")

    print("OK: report generated:", str(out_md), str(out_json))


if __name__ == "__main__":
    main()
