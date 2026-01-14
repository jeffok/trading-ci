#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易系统测试工具
统一管理所有测试功能：准备检查、查看持仓、清理持仓、执行测试下单等
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import redis
    from libs.common.config import settings
    from libs.common.time import now_ms
    from libs.db.pg import get_conn
    from libs.bybit.market_rest import BybitMarketRestClient, MarketRestV5Client
    from libs.bybit.trade_rest_v5 import TradeRestV5Client
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    print("\n💡 提示：在 Docker 容器中运行：")
    print("   docker compose exec execution python -m scripts.trading_test_tool --help")
    sys.exit(1)

# 颜色定义
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'

def print_info(msg: str):
    print(f"{Colors.BLUE}[INFO]{Colors.NC} {msg}")

def print_success(msg: str):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {msg}")

def print_error(msg: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")

def print_warning(msg: str):
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {msg}")

# ==================== 准备检查功能 ====================

def check_config() -> bool:
    """检查配置"""
    print_info("检查配置...")
    
    if str(settings.execution_mode).upper() != "LIVE":
        print_error(f"EXECUTION_MODE 不是 LIVE")
        print(f"   当前值: {settings.execution_mode}")
        print("   请设置: EXECUTION_MODE=LIVE")
        return False
    print_success("EXECUTION_MODE=LIVE")
    
    if not settings.bybit_api_key or not settings.bybit_api_secret:
        print_error("Bybit API Key/Secret 未配置")
        print("   请设置: BYBIT_API_KEY 和 BYBIT_API_SECRET")
        return False
    print_success("Bybit API Key/Secret 已配置")
    
    return True

def check_service_status() -> bool:
    """检查服务状态"""
    print_info("检查服务状态...")
    
    try:
        import requests
        health_url = "http://localhost:8003/health"
        response = requests.get(health_url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("execution_mode") == "LIVE":
                print_success("执行服务健康检查通过")
                return True
            else:
                print_warning(f"执行服务运行中，但模式是 {data.get('execution_mode')}")
                return True
        else:
            print_warning("无法访问健康检查端点，但服务可能在运行")
            return True
    except ImportError:
        print_warning("未安装 requests 库，跳过健康检查")
        return True
    except Exception as e:
        print_warning(f"健康检查失败: {e}")
        print_info("请手动检查服务状态: docker compose ps execution")
        return True

def check_all_services_health() -> bool:
    """检查所有服务的健康状态"""
    DEFAULT_PORTS = {
        "api": 8000,
        "marketdata": 8001,
        "strategy": 8002,
        "execution": 8003,
        "notifier": 8004,
    }
    
    print_info("检查所有服务健康状态...")
    ok = True
    
    try:
        import requests
        base_url = "http://localhost"
        
        for name, port in DEFAULT_PORTS.items():
            url = f"{base_url}:{port}/health"
            try:
                response = requests.get(url, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    print_success(f"{name:12s} {url} -> OK")
                else:
                    ok = False
                    print_error(f"{name:12s} {url} -> {response.status_code}")
            except Exception as e:
                ok = False
                print_error(f"{name:12s} {url} -> {str(e)}")
        
        return ok
    except ImportError:
        print_warning("未安装 requests 库，跳过健康检查")
        return True
    except Exception as e:
        print_warning(f"健康检查失败: {e}")
        return False

def check_redis_streams() -> bool:
    """检查 Redis Streams 状态"""
    print_info("检查 Redis Streams 状态...")
    
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        print_success("Redis 连接正常")
        
        streams = [
            "stream:dlq",
            "stream:bar_close",
            "stream:signal",
            "stream:trade_plan",
            "stream:execution_report",
            "stream:risk_event",
        ]
        
        for stream in streams:
            try:
                info = r.xinfo_stream(stream)
                groups = r.xinfo_groups(stream)
                length = info.get("length", 0)
                last_id = info.get("last-generated-id", "0-0")
                print_info(f"  {stream}: length={length}, last_id={last_id}, groups={len(groups)}")
            except Exception as e:
                print_warning(f"  {stream}: {str(e)}")
        
        return True
    except Exception as e:
        print_error(f"Redis 检查失败: {e}")
        return False

def show_config():
    """显示当前配置"""
    print_info("当前风险配置...")
    print(f"   RISK_PCT: {settings.risk_pct}")
    print(f"   MAX_OPEN_POSITIONS: {settings.max_open_positions}")
    print(f"   ACCOUNT_KILL_SWITCH_ENABLED: {settings.account_kill_switch_enabled}")
    print(f"   RISK_CIRCUIT_ENABLED: {settings.risk_circuit_enabled}")
    print(f"   DAILY_LOSS_LIMIT_PCT: {getattr(settings, 'daily_loss_limit_pct', '未设置')}")

def cmd_prepare():
    """准备检查命令"""
    print("=" * 60)
    print("  实盘下单测试准备")
    print("=" * 60)
    print()
    
    if not check_config():
        sys.exit(1)
    
    print()
    check_all_services_health()
    print()
    check_redis_streams()
    print()
    show_config()
    print()
    
    print_success("准备完成！")
    print()
    print_warning("⚠️  重要提醒：")
    print("   1. 确保 RISK_PCT ≤ 0.001（0.1%）")
    print("   2. 实时监控执行服务日志")
    print("   3. 在 Bybit 交易所验证订单")
    print("   4. 准备好紧急停止方案")

# ==================== 查看持仓功能 ====================

def show_open_positions(detailed: bool = False) -> List[Dict[str, Any]]:
    """显示所有 OPEN 持仓"""
    db_url = settings.database_url
    
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            if detailed:
                cur.execute("""
                    SELECT 
                        position_id,
                        idempotency_key,
                        symbol,
                        timeframe,
                        side,
                        qty_total,
                        entry_price,
                        primary_sl_price,
                        status,
                        created_at,
                        CASE 
                            WHEN position_id LIKE 'paper-%' THEN 'PAPER模式'
                            WHEN idempotency_key LIKE 'paper-%' THEN 'PAPER模式'
                            WHEN idempotency_key LIKE 'idem-%' THEN '测试注入'
                            ELSE '未知来源'
                        END as source_type
                    FROM positions 
                    WHERE status = 'OPEN'
                    ORDER BY created_at DESC;
                """)
            else:
                cur.execute("""
                    SELECT 
                        position_id,
                        idempotency_key,
                        symbol,
                        side,
                        qty_total,
                        status,
                        created_at
                    FROM positions 
                    WHERE status = 'OPEN'
                    ORDER BY created_at DESC;
                """)
            
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            
            if not rows:
                print("没有找到 OPEN 持仓")
                return []
            
            # 打印表头
            header = " | ".join(f"{col:30}" for col in cols)
            print(header)
            print("-" * len(header))
            
            # 打印数据
            positions = []
            for row in rows:
                pos_dict = dict(zip(cols, row))
                positions.append(pos_dict)
                row_str = " | ".join(f"{str(v) if v is not None else 'NULL':30}" for v in row)
                print(row_str)
            
            # 统计信息
            print()
            print_info("持仓数量统计：")
            cur.execute("""
                SELECT 
                    COUNT(*) as total_open,
                    COUNT(CASE WHEN position_id LIKE 'paper-%' OR idempotency_key LIKE 'paper-%' THEN 1 END) as paper_count,
                    COUNT(CASE WHEN idempotency_key LIKE 'idem-%' THEN 1 END) as test_count
                FROM positions 
                WHERE status = 'OPEN';
            """)
            
            stats = dict(zip(['total_open', 'paper_count', 'test_count'], cur.fetchone()))
            print(f"  总 OPEN 持仓数: {stats['total_open']}")
            print(f"  PAPER 模式持仓: {stats['paper_count']}")
            print(f"  测试注入持仓: {stats['test_count']}")
            
            return positions

def cmd_positions(args):
    """查看持仓命令"""
    print("=" * 60)
    print("  查看所有 OPEN 持仓")
    print("=" * 60)
    print()
    
    show_open_positions(detailed=args.detailed)

# ==================== 清理持仓功能 ====================

def close_position(position_id: str) -> bool:
    """关闭指定持仓"""
    db_url = settings.database_url
    
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            # 先检查是否存在
            cur.execute("""
                SELECT position_id, symbol, side, qty_total, status 
                FROM positions 
                WHERE (position_id = %s OR idempotency_key = %s OR position_id LIKE %s)
                AND status = 'OPEN';
            """, (position_id, position_id, f"{position_id}%"))
            
            row = cur.fetchone()
            if not row:
                print_error(f"未找到匹配的 OPEN 持仓: {position_id}")
                return False
            
            print_success(f"找到持仓: {dict(zip(['position_id', 'symbol', 'side', 'qty_total', 'status'], row))}")
            
            # 关闭持仓
            cur.execute("""
                UPDATE positions 
                SET 
                    status = 'CLOSED',
                    updated_at = now(),
                    closed_at_ms = extract(epoch from now())::bigint * 1000,
                    exit_reason = 'MANUAL_FORCE_CLOSE'
                WHERE (position_id = %s OR idempotency_key = %s OR position_id LIKE %s)
                AND status = 'OPEN'
                RETURNING position_id;
            """, (position_id, position_id, f"{position_id}%"))
            
            result = cur.fetchone()
            conn.commit()
            
            if result:
                print_success(f"已关闭持仓: {result[0]}")
                return True
            else:
                print_error("关闭失败")
                return False

def close_all_positions(confirm: bool = False) -> int:
    """关闭所有 OPEN 持仓"""
    db_url = settings.database_url
    
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            # 先查询所有 OPEN 持仓
            cur.execute("""
                SELECT 
                    position_id,
                    idempotency_key,
                    symbol,
                    side,
                    qty_total
                FROM positions 
                WHERE status = 'OPEN'
                ORDER BY created_at DESC;
            """)
            
            positions = cur.fetchall()
            
            if not positions:
                print("没有找到 OPEN 持仓")
                return 0
            
            print_warning(f"找到 {len(positions)} 个 OPEN 持仓，将全部关闭")
            print()
            
            if not confirm:
                response = input("确认关闭所有 OPEN 持仓? (yes/no): ")
                if response.lower() not in ['yes', 'y']:
                    print("取消操作")
                    return 0
            
            # 关闭所有
            cur.execute("""
                UPDATE positions 
                SET 
                    status = 'CLOSED',
                    updated_at = now(),
                    closed_at_ms = extract(epoch from now())::bigint * 1000,
                    exit_reason = 'MANUAL_FORCE_CLOSE'
                WHERE status = 'OPEN'
                RETURNING position_id;
            """)
            
            closed = cur.fetchall()
            conn.commit()
            
            print_success(f"已关闭 {len(closed)} 个持仓")
            for pos in closed:
                print(f"   - {pos[0]}")
            
            return len(closed)

def cmd_clean(args):
    """清理持仓命令"""
    print("=" * 60)
    print("  清理持仓")
    print("=" * 60)
    print()
    
    if args.all:
        close_all_positions(confirm=args.yes)
    elif args.position_id:
        if not args.yes:
            show_open_positions()
            print()
            response = input(f"确认关闭持仓 {args.position_id}? (yes/no): ")
            if response.lower() not in ['yes', 'y']:
                print("取消操作")
                return
        
        close_position(args.position_id)
    else:
        print_error("请指定 --all 或 <position_id>")
        return
    
    # 验证结果
    print()
    print_info("验证结果...")
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN';")
            remaining = cur.fetchone()[0]
            
            if remaining == 0:
                print_success("所有 OPEN 持仓已清理")
            else:
                print_warning(f"仍有 {remaining} 个 OPEN 持仓")

# ==================== 获取市场价格功能 ====================

def get_current_market_price(symbol: str) -> Optional[float]:
    """获取当前市场价格（使用最新 K 线收盘价）"""
    try:
        client = BybitMarketRestClient(base_url=settings.bybit_rest_base_url)
        klines = client.get_kline(
            symbol=symbol.upper(),
            interval="1",  # 1 分钟 K 线
            category=settings.bybit_category,
            limit=1,
        )
        if klines and len(klines) > 0:
            return float(klines[0]["close"])
        return None
    except Exception as e:
        print_error(f"获取市场价格失败: {e}")
        return None

def calculate_entry_and_sl_prices(
    symbol: str,
    side: str,
    current_price: float,
    sl_distance_pct: float = 0.02,  # 默认止损距离 2%
) -> Tuple[float, float]:
    """根据当前价格和方向计算入场价和止损价"""
    side_upper = side.upper()
    
    if side_upper == "BUY":
        # BUY: 入场价使用当前价格，止损价在当前价格下方
        entry_price = current_price
        sl_price = current_price * (1 - sl_distance_pct)
    elif side_upper == "SELL":
        # SELL: 入场价使用当前价格，止损价在当前价格上方
        entry_price = current_price
        sl_price = current_price * (1 + sl_distance_pct)
    else:
        raise ValueError(f"无效的 side: {side}")
    
    return entry_price, sl_price

# ==================== 执行测试下单功能 ====================

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
        # 兼容两种字段格式：json（旧格式）和 data（新格式）
        raw_data = fields.get("json") or fields.get("data")
        if raw_data:
            try:
                evt = json.loads(raw_data)
                payload = evt.get("payload", {})
                # 检查 plan_id 或 idempotency_key（可能在 payload 或 ext 中）
                ext = payload.get("ext", {}) or {}
                payload_idem = payload.get("idempotency_key") or ext.get("idempotency_key")
                payload_plan_id = payload.get("plan_id")
                if (
                    payload_plan_id == plan_id
                    or payload_idem == idempotency_key
                ):
                    related_reports.append(evt)
            except Exception:
                pass
    
    if related_reports:
        print(f"   找到 {len(related_reports)} 个相关执行报告:")
        for i, rep in enumerate(related_reports[:5], 1):
            payload = rep.get("payload", {})
            status = payload.get("status", "")
            symbol = payload.get("symbol", "")
            print(f"   {i}. 状态: {status}, 交易对: {symbol}")
            
            # 显示错误信息或原因
            detail = payload.get("detail", {})
            if isinstance(detail, dict):
                reason = detail.get("reason") or detail.get("error")
                if reason:
                    print(f"      原因: {reason}")
            
            # 显示 ext 中的信息
            ext = payload.get("ext", {})
            if isinstance(ext, dict):
                ext_detail = ext.get("detail", {})
                if isinstance(ext_detail, dict):
                    ext_reason = ext_detail.get("reason") or ext_detail.get("error")
                    if ext_reason:
                        print(f"      详细信息: {ext_reason}")
    else:
        print("   ⚠️  未找到相关执行报告")
    
    # 检查 risk_event
    print("\n⚠️  风险事件 (stream:risk_event):")
    risk_events = r.xrevrange("stream:risk_event", max="+", min="-", count=50)
    related_risks = []
    for msg_id, fields in risk_events:
        # 兼容两种字段格式：json（旧格式）和 data（新格式）
        raw_data = fields.get("json") or fields.get("data")
        if raw_data:
            try:
                evt = json.loads(raw_data)
                payload = evt.get("payload", {})
                detail = payload.get("detail", {}) if isinstance(payload.get("detail"), dict) else {}
                if (
                    detail.get("existing_idempotency_key") == idempotency_key
                    or detail.get("incoming_idempotency_key") == idempotency_key
                    or detail.get("idempotency_key") == idempotency_key
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
    print("\n2. 查看订单（通过此工具）：")
    print(f"   python -m scripts.trading_test_tool orders --idempotency-key {idempotency_key}")
    print("\n3. 查看持仓（通过此工具）：")
    print(f"   python -m scripts.trading_test_tool positions")
    print("\n4. 在 Bybit 交易所验证：")
    print("   - 登录 Bybit 交易所")
    print("   - 查看'订单'页面，确认订单已创建")
    print("   - 查看'持仓'页面，确认持仓正确")
    print("   - 查看'条件单'页面，确认止损/止盈已设置")

def cmd_test(args):
    """执行测试下单命令"""
    # 检查执行模式
    if str(settings.execution_mode).upper() != "LIVE":
        print_error("当前执行模式不是 LIVE")
        print(f"   当前模式: {settings.execution_mode}")
        print("   请设置 EXECUTION_MODE=LIVE 后再运行")
        sys.exit(1)
    
    # 检查 Bybit API
    if not settings.bybit_api_key or not settings.bybit_api_secret:
        print_error("未配置 Bybit API Key/Secret")
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
    
    # 自动获取或使用指定的价格
    entry_price = args.entry_price
    sl_price = args.sl_price
    
    if entry_price is None or sl_price is None:
        print_info(f"\n正在获取 {args.symbol} 的当前市场价格...")
        current_price = get_current_market_price(args.symbol)
        
        if current_price is None:
            print_error("无法获取市场价格，请手动指定 --entry-price 和 --sl-price")
            sys.exit(1)
        
        print_success(f"当前市场价格: {current_price}")
        
        # 计算入场价和止损价
        entry_price, sl_price = calculate_entry_and_sl_prices(
            symbol=args.symbol,
            side=args.side,
            current_price=current_price,
            sl_distance_pct=args.sl_distance_pct,
        )
        
        print_info(f"自动计算的价格：")
        print(f"  入场价格: {entry_price:.2f}")
        print(f"  止损价格: {sl_price:.2f} (距离: {args.sl_distance_pct * 100:.1f}%)")
    
    print(f"\n交易参数：")
    print(f"  交易对: {args.symbol}")
    print(f"  方向: {args.side}")
    print(f"  时间框架: {args.timeframe}")
    print(f"  入场价格: {entry_price}")
    print(f"  止损价格: {sl_price}")
    
    # 自动诊断（如果启用）
    if args.auto_diagnose:
        print("\n" + "=" * 60)
        print("  自动诊断（下单前检查）")
        print("=" * 60)
        diagnose_order_failure(args.symbol, args.side)
        print()
    
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
        print_error(f"Redis 连接失败: {e}")
        sys.exit(1)
    
    # 构建并发布 trade_plan
    print("\n📤 构建 trade_plan...")
    event = build_trade_plan(
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        side=args.side.upper(),
        entry_price=entry_price,
        sl_price=sl_price,
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

# ==================== 查看订单功能 ====================

def show_orders(idempotency_key: Optional[str] = None, limit: int = 10):
    """显示订单"""
    db_url = settings.database_url
    
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            if idempotency_key:
                cur.execute("""
                    SELECT 
                        order_id,
                        idempotency_key,
                        symbol,
                        side,
                        order_type,
                        qty,
                        price,
                        status,
                        bybit_order_id,
                        created_at
                    FROM orders
                    WHERE idempotency_key = %s
                    ORDER BY created_at DESC
                    LIMIT %s;
                """, (idempotency_key, limit))
            else:
                cur.execute("""
                    SELECT 
                        order_id,
                        idempotency_key,
                        symbol,
                        side,
                        order_type,
                        qty,
                        price,
                        status,
                        bybit_order_id,
                        created_at
                    FROM orders
                    ORDER BY created_at DESC
                    LIMIT %s;
                """, (limit,))
            
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            
            if not rows:
                print("没有找到订单")
                return
            
            # 打印表头
            header = " | ".join(f"{col:20}" for col in cols)
            print(header)
            print("-" * len(header))
            
            # 打印数据
            for row in rows:
                row_str = " | ".join(f"{str(v) if v is not None else 'NULL':20}" for v in row)
                print(row_str)

def cmd_orders(args):
    """查看订单命令"""
    print("=" * 60)
    print("  查看订单")
    print("=" * 60)
    print()
    
    show_orders(idempotency_key=args.idempotency_key, limit=args.limit)

# ==================== 诊断功能 ====================

def diagnose_order_failure(symbol: str, side: str):
    """诊断下单失败的原因"""
    print("=" * 60)
    print("  下单失败诊断")
    print("=" * 60)
    print()
    
    symbol_upper = symbol.upper()
    side_upper = side.upper()
    
    issues = []
    warnings = []
    
    # 1. 检查数据库中的 OPEN 持仓
    print_info("1. 检查数据库中的 OPEN 持仓...")
    db_positions = []
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    position_id,
                    idempotency_key,
                    symbol,
                    timeframe,
                    side,
                    qty_total,
                    entry_price,
                    primary_sl_price,
                    status,
                    created_at
                FROM positions 
                WHERE status = 'OPEN' AND symbol = %s
                ORDER BY created_at DESC;
            """, (symbol_upper,))
            
            cols = [desc[0] for desc in cur.description]
            for row in cur.fetchall():
                db_positions.append(dict(zip(cols, row)))
    
    if db_positions:
        print_warning(f"   找到 {len(db_positions)} 个数据库中的 OPEN 持仓:")
        for pos in db_positions:
            pos_side = pos.get("side", "").upper()
            print(f"     - {pos['position_id']}: {pos['symbol']} {pos_side} qty={pos['qty_total']}")
            
            # 检查是否同方向
            if pos_side == side_upper:
                issues.append(f"数据库中存在同方向 OPEN 持仓: {pos['position_id']} ({pos_side})")
    else:
        print_success("   数据库中没有 OPEN 持仓")
    
    # 2. 检查 Bybit 交易所的实际持仓
    print_info("\n2. 检查 Bybit 交易所的实际持仓...")
    try:
        client = TradeRestV5Client(base_url=settings.bybit_rest_base_url)
        bybit_positions_resp = client.position_list(
            category=settings.bybit_category,
            symbol=symbol_upper
        )
        
        bybit_positions = []
        if bybit_positions_resp.get("retCode") == 0:
            result = bybit_positions_resp.get("result", {})
            bybit_list = result.get("list", [])
            
            for pos in bybit_list:
                size = float(pos.get("size", "0") or "0")
                if size > 0:
                    bybit_positions.append({
                        "symbol": pos.get("symbol", ""),
                        "side": pos.get("side", ""),
                        "size": size,
                        "entry_price": float(pos.get("avgPrice", "0") or "0"),
                        "mark_price": float(pos.get("markPrice", "0") or "0"),
                        "unrealised_pnl": float(pos.get("unrealisedPnl", "0") or "0"),
                    })
        
        if bybit_positions:
            print_warning(f"   Bybit 交易所中有 {len(bybit_positions)} 个实际持仓:")
            for pos in bybit_positions:
                bybit_side = pos.get("side", "").upper()
                print(f"     - {pos['symbol']} {bybit_side} size={pos['size']} entry={pos['entry_price']}")
                
                # 检查是否同方向
                if bybit_side == side_upper:
                    issues.append(f"Bybit 交易所存在同方向持仓: {pos['symbol']} {bybit_side} size={pos['size']}")
        else:
            print_success("   Bybit 交易所中没有持仓")
            
        # 检查数据库和交易所的一致性
        if db_positions and not bybit_positions:
            warnings.append("数据库中有 OPEN 持仓，但 Bybit 交易所中没有对应持仓（可能是过期持仓）")
        elif not db_positions and bybit_positions:
            warnings.append("Bybit 交易所有持仓，但数据库中没有对应记录（需要同步）")
            
    except Exception as e:
        print_error(f"   无法获取 Bybit 持仓: {e}")
        issues.append(f"无法连接 Bybit API: {e}")
    
    # 3. 检查账户余额
    print_info("\n3. 检查账户余额...")
    try:
        client = TradeRestV5Client(base_url=settings.bybit_rest_base_url)
        wallet_resp = client.wallet_balance(
            account_type=settings.bybit_account_type,
            coin="USDT"
        )
        
        if wallet_resp.get("retCode") == 0:
            result = wallet_resp.get("result", {})
            wallet_list = result.get("list", [])
            if wallet_list:
                coin_list = wallet_list[0].get("coin", [])
                for coin in coin_list:
                    if coin.get("coin") == "USDT":
                        available = float(coin.get("availableToWithdraw", "0") or "0")
                        equity = float(coin.get("equity", "0") or "0")
                        print_success(f"   USDT 可用余额: {available:.2f}")
                        print_info(f"   USDT 总权益: {equity:.2f}")
                        
                        if available < 10:
                            warnings.append(f"账户余额较低: {available:.2f} USDT")
    except Exception as e:
        print_error(f"   无法获取账户余额: {e}")
        warnings.append(f"无法获取账户余额: {e}")
    
    # 4. 检查风险控制规则
    print_info("\n4. 检查风险控制规则...")
    print(f"   最大持仓数: {settings.max_open_positions}")
    print(f"   风险百分比: {settings.risk_pct} ({settings.risk_pct * 100}%)")
    print(f"   账户熔断: {'启用' if settings.account_kill_switch_enabled else '未启用'}")
    print(f"   风险熔断: {'启用' if settings.risk_circuit_enabled else '未启用'}")
    
    # 检查是否达到最大持仓数
    if db_positions:
        total_open = len(db_positions)
        if total_open >= settings.max_open_positions:
            issues.append(f"已达到最大持仓数限制: {total_open}/{settings.max_open_positions}")
    
    # 5. 检查最近的执行报告
    print_info("\n5. 检查最近的执行报告...")
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        reports = r.xrevrange("stream:execution_report", max="+", min="-", count=10)
        
        recent_reports = []
        for msg_id, fields in reports:
            raw_data = fields.get("json") or fields.get("data")
            if raw_data:
                try:
                    evt = json.loads(raw_data)
                    payload = evt.get("payload", {})
                    if payload.get("symbol") == symbol_upper:
                        recent_reports.append({
                            "status": payload.get("status", ""),
                            "detail": payload.get("detail", {}),
                            "ts_ms": evt.get("ts_ms", 0),
                        })
                except Exception:
                    pass
        
        if recent_reports:
            print_warning(f"   找到 {len(recent_reports)} 个相关执行报告:")
            for rep in recent_reports[:3]:
                status = rep.get("status", "")
                detail = rep.get("detail", {})
                reason = detail.get("reason") or detail.get("error") or "无详情"
                print(f"     - 状态: {status}, 原因: {reason}")
        else:
            print_success("   没有找到相关执行报告")
    except Exception as e:
        print_error(f"   无法检查执行报告: {e}")
    
    # 6. 总结和建议
    print("\n" + "=" * 60)
    print("  诊断总结")
    print("=" * 60)
    
    if issues:
        print_error("\n❌ 发现的问题（可能导致下单失败）:")
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
    else:
        print_success("\n✅ 未发现明显问题")
    
    if warnings:
        print_warning("\n⚠️  警告:")
        for i, warning in enumerate(warnings, 1):
            print(f"   {i}. {warning}")
    
    # 提供修复建议
    print("\n💡 修复建议:")
    if any("同方向" in issue for issue in issues):
        print("   1. 清理同方向的 OPEN 持仓:")
        print(f"      python -m scripts.trading_test_tool clean --all")
        print("   2. 或者关闭特定持仓:")
        print(f"      python -m scripts.trading_test_tool clean <position_id>")
    
    if any("最大持仓数" in issue for issue in issues):
        print("   1. 关闭部分持仓以释放额度")
        print("   2. 或增加 MAX_OPEN_POSITIONS 配置")
    
    if any("过期持仓" in warning for warning in warnings):
        print("   1. 清理数据库中的过期持仓:")
        print(f"      python -m scripts.trading_test_tool clean --all")
    
    if not issues and not warnings:
        print("   系统状态正常，如果仍然无法下单，请检查:")
        print("   1. 执行服务日志: docker compose logs execution | tail -50")
        print("   2. 风险事件: 检查 stream:risk_event")
        print("   3. 账户权限: 确认 API Key 有交易权限")

def cmd_diagnose(args):
    """诊断下单失败命令"""
    diagnose_order_failure(args.symbol, args.side)

# ==================== 持仓同步功能 ====================

def sync_positions_with_exchange(dry_run: bool = False) -> Dict[str, Any]:
    """同步数据库持仓与交易所持仓"""
    print("=" * 60)
    print("  持仓同步检查")
    print("=" * 60)
    print()
    
    if str(settings.execution_mode).upper() != "LIVE":
        print_error("持仓同步仅在 LIVE 模式下可用")
        return {"synced": 0, "errors": 0, "skipped": 0}
    
    try:
        from services.execution.position_sync import sync_positions
    except ImportError:
        print_error("无法导入 position_sync 模块")
        return {"synced": 0, "errors": 0, "skipped": 0}
    
    print_info("正在检查数据库中的 OPEN 持仓...")
    
    # 获取所有 OPEN 持仓
    db_positions = []
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    position_id,
                    idempotency_key,
                    symbol,
                    timeframe,
                    side,
                    qty_total,
                    entry_price,
                    status,
                    created_at
                FROM positions 
                WHERE status = 'OPEN'
                ORDER BY created_at DESC;
            """)
            
            cols = [desc[0] for desc in cur.description]
            for row in cur.fetchall():
                db_positions.append(dict(zip(cols, row)))
    
    if not db_positions:
        print_success("数据库中没有 OPEN 持仓，无需同步")
        return {"synced": 0, "errors": 0, "skipped": 0}
    
    print_info(f"找到 {len(db_positions)} 个数据库中的 OPEN 持仓")
    print()
    
    # 检查每个持仓在交易所的状态
    client = TradeRestV5Client(base_url=settings.bybit_rest_base_url)
    synced_count = 0
    error_count = 0
    skipped_count = 0
    
    for pos in db_positions:
        symbol = pos["symbol"]
        position_id = pos["position_id"]
        idem = pos["idempotency_key"]
        
        print_info(f"检查持仓: {position_id} ({symbol})")
        
        try:
            # 查询交易所持仓
            bybit_resp = client.position_list(
                category=settings.bybit_category,
                symbol=symbol
            )
            
            if bybit_resp.get("retCode") != 0:
                print_error(f"  查询失败: {bybit_resp.get('retMsg', '未知错误')}")
                error_count += 1
                continue
            
            result = bybit_resp.get("result", {})
            bybit_list = result.get("list", [])
            
            # 查找对应持仓
            exchange_size = 0.0
            exchange_side = None
            if bybit_list:
                for bp in bybit_list:
                    size = float(bp.get("size", "0") or "0")
                    if size > 0:
                        exchange_size = size
                        exchange_side = bp.get("side", "")
                        break
            
            # 判断是否需要同步
            if exchange_size == 0:
                # 交易所中没有持仓，但数据库中是 OPEN，需要关闭
                print_warning(f"  ⚠️  交易所中已平仓，但数据库中仍为 OPEN")
                print(f"     数据库状态: OPEN, qty={pos['qty_total']}")
                print(f"     交易所状态: 已平仓 (size=0)")
                
                if not dry_run:
                    # 直接更新数据库状态
                    try:
                        from services.execution.repo import mark_position_closed
                        from libs.common.time import now_ms
                        
                        meta = dict(pos.get("meta") or {})
                        exit_reason = "MANUAL_CLOSE"  # 手动平仓
                        
                        mark_position_closed(
                            database_url=settings.database_url,
                            position_id=position_id,
                            closed_at_ms=now_ms(),
                            exit_reason=exit_reason,
                            meta=meta
                        )
                        
                        print_success(f"  ✅ 已同步：将数据库状态更新为 CLOSED (exit_reason={exit_reason})")
                        synced_count += 1
                    except Exception as e:
                        print_error(f"  ❌ 同步失败: {e}")
                        error_count += 1
                else:
                    print_info(f"  [DRY RUN] 将更新为 CLOSED (exit_reason=MANUAL_CLOSE)")
                    skipped_count += 1
            else:
                # 交易所中仍有持仓
                print_success(f"  ✅ 状态一致：交易所中仍有持仓 (size={exchange_size}, side={exchange_side})")
                skipped_count += 1
                
        except Exception as e:
            print_error(f"  ❌ 检查失败: {e}")
            error_count += 1
        
        print()
    
    # 总结
    print("=" * 60)
    print("  同步结果")
    print("=" * 60)
    print(f"  已同步: {synced_count}")
    print(f"  跳过: {skipped_count}")
    print(f"  错误: {error_count}")
    
    if dry_run:
        print()
        print_info("这是 DRY RUN 模式，未实际修改数据库")
        print("  运行不带 --dry-run 参数来实际执行同步")
    
    return {
        "synced": synced_count,
        "skipped": skipped_count,
        "errors": error_count,
        "total": len(db_positions)
    }

def cmd_sync(args):
    """持仓同步命令"""
    sync_positions_with_exchange(dry_run=args.dry_run)

# ==================== 平仓测试功能 ====================

def cmd_close_test(args):
    """平仓测试命令（PAPER/BACKTEST 模式）"""
    print("=" * 60)
    print("  平仓测试（E2E Stage 2）")
    print("=" * 60)
    print()
    
    mode = str(settings.execution_mode).upper()
    if mode not in ("PAPER", "BACKTEST"):
        print_warning(f"当前模式: {mode}，建议使用 PAPER 或 BACKTEST 模式")
        response = input("是否继续？(yes/no): ")
        if response.lower() != "yes":
            return
    
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
    except Exception as e:
        print_error(f"Redis 连接失败: {e}")
        sys.exit(1)
    
    # 构建 trade_plan
    symbol = args.symbol.upper()
    timeframe = args.timeframe
    side = args.side.upper()
    entry_price = args.entry_price
    sl_price = args.sl_price
    
    print_info("构建 trade_plan...")
    event = build_trade_plan(
        symbol=symbol,
        timeframe=timeframe,
        side=side,
        entry_price=entry_price,
        sl_price=sl_price,
        env=settings.env,
    )
    
    plan_id = event["payload"]["plan_id"]
    idem = event["payload"]["idempotency_key"]
    
    print_success(f"Plan ID: {plan_id}")
    print_success(f"Idempotency Key: {idem}")
    
    # 发布 trade_plan
    print_info("发布 trade_plan 到 Redis Streams...")
    msg_id = publish_event(r, "stream:trade_plan", event, event_type="TRADE_PLAN")
    print_success(f"已发布，消息 ID: {msg_id}")
    
    # 等待持仓创建
    print_info(f"等待 {args.wait_before_close} 秒让持仓创建...")
    time.sleep(args.wait_before_close)
    
    # 强制平仓
    print_info("强制平仓（PAPER/BACKTEST 模式）...")
    try:
        from services.execution.executor import close_position_market
        
        close_position_market(
            database_url=settings.database_url,
            redis_url=settings.redis_url,
            idempotency_key=idem,
            symbol=symbol,
            side=side,
            close_price=args.close_price,
            close_time_ms=now_ms(),
            reason="close_test_force_close",
        )
        print_success("平仓请求已发送")
    except Exception as e:
        print_error(f"平仓失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # 等待报告生成
    print_info(f"等待 {args.wait_after_close} 秒让报告生成...")
    time.sleep(args.wait_after_close)
    
    # 检查执行报告
    print_info("检查执行报告...")
    reports = r.xrevrange("stream:execution_report", max="+", min="-", count=200)
    related_reports = []
    for msg_id, fields in reports:
        raw_data = fields.get("json") or fields.get("data")
        if raw_data:
            try:
                evt = json.loads(raw_data)
                payload = evt.get("payload", {})
                if payload.get("plan_id") == plan_id or payload.get("idempotency_key") == idem:
                    related_reports.append(evt)
            except Exception:
                pass
    
    if related_reports:
        print_success(f"找到 {len(related_reports)} 个相关执行报告:")
        for i, rep in enumerate(related_reports[:10], 1):
            payload = rep.get("payload", {})
            print(f"  {i}. {payload.get('status')} - {payload.get('symbol')}")
            detail = payload.get("detail", {})
            if isinstance(detail, dict):
                pnl = detail.get("pnl_usdt")
                if pnl is not None:
                    print(f"     PnL: {pnl:.2f} USDT")
    else:
        print_warning("未找到相关执行报告")
    
    # 检查风险事件
    print_info("检查风险事件...")
    risk_events = r.xrevrange("stream:risk_event", max="+", min="-", count=50)
    related_risks = []
    for msg_id, fields in risk_events:
        raw_data = fields.get("json") or fields.get("data")
        if raw_data:
            try:
                evt = json.loads(raw_data)
                payload = evt.get("payload", {})
                detail = payload.get("detail", {})
                if isinstance(detail, dict):
                    if detail.get("idempotency_key") == idem:
                        related_risks.append(evt)
            except Exception:
                pass
    
    if related_risks:
        print_warning(f"找到 {len(related_risks)} 个相关风险事件")
    else:
        print_success("未找到相关风险事件")
    
    print()
    print_success("平仓测试完成！")
    print_info("如果配置了 Telegram，应该会收到包含 PnL 和连续亏损统计的平仓消息")

# ==================== 风控测试功能 ====================

def cmd_gates_test(args):
    """风控闸门测试命令（PAPER/BACKTEST 模式）"""
    print("=" * 60)
    print("  风控闸门测试（E2E Stage 6）")
    print("=" * 60)
    print()
    
    mode = str(settings.execution_mode).upper()
    if mode not in ("PAPER", "BACKTEST"):
        print_warning(f"当前模式: {mode}，建议使用 PAPER 或 BACKTEST 模式")
        response = input("是否继续？(yes/no): ")
        if response.lower() != "yes":
            return
    
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=False)
        r.ping()
    except Exception as e:
        print_error(f"Redis 连接失败: {e}")
        sys.exit(1)
    
    # 重置数据库（如果指定）
    if args.reset_db:
        print_warning("重置数据库（TRUNCATE execution tables）...")
        try:
            import psycopg
            with psycopg.connect(settings.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("TRUNCATE TABLE orders, positions, cooldowns, execution_reports, risk_events, backtest_trades RESTART IDENTITY CASCADE;")
                conn.commit()
            print_success("数据库已重置")
            time.sleep(1)
        except Exception as e:
            print_error(f"重置数据库失败: {e}")
            sys.exit(1)
    
    def _xlast(stream: str) -> str:
        try:
            xs = r.xrevrange(stream, count=1)
            if xs:
                return xs[0][0].decode() if isinstance(xs[0][0], (bytes, bytearray)) else str(xs[0][0])
        except Exception:
            pass
        return "0-0"
    
    def _collect(stream: str, start_id: str, predicate, timeout_s: int = 15) -> List[Dict[str, Any]]:
        end = time.time() + timeout_s
        cur = start_id
        out: List[Dict[str, Any]] = []
        while time.time() < end:
            resp = r.xread({stream: cur}, count=100, block=500)
            if not resp:
                continue
            for _stream_name, items in resp:
                for xid, fields in items:
                    cur = xid.decode() if isinstance(xid, (bytes, bytearray)) else str(xid)
                    raw = fields.get(b"json") or fields.get("json")
                    if raw is None:
                        continue
                    try:
                        obj = json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
                    except Exception:
                        continue
                    if predicate(obj):
                        out.append(obj)
            if out:
                break
        return out
    
    def _build_trade_plan(symbol: str, timeframe: str, side: str, entry: float, sl: float, close_time_ms: int) -> Dict[str, Any]:
        plan_id = f"stage6-{uuid.uuid4().hex[:10]}"
        idem = f"idem-{uuid.uuid4().hex}"
        return {
            "event_id": f"evt-{uuid.uuid4().hex}",
            "ts_ms": now_ms(),
            "env": settings.env,
            "service": "e2e-stage6",
            "payload": {
                "plan_id": plan_id,
                "idempotency_key": idem,
                "symbol": symbol,
                "timeframe": timeframe,
                "side": side,
                "entry_price": float(entry),
                "primary_sl_price": float(sl),
                "risk_pct": 0.005,
                "close_time_ms": int(close_time_ms),
                "tp_rules": {
                    "tp1": {"r": 1.0, "pct": 0.4},
                    "tp2": {"r": 2.0, "pct": 0.4},
                    "tp3_trail": {"pct": 0.2, "mode": "ATR"},
                    "reduce_only": True,
                },
                "secondary_sl_rule": {"type": "NEXT_BAR_NOT_SHORTEN_EXIT"},
                "traceability": {"setup_id": "stage6", "trigger_id": "stage6"},
                "ext": {"run_id": "stage6-test"},
            },
        }
    
    def _build_bar_close(symbol: str, timeframe: str, close_time_ms: int, o: float, h: float, l: float, c: float) -> Dict[str, Any]:
        return {
            "event_id": f"evt-{uuid.uuid4().hex}",
            "ts_ms": now_ms(),
            "env": settings.env,
            "service": "e2e-stage6",
            "payload": {
                "symbol": symbol,
                "timeframe": timeframe,
                "close_time_ms": int(close_time_ms),
                "is_final": True,
                "source": "bybit_ws",
                "ohlcv": {"open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": 1.0},
                "ext": {"run_id": "stage6-test"},
            },
        }
    
    # 测试1: MAX_POSITIONS_BLOCKED
    print_info("[T1] 测试最大持仓数限制（第4个应该被拒绝）...")
    start_rep = _xlast("stream:execution_report")
    start_risk = _xlast("stream:risk_event")
    base_t = now_ms()
    syms = ["BTCUSDT", "ETHUSDT", "BCHUSDT", "LTCUSDT"]
    idems: List[str] = []
    
    for i, s in enumerate(syms):
        ev = _build_trade_plan(symbol=s, timeframe="1h", side="BUY", entry=100 + i, sl=90 + i, close_time_ms=base_t + i * 3600000)
        idems.append(ev["payload"]["idempotency_key"])
        publish_event(r, "stream:trade_plan", ev, event_type="trade_plan")
        time.sleep(0.2)
    
    rejected = _collect(
        "stream:execution_report",
        start_rep,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idems[-1]
        and str((obj.get("payload") or {}).get("status") or "").upper() in ("REJECTED", "ORDER_REJECTED", "ERROR"),
        timeout_s=args.wait,
    )
    if not rejected:
        print_error("T1 失败: 第4个计划未被拒绝")
        sys.exit(1)
    print_success("T1 通过: 第4个计划被正确拒绝")
    
    risk_max = _collect(
        "stream:risk_event",
        start_risk,
        lambda obj: str((obj.get("payload") or {}).get("type") or "").upper() == "MAX_POSITIONS_BLOCKED",
        timeout_s=args.wait,
    )
    if not risk_max:
        print_error("T1 失败: 未生成 MAX_POSITIONS_BLOCKED 风险事件")
        sys.exit(1)
    print_success("T1 通过: 生成了 MAX_POSITIONS_BLOCKED 风险事件")
    
    # 测试2: mutex upgrade
    print_info("[T2] 测试同币种同向互斥升级（4h 应该关闭 1h 并开新仓）...")
    if args.reset_db:
        import psycopg
        with psycopg.connect(settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE orders, positions, cooldowns, execution_reports, risk_events, backtest_trades RESTART IDENTITY CASCADE;")
            conn.commit()
        time.sleep(1)
    
    start_rep = _xlast("stream:execution_report")
    base_t = now_ms()
    ev1 = _build_trade_plan(symbol="BTCUSDT", timeframe="1h", side="BUY", entry=200, sl=180, close_time_ms=base_t)
    ev2 = _build_trade_plan(symbol="BTCUSDT", timeframe="4h", side="BUY", entry=200, sl=180, close_time_ms=base_t + 4 * 3600000)
    idem1 = ev1["payload"]["idempotency_key"]
    idem2 = ev2["payload"]["idempotency_key"]
    publish_event(r, "stream:trade_plan", ev1, event_type="trade_plan")
    time.sleep(0.5)
    publish_event(r, "stream:trade_plan", ev2, event_type="trade_plan")
    
    exited1 = _collect(
        "stream:execution_report",
        start_rep,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idem1
        and str((obj.get("payload") or {}).get("status") or "").upper() in ("EXITED", "POSITION_CLOSED", "PRIMARY_SL_HIT", "SECONDARY_SL_EXIT"),
        timeout_s=args.wait,
    )
    if not exited1:
        print_error("T2 失败: 低时间框架持仓未被关闭")
        sys.exit(1)
    print_success("T2 通过: 低时间框架持仓被关闭")
    
    filled2 = _collect(
        "stream:execution_report",
        start_rep,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idem2
        and str((obj.get("payload") or {}).get("status") or "").upper() in ("FILLED", "ORDER_SUBMITTED"),
        timeout_s=args.wait,
    )
    if not filled2:
        print_error("T2 失败: 高时间框架计划未执行")
        sys.exit(1)
    print_success("T2 通过: 高时间框架计划成功执行")
    
    # 测试3: cooldown
    print_info("[T3] 测试冷却期功能（止损后重新入场应该被阻止）...")
    import psycopg
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE orders, positions, cooldowns, execution_reports, risk_events, backtest_trades RESTART IDENTITY CASCADE;")
        conn.commit()
    time.sleep(1)
    
    start_rep = _xlast("stream:execution_report")
    start_risk = _xlast("stream:risk_event")
    base_t = now_ms()
    ev = _build_trade_plan(symbol="BTCUSDT", timeframe="1h", side="BUY", entry=100, sl=90, close_time_ms=base_t)
    idem = ev["payload"]["idempotency_key"]
    publish_event(r, "stream:trade_plan", ev, event_type="trade_plan")
    time.sleep(1)
    
    # 发布触发止损的 bar_close
    bc = _build_bar_close(symbol="BTCUSDT", timeframe="1h", close_time_ms=base_t + 3600000, o=100, h=100, l=80, c=85)
    publish_event(r, "stream:bar_close", bc, event_type="bar_close")
    
    sl_rep = _collect(
        "stream:execution_report",
        start_rep,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idem
        and str((obj.get("payload") or {}).get("status") or "").upper() in ("PRIMARY_SL_HIT", "SECONDARY_SL_EXIT", "POSITION_CLOSED"),
        timeout_s=args.wait,
    )
    if not sl_rep:
        print_error("T3 失败: 未生成止损平仓报告")
        sys.exit(1)
    print_success("T3 通过: 止损平仓报告已生成")
    
    # 尝试在冷却期内重新入场
    start_rep2 = _xlast("stream:execution_report")
    ev_re = _build_trade_plan(symbol="BTCUSDT", timeframe="1h", side="BUY", entry=100, sl=90, close_time_ms=base_t + 3600000)
    idem_re = ev_re["payload"]["idempotency_key"]
    publish_event(r, "stream:trade_plan", ev_re, event_type="trade_plan")
    
    reject_cd = _collect(
        "stream:execution_report",
        start_rep2,
        lambda obj: (obj.get("payload") or {}).get("idempotency_key") == idem_re
        and str((obj.get("payload") or {}).get("status") or "").upper() == "REJECTED",
        timeout_s=args.wait,
    )
    if not reject_cd:
        print_error("T3 失败: 冷却期内重新入场未被拒绝")
        sys.exit(1)
    
    risk_cd = _collect(
        "stream:risk_event",
        start_risk,
        lambda obj: str((obj.get("payload") or {}).get("type") or "").upper() == "COOLDOWN_BLOCKED",
        timeout_s=args.wait,
    )
    if not risk_cd:
        print_error("T3 失败: 未生成 COOLDOWN_BLOCKED 风险事件")
        sys.exit(1)
    print_success("T3 通过: 冷却期成功阻止重新入场")
    
    print()
    print_success("所有风控闸门测试通过！✅")

# ==================== 回放回测功能 ====================

def cmd_replay(args):
    """回放回测命令"""
    print("=" * 60)
    print("  回放回测")
    print("=" * 60)
    print()
    
    try:
        from libs.common.logging import setup_logging
        from libs.mq.redis_streams import RedisStreamsClient
        from libs.mq.events import publish_event
        from services.marketdata.publisher import build_bar_close_event
        from services.marketdata.repo_bars import upsert_bar
        from services.strategy.repo import get_bars, get_bars_range
        from libs.backtest.repo import insert_backtest_run, list_backtest_trades
        import hashlib
    except ImportError as e:
        print_error(f"导入失败: {e}")
        sys.exit(1)
    
    setup_logging("scripts/replay_backtest")
    
    symbol = args.symbol.upper()
    tf = args.timeframe
    
    def _gen_run_id(symbol: str, timeframe: str) -> str:
        seed = f"{symbol}|{timeframe}|{now_ms()}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    
    def _fetch_and_upsert(symbol: str, interval: str, limit: int) -> None:
        """从 Bybit REST 拉取最近 N 根（近似）并写库。"""
        from libs.bybit.market_rest import BybitMarketRestClient
        client = BybitMarketRestClient(base_url=settings.bybit_rest_base_url)
        bars = client.get_kline(symbol=symbol, interval=interval, limit=limit)
        bars = list(reversed(bars))
        for b in bars:
            start_ms = int(b["start_ms"])
            o = float(b["open"]); h = float(b["high"]); l = float(b["low"]); c = float(b["close"])
            v = float(b["volume"]); t = float(b.get("turnover")) if b.get("turnover") is not None else None
            if interval.isdigit():
                close_ms = start_ms + int(interval) * 60_000
            elif interval.upper() == "D":
                close_ms = start_ms + 24 * 60 * 60_000
            else:
                close_ms = start_ms
            upsert_bar(settings.database_url, symbol=symbol, timeframe=interval, open_time_ms=start_ms, close_time_ms=close_ms,
                       open=o, high=h, low=l, close=c, volume=v, turnover=t, source="REST")
    
    run_id = args.run_id or _gen_run_id(symbol, tf)
    
    if args.fetch:
        print_info(f"从 Bybit REST 拉取 {args.fetch_limit} 根 K 线...")
        _fetch_and_upsert(symbol, tf, args.fetch_limit)
        print_success("K 线数据已写入数据库")
    
    # 选择 bars
    bars: List[Dict[str, Any]] = []
    if args.start_ms and args.end_ms:
        bars = get_bars_range(settings.database_url, symbol=symbol, timeframe=tf, start_close_time_ms=args.start_ms, end_close_time_ms=args.end_ms)
    else:
        lim = int(args.limit or 0)
        if lim <= 0:
            print_error("请使用 --limit 或 --start-ms/--end-ms 指定回放范围")
            sys.exit(1)
        bars = list(reversed(get_bars(settings.database_url, symbol=symbol, timeframe=tf, limit=lim)))
    
    if not bars:
        print_error("bars 为空：请确认 bars 表已写入或使用 --fetch")
        sys.exit(1)
    
    client = RedisStreamsClient(settings.redis_url)
    
    print_info(f"Run ID: {run_id}")
    print_info(f"Bars 数量: {len(bars)}")
    print_info(f"Symbol: {symbol}")
    print_info(f"Timeframe: {tf}")
    print()
    
    # 发布 bar_close
    print_info("开始回放 bar_close 事件...")
    for i, b in enumerate(bars, start=1):
        evt = build_bar_close_event(
            symbol=symbol,
            timeframe=tf,
            close_time_ms=int(b["close_time_ms"]),
            source="REPLAY",
            ohlcv={
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b["volume"]),
            },
        )
        evt["payload"]["ext"] = {"run_id": run_id, "seq": i}
        publish_event(client, "stream:bar_close", evt, event_type="bar_close")
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)
        
        if i % 100 == 0:
            print_info(f"已回放 {i}/{len(bars)} 根 K 线...")
    
    print_success(f"已回放 {len(bars)} 根 K 线")
    
    # 生成并落库 backtest_run
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
        print_success(f"回测运行记录已创建: run_id={run_id}")
    except Exception as e:
        print_warning(f"创建回测运行记录失败: {e}")
    
    print()
    print_success("回放回测完成！")
    print_info(f"建议使用 /v1/backtest-compare?run_id={run_id} 检查闭环进度")

# ==================== 限流器自测功能 ====================

def cmd_ratelimit_test(args):
    """限流器自测命令"""
    print("=" * 60)
    print("  限流器自测")
    print("=" * 60)
    print()
    
    try:
        from libs.bybit.ratelimit import EndpointGroup, get_rate_limiter
        import random
    except ImportError as e:
        print_error(f"导入失败: {e}")
        sys.exit(1)
    
    rl = get_rate_limiter(settings)
    
    symbols = ["BTCUSDT", "ETHUSDT", "BCHUSDT", "SOLUSDT", "XRPUSDT"]
    
    print_info("限流器配置:")
    print(f"  max_wait_ms={rl.max_wait_ms}")
    print(f"  low_status_threshold={rl.low_status_threshold}")
    print()
    print_info("环境变量覆盖:")
    for k in [
        "BYBIT_PUBLIC_RPS",
        "BYBIT_PRIVATE_CRITICAL_RPS",
        "BYBIT_PRIVATE_ORDER_QUERY_RPS",
        "BYBIT_PRIVATE_ACCOUNT_QUERY_RPS",
        "BYBIT_PRIVATE_PER_SYMBOL_ORDER_QUERY_RPS",
        "BYBIT_PRIVATE_PER_SYMBOL_ACCOUNT_QUERY_RPS",
        "BYBIT_RATE_LIMIT_MAX_WAIT_MS",
    ]:
        val = getattr(settings, k.lower(), None)
        print(f"    {k}={val}")
    print()
    
    stats = {"crit_wait_ms": [], "order_query_wait_ms": [], "account_query_wait_ms": []}
    
    print_info("开始模拟请求（200 次）...")
    start = time.time()
    for i in range(200):
        sym = random.choice(symbols)
        r = random.random()
        if r < 0.25:
            gw, sw = rl.acquire(group=EndpointGroup.PRIVATE_CRITICAL, symbol=sym)
            w = max(gw, sw)
            stats["crit_wait_ms"].append(w)
        elif r < 0.70:
            gw, sw = rl.acquire(group=EndpointGroup.PRIVATE_ORDER_QUERY, symbol=sym)
            w = max(gw, sw)
            stats["order_query_wait_ms"].append(w)
        else:
            gw, sw = rl.acquire(group=EndpointGroup.PRIVATE_ACCOUNT_QUERY, symbol=sym)
            w = max(gw, sw)
            stats["account_query_wait_ms"].append(w)
        
        if i % 50 == 0 and i > 0:
            time.sleep(0.4)
    
    elapsed = (time.time() - start) * 1000
    
    def p(xs, q):
        if not xs:
            return 0
        xs2 = sorted(xs)
        idx = int((len(xs2) - 1) * q)
        return xs2[idx]
    
    print()
    print_info("结果统计（毫秒）:")
    for k in ["crit_wait_ms", "order_query_wait_ms", "account_query_wait_ms"]:
        xs = stats[k]
        if xs:
            mean = sum(xs) / len(xs)
            print(f"  {k}:")
            print(f"    n={len(xs)}")
            print(f"    mean={mean:.1f}")
            print(f"    p50={p(xs, 0.50)}")
            print(f"    p90={p(xs, 0.90)}")
            print(f"    p99={p(xs, 0.99)}")
            print(f"    max={max(xs)}")
        else:
            print(f"  {k}: n=0")
    
    print()
    print_success(f"完成，耗时: {elapsed:.0f}ms")

# ==================== WebSocket 处理自测功能 ====================

def cmd_ws_test(args):
    """WebSocket 处理自测命令"""
    print("=" * 60)
    print("  WebSocket 处理自测")
    print("=" * 60)
    print()
    
    try:
        import asyncio
        from services.execution.ws_private_ingest import handle_private_ws_message
    except ImportError as e:
        print_error(f"导入失败: {e}")
        sys.exit(1)
    
    SAMPLES = [
        {
            "topic": "order",
            "data": [{
                "symbol": "BCHUSDT",
                "orderId": "abc",
                "orderLinkId": "link_1",
                "orderStatus": "PartiallyFilled",
                "cumExecQty": "0.5",
                "avgPrice": "617.5"
            }]
        },
        {
            "topic": "execution",
            "data": [{
                "symbol": "BCHUSDT",
                "orderId": "abc",
                "orderLinkId": "link_1",
                "execId": "e1",
                "execQty": "0.5",
                "execPrice": "617.5",
                "cumExecQty": "0.5",
                "leavesQty": "0.71"
            }]
        },
        {
            "topic": "position",
            "data": [{
                "symbol": "BCHUSDT",
                "side": "Buy",
                "size": "1.21",
                "entryPrice": "617.5"
            }]
        },
        {
            "topic": "wallet",
            "data": [{
                "coin": [{"coin": "USDT", "walletBalance": "1000"}]
            }]
        }
    ]
    
    async def run_test():
        for i, m in enumerate(SAMPLES, start=1):
            topic = m.get('topic')
            print_info(f"测试样本 {i}: topic={topic}")
            try:
                await handle_private_ws_message(m)
                print_success(f"样本 {i} 处理成功")
            except Exception as e:
                print_error(f"样本 {i} 处理失败: {e}")
                import traceback
                traceback.print_exc()
            print()
    
    print_info("开始测试 WebSocket 消息处理...")
    print()
    asyncio.run(run_test())
    print_success("WebSocket 处理自测完成！")

# ==================== 主函数 ====================

def main():
    parser = argparse.ArgumentParser(
        description="交易系统测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 准备检查
  python -m scripts.trading_test_tool prepare

  # 查看持仓
  python -m scripts.trading_test_tool positions
  python -m scripts.trading_test_tool positions --detailed

  # 清理持仓
  python -m scripts.trading_test_tool clean --all
  python -m scripts.trading_test_tool clean --all --yes
  python -m scripts.trading_test_tool clean <position_id>

  # 执行测试下单（自动获取价格）
  python -m scripts.trading_test_tool test \\
    --symbol BTCUSDT \\
    --side BUY

  # 执行测试下单（手动指定价格）
  python -m scripts.trading_test_tool test \\
    --symbol BTCUSDT \\
    --side BUY \\
    --entry-price 30000 \\
    --sl-price 29000

  # 执行测试下单（自定义止损距离）
  python -m scripts.trading_test_tool test \\
    --symbol BTCUSDT \\
    --side BUY \\
    --sl-distance-pct 0.03

  # 查看订单
  python -m scripts.trading_test_tool orders
  python -m scripts.trading_test_tool orders --idempotency-key idem-xxx

  # 诊断下单失败原因
  python -m scripts.trading_test_tool diagnose \\
    --symbol BTCUSDT \\
    --side BUY

  # 同步持仓（检查并修复不一致）
  python -m scripts.trading_test_tool sync
  python -m scripts.trading_test_tool sync --dry-run  # 仅检查，不修改

  # 平仓测试（PAPER/BACKTEST 模式）
  python -m scripts.trading_test_tool close-test \\
    --symbol BTCUSDT --side BUY --entry-price 30000 --sl-price 29000

  # 风控闸门测试（PAPER/BACKTEST 模式）
  python -m scripts.trading_test_tool gates-test --reset-db

  # 回放回测
  python -m scripts.trading_test_tool replay \\
    --symbol BTCUSDT --timeframe 60 --limit 2000

  # 限流器自测
  python -m scripts.trading_test_tool ratelimit-test

  # WebSocket 处理自测
  python -m scripts.trading_test_tool ws-test
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # prepare 命令
    subparsers.add_parser('prepare', help='准备检查（检查配置、服务状态等）')
    
    # positions 命令
    pos_parser = subparsers.add_parser('positions', help='查看 OPEN 持仓')
    pos_parser.add_argument('--detailed', action='store_true', help='显示详细信息')
    
    # clean 命令
    clean_parser = subparsers.add_parser('clean', help='清理持仓')
    clean_parser.add_argument('position_id', nargs='?', help='持仓 ID（可选）')
    clean_parser.add_argument('--all', action='store_true', help='清理所有 OPEN 持仓')
    clean_parser.add_argument('--yes', action='store_true', help='跳过确认提示')
    
    # test 命令
    test_parser = subparsers.add_parser('test', help='执行测试下单（⚠️ 会真实下单！）')
    test_parser.add_argument('--symbol', required=True, help='交易对，如 BTCUSDT')
    test_parser.add_argument('--side', required=True, choices=['BUY', 'SELL'], help='方向：BUY 或 SELL')
    test_parser.add_argument('--entry-price', type=float, default=None, help='入场价格（可选，不指定则自动获取市场价格）')
    test_parser.add_argument('--sl-price', type=float, default=None, help='止损价格（可选，不指定则自动计算）')
    test_parser.add_argument('--sl-distance-pct', type=float, default=0.02, help='止损距离百分比（默认: 0.02，即 2%%）')
    test_parser.add_argument('--timeframe', default='15m', help='时间框架（默认: 15m）')
    test_parser.add_argument('--wait-seconds', type=int, default=30, help='等待执行的时间（秒，默认: 30）')
    test_parser.add_argument('--confirm', action='store_true', help='跳过确认提示（谨慎使用）')
    test_parser.add_argument('--auto-diagnose', action='store_true', help='下单前自动运行诊断检查')
    
    # orders 命令
    orders_parser = subparsers.add_parser('orders', help='查看订单')
    orders_parser.add_argument('--idempotency-key', help='按 idempotency_key 过滤')
    orders_parser.add_argument('--limit', type=int, default=10, help='限制返回数量（默认: 10）')
    
    # diagnose 命令
    diagnose_parser = subparsers.add_parser('diagnose', help='诊断下单失败原因')
    diagnose_parser.add_argument('--symbol', required=True, help='交易对，如 BTCUSDT')
    diagnose_parser.add_argument('--side', required=True, choices=['BUY', 'SELL'], help='方向：BUY 或 SELL')
    
    # sync 命令
    sync_parser = subparsers.add_parser('sync', help='同步数据库持仓与交易所持仓')
    sync_parser.add_argument('--dry-run', action='store_true', help='仅检查，不实际修改数据库')
    
    # close-test 命令
    close_test_parser = subparsers.add_parser('close-test', help='平仓测试（PAPER/BACKTEST 模式）')
    close_test_parser.add_argument('--symbol', default='BCHUSDT', help='交易对（默认: BCHUSDT）')
    close_test_parser.add_argument('--side', default='SELL', choices=['BUY', 'SELL'], help='方向（默认: SELL）')
    close_test_parser.add_argument('--timeframe', default='15m', help='时间框架（默认: 15m）')
    close_test_parser.add_argument('--entry-price', type=float, default=617.5, help='入场价格（默认: 617.5）')
    close_test_parser.add_argument('--sl-price', type=float, default=630.0, help='止损价格（默认: 630.0）')
    close_test_parser.add_argument('--wait-before-close', type=int, default=3, help='持仓创建后等待时间（秒，默认: 3）')
    close_test_parser.add_argument('--wait-after-close', type=int, default=3, help='平仓后等待时间（秒，默认: 3）')
    close_test_parser.add_argument('--close-price', type=float, default=623.7579, help='强制平仓价格（默认: 623.7579）')
    
    # gates-test 命令
    gates_test_parser = subparsers.add_parser('gates-test', help='风控闸门测试（PAPER/BACKTEST 模式）')
    gates_test_parser.add_argument('--reset-db', action='store_true', help='测试前重置数据库（TRUNCATE execution tables）')
    gates_test_parser.add_argument('--wait', type=int, default=10, help='等待超时时间（秒，默认: 10）')
    
    # replay 命令
    replay_parser = subparsers.add_parser('replay', help='回放回测（使用历史 bars 回放 bar_close 事件）')
    replay_parser.add_argument('--symbol', required=True, help='交易对，如 BTCUSDT')
    replay_parser.add_argument('--timeframe', required=True, help='时间框架，如 60(1h)/240(4h)/D(1d)')
    replay_parser.add_argument('--limit', type=int, default=0, help='从 DB 读取最近 N 根 bars 回放')
    replay_parser.add_argument('--start-ms', type=int, default=0, help='开始时间（毫秒时间戳）')
    replay_parser.add_argument('--end-ms', type=int, default=0, help='结束时间（毫秒时间戳）')
    replay_parser.add_argument('--run-id', default='', help='运行 ID（可选，默认自动生成）')
    replay_parser.add_argument('--sleep-ms', type=int, default=0, help='每次发布事件后的延迟（毫秒，默认: 0）')
    replay_parser.add_argument('--fetch', action='store_true', help='先从 Bybit REST 拉取 bars 写库')
    replay_parser.add_argument('--fetch-limit', type=int, default=2000, help='拉取的 bars 数量（默认: 2000）')
    
    # ratelimit-test 命令
    subparsers.add_parser('ratelimit-test', help='限流器自测（不调用 Bybit，仅测试限流逻辑）')
    
    # ws-test 命令
    subparsers.add_parser('ws-test', help='WebSocket 处理自测（测试消息解析与路由）')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # 执行对应命令
    if args.command == 'prepare':
        cmd_prepare()
    elif args.command == 'positions':
        cmd_positions(args)
    elif args.command == 'clean':
        cmd_clean(args)
    elif args.command == 'test':
        cmd_test(args)
    elif args.command == 'orders':
        cmd_orders(args)
    elif args.command == 'diagnose':
        cmd_diagnose(args)
    elif args.command == 'sync':
        cmd_sync(args)
    elif args.command == 'close-test':
        cmd_close_test(args)
    elif args.command == 'gates-test':
        cmd_gates_test(args)
    elif args.command == 'replay':
        cmd_replay(args)
    elif args.command == 'ratelimit-test':
        cmd_ratelimit_test(args)
    elif args.command == 'ws-test':
        cmd_ws_test(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
