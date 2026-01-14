#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实盘下单测试脚本

⚠️ 警告：此脚本会真实下单！请确保：
1. EXECUTION_MODE=LIVE
2. RISK_PCT 设置合理（建议 ≤ 0.001）
3. 准备好紧急停止方案
4. 在 Bybit 交易所验证订单

使用方法：
  python scripts/live_trade_test.py --symbol BTCUSDT --side BUY --entry-price 30000 --sl-price 29000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any, Dict

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    import redis
    from libs.common.config import settings
    from libs.common.time import now_ms
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    print("\n💡 提示：在 Docker 容器中运行：")
    print("   docker compose exec execution python -m scripts.live_trade_test --help")
    sys.exit(1)


def build_trade_plan(
    symbol: str,
    timeframe: str,
    side: str,
    entry_price: float,
    sl_price: float,
    env: str = "prod",
) -> Dict[str, Any]:
    """构建 trade_plan 事件"""
    now = now_ms()
    plan_id = f"live-test-{uuid.uuid4().hex[:12]}"
    idem = f"idem-{uuid.uuid4().hex}"

    event = {
        "event_id": f"evt-{uuid.uuid4().hex}",
        "ts_ms": now,
        "env": env,
        "service": "strategy-service",
        "schema_version": 1,
        "payload": {
            "plan_id": plan_id,
            "idempotency_key": idem,
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "entry_price": entry_price,
            "primary_sl_price": sl_price,
            "tp_rules": {
                "tp1": {"r": 1.0, "pct": 0.4},
                "tp2": {"r": 2.0, "pct": 0.4},
                "tp3_trail": {"pct": 0.2, "mode": "ATR"},
                "reduce_only": True,
            },
            "secondary_sl_rule": {"type": "NEXT_BAR_NOT_SHORTEN_EXIT"},
            "traceability": {"setup_id": "live-test-setup", "trigger_id": "live-test-trigger"},
            "ext": {"live_test": True, "manual_inject": True},
        },
    }
    return event


def publish_event(
    r: redis.Redis, stream: str, event: Dict[str, Any], event_type: str = "TRADE_PLAN"
) -> str:
    """发布事件到 Redis Streams"""
    payload: Dict[str, Any] = {"json": json.dumps(event, ensure_ascii=False)}
    if event_type:
        payload["type"] = event_type
    return r.xadd(stream, payload)


def check_execution_result(
    r: redis.Redis, plan_id: str, idempotency_key: str, wait_seconds: int = 30
) -> None:
    """检查执行结果"""
    print(f"\n⏳ 等待 {wait_seconds} 秒让执行服务处理...")
    time.sleep(wait_seconds)

    print("\n" + "=" * 60)
    print("  检查执行结果")
    print("=" * 60)

    # 检查 execution_report
    print("\n📊 执行报告 (stream:execution_report):")
    reports = r.xrevrange("stream:execution_report", max="+", min="-", count=50)
    related_reports = []
    for msg_id, fields in reports:
        if "json" in fields:
            try:
                evt = json.loads(fields["json"])
                payload = evt.get("payload", {})
                if (
                    payload.get("plan_id") == plan_id
                    or payload.get("idempotency_key") == idempotency_key
                ):
                    related_reports.append(evt)
            except Exception:
                pass

    if related_reports:
        print(f"   找到 {len(related_reports)} 个相关执行报告:")
        for i, rep in enumerate(related_reports[:5], 1):
            payload = rep.get("payload", {})
            print(f"   {i}. {payload.get('typ')} - {payload.get('status')} - {payload.get('symbol')}")
            if payload.get("detail"):
                detail = payload.get("detail", {})
                if isinstance(detail, dict):
                    reason = detail.get("reason", "")
                    if reason:
                        print(f"      原因: {reason}")
    else:
        print("   ⚠️  未找到相关执行报告")

    # 检查 risk_event
    print("\n⚠️  风险事件 (stream:risk_event):")
    risk_events = r.xrevrange("stream:risk_event", max="+", min="-", count=50)
    related_risks = []
    for msg_id, fields in risk_events:
        if "json" in fields:
            try:
                evt = json.loads(fields["json"])
                payload = evt.get("payload", {})
                detail = payload.get("detail", {}) if isinstance(payload.get("detail"), dict) else {}
                if (
                    detail.get("existing_idempotency_key") == idempotency_key
                    or detail.get("incoming_idempotency_key") == idempotency_key
                ):
                    related_risks.append(evt)
            except Exception:
                pass

    if related_risks:
        print(f"   找到 {len(related_risks)} 个相关风险事件:")
        for i, risk in enumerate(related_risks[:5], 1):
            payload = risk.get("payload", {})
            print(f"   {i}. {payload.get('type')} - {payload.get('severity')} - {payload.get('symbol')}")
    else:
        print("   ✅ 未找到相关风险事件")

    print("\n" + "=" * 60)
    print("  验证步骤")
    print("=" * 60)
    print("\n1. 查看执行服务日志：")
    print("   docker compose logs execution | tail -50")
    print("\n2. 查询数据库订单：")
    print(f"   docker compose exec execution psql \"$DATABASE_URL\" -c \"")
    print(f"   SELECT order_id, symbol, side, order_type, qty, status, bybit_order_id, created_at")
    print(f"   FROM orders WHERE idempotency_key='{idempotency_key}' ORDER BY created_at DESC;\"")
    print("\n3. 查询数据库持仓：")
    print(f"   docker compose exec execution psql \"$DATABASE_URL\" -c \"")
    print(f"   SELECT position_id, symbol, side, qty_total, status, created_at")
    print(f"   FROM positions WHERE idempotency_key='{idempotency_key}' ORDER BY created_at DESC;\"")
    print("\n4. 在 Bybit 交易所验证：")
    print("   - 登录 Bybit 交易所")
    print("   - 查看'订单'页面，确认订单已创建")
    print("   - 查看'持仓'页面，确认持仓正确")
    print("   - 查看'条件单'页面，确认止损/止盈已设置")


def main():
    ap = argparse.ArgumentParser(
        description="实盘下单测试脚本（⚠️ 会真实下单！）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 测试做多 BTCUSDT
  python scripts/live_trade_test.py \\
    --symbol BTCUSDT \\
    --side BUY \\
    --entry-price 30000 \\
    --sl-price 29000

  # 测试做空 ETHUSDT
  python scripts/live_trade_test.py \\
    --symbol ETHUSDT \\
    --side SELL \\
    --entry-price 2000 \\
    --sl-price 2100 \\
    --timeframe 1h
        """,
    )
    ap.add_argument("--symbol", required=True, help="交易对，如 BTCUSDT")
    ap.add_argument("--side", required=True, choices=["BUY", "SELL"], help="方向：BUY 或 SELL")
    ap.add_argument("--entry-price", type=float, required=True, help="入场价格")
    ap.add_argument("--sl-price", type=float, required=True, help="止损价格")
    ap.add_argument("--timeframe", default="15m", help="时间框架（默认: 15m）")
    ap.add_argument("--wait-seconds", type=int, default=30, help="等待执行的时间（秒，默认: 30）")
    ap.add_argument("--confirm", action="store_true", help="跳过确认提示（谨慎使用）")

    args = ap.parse_args()

    # 检查执行模式
    if str(settings.execution_mode).upper() != "LIVE":
        print("❌ 错误：当前执行模式不是 LIVE")
        print(f"   当前模式: {settings.execution_mode}")
        print("   请设置 EXECUTION_MODE=LIVE 后再运行")
        sys.exit(1)

    # 检查 Bybit API
    if not settings.bybit_api_key or not settings.bybit_api_secret:
        print("❌ 错误：未配置 Bybit API Key/Secret")
        print("   请在 .env 文件中设置 BYBIT_API_KEY 和 BYBIT_API_SECRET")
        sys.exit(1)

    # 显示配置信息
    print("=" * 60)
    print("  实盘下单测试")
    print("=" * 60)
    print("\n⚠️  警告：此操作会真实下单！")
    print(f"\n配置信息：")
    print(f"  执行模式: {settings.execution_mode}")
    print(f"  风险百分比: {settings.risk_pct} ({settings.risk_pct * 100}%)")
    print(f"  最大持仓数: {settings.max_open_positions}")
    print(f"  账户熔断: {'启用' if settings.account_kill_switch_enabled else '未启用'}")
    print(f"\n交易参数：")
    print(f"  交易对: {args.symbol}")
    print(f"  方向: {args.side}")
    print(f"  时间框架: {args.timeframe}")
    print(f"  入场价格: {args.entry_price}")
    print(f"  止损价格: {args.sl_price}")

    # 确认
    if not args.confirm:
        print("\n" + "=" * 60)
        response = input("确认继续？输入 'yes' 继续: ")
        if response.lower() != "yes":
            print("取消操作")
            sys.exit(0)

    # 连接 Redis
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
    except Exception as e:
        print(f"❌ Redis 连接失败: {e}")
        sys.exit(1)

    # 构建并发布 trade_plan
    print("\n📤 构建 trade_plan...")
    event = build_trade_plan(
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        side=args.side.upper(),
        entry_price=args.entry_price,
        sl_price=args.sl_price,
        env=settings.env,
    )

    plan_id = event["payload"]["plan_id"]
    idempotency_key = event["payload"]["idempotency_key"]

    print(f"   Plan ID: {plan_id}")
    print(f"   Idempotency Key: {idempotency_key}")

    print("\n📨 发布 trade_plan 到 Redis Streams...")
    msg_id = publish_event(r, "stream:trade_plan", event, event_type="TRADE_PLAN")
    print(f"   ✅ 已发布，消息 ID: {msg_id}")

    # 检查执行结果
    check_execution_result(r, plan_id, idempotency_key, wait_seconds=args.wait_seconds)

    print("\n✅ 测试完成！")
    print("\n💡 提示：")
    print("   - 查看执行服务日志了解详细执行过程")
    print("   - 在 Bybit 交易所验证订单是否真实创建")
    print("   - 如果订单被拒绝，查看执行报告了解原因")


if __name__ == "__main__":
    main()
