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
    from libs.bybit.market_rest import BybitMarketRestClient
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
    
    # orders 命令
    orders_parser = subparsers.add_parser('orders', help='查看订单')
    orders_parser.add_argument('--idempotency-key', help='按 idempotency_key 过滤')
    orders_parser.add_argument('--limit', type=int, default=10, help='限制返回数量（默认: 10）')
    
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
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
