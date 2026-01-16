#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号生成诊断工具
检查为什么没有信号生成
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from libs.common.config import settings
from libs.db.pg import get_conn
from libs.strategy.repo import get_bars
from libs.strategy.divergence import detect_three_segment_divergence
from libs.strategy.confluence import Candle, vegas_state, engulfing, rsi_divergence, obv_divergence, fvg_proximity
import redis

def print_section(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_info(msg: str):
    print(f"ℹ️  {msg}")

def print_success(msg: str):
    print(f"✅ {msg}")

def print_warning(msg: str):
    print(f"⚠️  {msg}")

def print_error(msg: str):
    print(f"❌ {msg}")

def check_market_data(symbol: str, timeframe: str):
    """检查市场数据"""
    print_section("1. 市场数据检查")
    
    bars = get_bars(settings.database_url, symbol=symbol, timeframe=timeframe, limit=500)
    bar_count = len(bars)
    
    print_info(f"交易对: {symbol}, 时间框架: {timeframe}")
    print_info(f"K 线数量: {bar_count}")
    
    if bar_count < 120:
        print_error(f"K 线数量不足！需要至少 120 根，当前只有 {bar_count} 根")
        print_warning("信号生成需要至少 120 根 K 线才能进行三段背离检测")
        return False, None
    
    print_success(f"K 线数量足够（{bar_count} >= 120）")
    
    if bars:
        latest = bars[-1]
        print_info(f"最新 K 线时间: {latest['close_time_ms']}")
        print_info(f"最新收盘价: {latest['close']}")
    
    return True, bars

def check_divergence(bars):
    """检查三段背离"""
    print_section("2. 三段背离检测")
    
    candles = [Candle(open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b["volume"]) for b in bars]
    close = [c.close for c in candles]
    high = [c.high for c in candles]
    low = [c.low for c in candles]
    
    setup = detect_three_segment_divergence(close=close, high=high, low=low)
    
    if setup is None:
        print_warning("未检测到三段背离")
        print_info("三段背离是信号生成的前提条件")
        print_info("需要 MACD histogram 形成三段顶/底背离结构")
        return False, None
    
    print_success(f"检测到三段背离！方向: {setup.direction}")
    print_info(f"  P1: index={setup.p1.index}, price={setup.p1.price:.2f}, hist={setup.h1:.4f}")
    print_info(f"  P2: index={setup.p2.index}, price={setup.p2.price:.2f}, hist={setup.h2:.4f}")
    print_info(f"  P3: index={setup.p3.index}, price={setup.p3.price:.2f}, hist={setup.h3:.4f}")
    
    return True, setup

def check_vegas(bars, bias):
    """检查 Vegas 状态"""
    print_section("3. Vegas 状态检查")
    
    candles = [Candle(open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b["volume"]) for b in bars]
    close = [c.close for c in candles]
    
    vs = vegas_state(close)
    print_info(f"当前 Vegas 状态: {vs}")
    print_info(f"信号方向: {bias}")
    
    if bias == "LONG" and vs != "Bullish":
        print_error(f"Vegas 状态不匹配！LONG 信号需要 Bullish，但当前是 {vs}")
        return False
    
    if bias == "SHORT" and vs != "Bearish":
        print_error(f"Vegas 状态不匹配！SHORT 信号需要 Bearish，但当前是 {vs}")
        return False
    
    print_success(f"Vegas 状态匹配（{bias} 需要 {vs}）")
    return True

def check_confirmations(bars, bias):
    """检查确认项"""
    print_section("4. 确认项检查")
    
    candles = [Candle(open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b["volume"]) for b in bars]
    
    hits = []
    
    # ENGULFING
    if engulfing(candles[-2:], bias):
        hits.append("ENGULFING")
        print_success("✅ ENGULFING（吞没形态）")
    else:
        print_warning("❌ ENGULFING（吞没形态）未命中")
    
    # RSI_DIV
    if rsi_divergence(candles, bias):
        hits.append("RSI_DIV")
        print_success("✅ RSI_DIV（RSI 背离）")
    else:
        print_warning("❌ RSI_DIV（RSI 背离）未命中")
    
    # OBV_DIV
    if obv_divergence(candles, bias):
        hits.append("OBV_DIV")
        print_warning("✅ OBV_DIV（OBV 背离）")
    else:
        print_warning("❌ OBV_DIV（OBV 背离）未命中")
    
    # FVG_PROXIMITY
    if fvg_proximity(candles, bias):
        hits.append("FVG_PROXIMITY")
        print_success("✅ FVG_PROXIMITY（FVG 接近）")
    else:
        print_warning("❌ FVG_PROXIMITY（FVG 接近）未命中")
    
    print_info(f"\n命中确认项数量: {len(hits)}/{4}")
    print_info(f"需要的最小确认项: {settings.min_confirmations}")
    print_info(f"命中的确认项: {hits if hits else '无'}")
    
    if len(hits) < settings.min_confirmations:
        print_error(f"确认项不足！需要至少 {settings.min_confirmations} 个，但只命中 {len(hits)} 个")
        return False, hits
    
    print_success(f"确认项足够（{len(hits)} >= {settings.min_confirmations}）")
    return True, hits

def check_strategy_service():
    """检查策略服务状态"""
    print_section("5. 策略服务状态检查")
    
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        print_success("Redis 连接正常")
    except Exception as e:
        print_error(f"Redis 连接失败: {e}")
        return False
    
    # 检查 bar_close 事件
    try:
        msgs = r.xrevrange("stream:bar_close", "+", "-", count=5)
        if msgs:
            print_success(f"最近有 {len(msgs)} 个 bar_close 事件")
            latest = msgs[0]
            print_info(f"最新 bar_close 消息 ID: {latest[0]}")
        else:
            print_warning("没有 bar_close 事件！")
            print_warning("可能原因：")
            print_warning("  1. marketdata 服务未运行")
            print_warning("  2. 没有订阅的交易对")
            print_warning("  3. 市场数据未正常接收")
    except Exception as e:
        print_warning(f"检查 bar_close 事件失败: {e}")
    
    # 检查信号事件
    try:
        msgs = r.xrevrange("stream:signal", "+", "-", count=5)
        if msgs:
            print_warning(f"最近有 {len(msgs)} 个信号事件（说明之前有信号生成）")
        else:
            print_info("没有信号事件（这是正常的，如果当前没有符合条件的信号）")
    except Exception as e:
        print_warning(f"检查信号事件失败: {e}")
    
    return True

def check_database_signals(symbol: str, timeframe: str):
    """检查数据库中的信号"""
    print_section("6. 数据库信号检查")
    
    try:
        with get_conn(settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT signal_id, symbol, timeframe, bias, hit_count, hits, vegas_state, created_at
                    FROM signals
                    WHERE symbol = %s AND timeframe = %s
                    ORDER BY created_at DESC
                    LIMIT 10
                """, (symbol, timeframe))
                
                rows = cur.fetchall()
                
                if rows:
                    print_success(f"找到 {len(rows)} 个历史信号")
                    print_info("\n最近的信号：")
                    for i, row in enumerate(rows[:5], 1):
                        print(f"  {i}. {row[3]} | hits={row[4]} | {row[6]} | {row[7]}")
                else:
                    print_warning(f"数据库中没有 {symbol} {timeframe} 的信号记录")
    except Exception as e:
        print_error(f"查询数据库失败: {e}")

def check_configuration():
    """检查配置"""
    print_section("7. 配置检查")
    
    print_info(f"MIN_CONFIRMATIONS: {settings.min_confirmations}")
    print_info(f"AUTO_TIMEFRAMES: {settings.auto_timeframes}")
    print_info(f"MONITOR_TIMEFRAMES: {settings.monitor_timeframes}")
    
    # 检查时间框架配置
    auto_tfs = [x.strip() for x in settings.auto_timeframes.split(",") if x.strip()]
    monitor_tfs = [x.strip() for x in settings.monitor_timeframes.split(",") if x.strip()]
    
    print_info(f"\n自动下单时间框架: {auto_tfs}")
    print_info(f"监控时间框架: {monitor_tfs}")
    print_info("注意：只有 AUTO_TIMEFRAMES 中的时间框架会生成 trade_plan")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="信号生成诊断工具")
    parser.add_argument("--symbol", default="BTCUSDT", help="交易对（默认: BTCUSDT）")
    parser.add_argument("--timeframe", default="1h", help="时间框架（默认: 1h）")
    
    args = parser.parse_args()
    
    print("\n" + "=" * 80)
    print("  信号生成诊断工具".center(80))
    print("=" * 80)
    
    symbol = args.symbol.upper()
    timeframe = args.timeframe
    
    # 1. 检查市场数据
    has_data, bars = check_market_data(symbol, timeframe)
    if not has_data:
        print("\n❌ 诊断结果：市场数据不足，无法生成信号")
        return
    
    # 2. 检查三段背离
    has_divergence, setup = check_divergence(bars)
    if not has_divergence:
        print("\n❌ 诊断结果：未检测到三段背离，无法生成信号")
        check_database_signals(symbol, timeframe)
        check_configuration()
        return
    
    bias = setup.direction
    
    # 3. 检查 Vegas
    has_vegas = check_vegas(bars, bias)
    if not has_vegas:
        print("\n❌ 诊断结果：Vegas 状态不匹配，无法生成信号")
        check_database_signals(symbol, timeframe)
        check_configuration()
        return
    
    # 4. 检查确认项
    has_confirmations, hits = check_confirmations(bars, bias)
    if not has_confirmations:
        print("\n❌ 诊断结果：确认项不足，无法生成信号")
        print_info(f"需要至少 {settings.min_confirmations} 个确认项，但只命中 {len(hits)} 个")
        check_database_signals(symbol, timeframe)
        check_configuration()
        return
    
    # 5. 检查服务状态
    check_strategy_service()
    
    # 6. 检查数据库
    check_database_signals(symbol, timeframe)
    
    # 7. 检查配置
    check_configuration()
    
    print("\n" + "=" * 80)
    print("  诊断总结".center(80))
    print("=" * 80)
    print_success("所有条件都满足，应该可以生成信号！")
    print_info("如果仍然没有信号，可能的原因：")
    print_info("  1. 策略服务未正常运行")
    print_info("  2. bar_close 事件未正常接收")
    print_info("  3. 信号已生成但被其他条件过滤")
    print_info("\n建议：")
    print_info("  1. 检查策略服务日志: docker compose logs strategy --tail 100")
    print_info("  2. 检查市场数据服务: docker compose logs marketdata --tail 100")
    print_info("  3. 检查 Redis Streams 中的 bar_close 事件")

if __name__ == "__main__":
    main()
