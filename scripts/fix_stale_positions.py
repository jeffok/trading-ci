#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复数据库中的无效持仓

用途：
- 查询数据库中的 OPEN 持仓
- 与 Bybit 交易所实际持仓对比
- 清理无效的持仓记录（交易所中已不存在的持仓）
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from libs.common.config import settings
from libs.common.time import now_ms
from libs.db.pg import get_conn
from libs.bybit.trade_rest_v5 import BybitV5Client


def list_open_positions_db(database_url: str) -> List[Dict[str, Any]]:
    """查询数据库中的 OPEN 持仓"""
    sql = """
    SELECT position_id, idempotency_key, symbol, timeframe, side, qty_total, 
           entry_price, status, opened_at_ms, created_at
    FROM positions
    WHERE status = 'OPEN'
    ORDER BY created_at DESC
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                row = {}
                for i, c in enumerate(cols):
                    row[c] = r[i]
                rows.append(row)
    return rows


def check_bybit_position(client: BybitV5Client, symbol: str) -> Dict[str, Any]:
    """检查 Bybit 交易所的实际持仓"""
    try:
        pos = client.position_list_cached(category=settings.bybit_category, symbol=symbol)
        lst = pos.get("result", {}).get("list", []) or []
        if lst:
            size = float(lst[0].get("size", "0") or "0")
            side = lst[0].get("side", "")
            return {"exists": True, "size": size, "side": side, "data": lst[0]}
        return {"exists": False, "size": 0.0}
    except Exception as e:
        return {"exists": False, "error": str(e)}


def mark_position_closed(database_url: str, position_id: str, exit_reason: str = "MANUAL_CLEANUP") -> None:
    """标记持仓为已关闭"""
    sql = """
    UPDATE positions
    SET status = 'CLOSED',
        updated_at = now(),
        closed_at_ms = %s,
        exit_reason = %s
    WHERE position_id = %s
    """
    with get_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (now_ms(), exit_reason, position_id))
            conn.commit()


def main():
    ap = argparse.ArgumentParser(description="修复数据库中的无效持仓")
    ap.add_argument("--dry-run", action="store_true", help="仅显示，不实际修改")
    ap.add_argument("--force", action="store_true", help="强制清理所有 OPEN 持仓（谨慎使用）")
    ap.add_argument("--check-bybit", action="store_true", default=True, help="检查 Bybit 实际持仓（默认启用）")
    args = ap.parse_args()

    print("=" * 60)
    print("  修复数据库中的无效持仓")
    print("=" * 60)
    print()

    # 检查配置
    if args.check_bybit and str(settings.execution_mode).upper() != "LIVE":
        print(f"⚠️  当前执行模式: {settings.execution_mode}")
        print("   持仓同步只在 LIVE 模式下运行")
        print("   如果之前使用 PAPER/BACKTEST 模式测试，数据库中可能有残留持仓")
        print()

    # 查询数据库中的 OPEN 持仓
    print("📊 查询数据库中的 OPEN 持仓...")
    db_positions = list_open_positions_db(settings.database_url)
    
    if not db_positions:
        print("✅ 数据库中没有 OPEN 状态的持仓")
        return

    print(f"   找到 {len(db_positions)} 个 OPEN 持仓:")
    for p in db_positions:
        print(f"   - {p['symbol']} {p['side']} {p['timeframe']} "
              f"(idem: {p['idempotency_key'][:20]}...) "
              f"qty: {p['qty_total']}")
    print()

    # 检查 Bybit 实际持仓
    if args.check_bybit and str(settings.execution_mode).upper() == "LIVE":
        if not settings.bybit_api_key or not settings.bybit_api_secret:
            print("⚠️  未配置 Bybit API Key/Secret，跳过交易所检查")
            args.check_bybit = False
        else:
            print("🔍 检查 Bybit 交易所实际持仓...")
            client = BybitV5Client(
                base_url=settings.bybit_rest_base_url,
                api_key=settings.bybit_api_key,
                api_secret=settings.bybit_api_secret,
                recv_window_ms=settings.bybit_recv_window,
            )

            stale_positions = []
            for p in db_positions:
                symbol = p["symbol"]
                bybit_pos = check_bybit_position(client, symbol)
                
                if bybit_pos.get("error"):
                    print(f"   ⚠️  {symbol}: 查询失败 - {bybit_pos['error']}")
                    continue

                if not bybit_pos.get("exists") or bybit_pos.get("size", 0) == 0:
                    print(f"   ❌ {symbol}: 交易所中不存在或已关闭 (DB: OPEN)")
                    stale_positions.append(p)
                else:
                    print(f"   ✅ {symbol}: 交易所中存在 (size: {bybit_pos['size']})")
            
            print()

            if not stale_positions:
                print("✅ 所有数据库持仓都与交易所一致")
                return

            # 清理无效持仓
            print(f"🧹 发现 {len(stale_positions)} 个无效持仓需要清理:")
            for p in stale_positions:
                print(f"   - {p['symbol']} {p['side']} {p['timeframe']} "
                      f"(position_id: {p['position_id']})")

            if args.dry_run:
                print("\n🔍 DRY RUN 模式：不会实际修改数据库")
                return

            if not args.force:
                response = input("\n是否清理这些无效持仓? (yes/no): ")
                if response.lower() not in ["yes", "y"]:
                    print("取消操作")
                    return

            print("\n开始清理...")
            for p in stale_positions:
                mark_position_closed(
                    settings.database_url,
                    p["position_id"],
                    exit_reason="STALE_POSITION_CLEANUP"
                )
                print(f"   ✅ 已清理: {p['symbol']} {p['side']} {p['timeframe']}")

            print(f"\n✅ 完成！已清理 {len(stale_positions)} 个无效持仓")

    elif args.force:
        # 强制清理模式（不检查交易所）
        print("⚠️  强制清理模式：将清理所有 OPEN 持仓（不检查交易所）")
        
        if args.dry_run:
            print("🔍 DRY RUN 模式：不会实际修改数据库")
            return

        response = input("\n确认清理所有 OPEN 持仓? (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("取消操作")
            return

        print("\n开始清理...")
        for p in db_positions:
            mark_position_closed(
                settings.database_url,
                p["position_id"],
                exit_reason="FORCE_CLEANUP"
            )
            print(f"   ✅ 已清理: {p['symbol']} {p['side']} {p['timeframe']}")

        print(f"\n✅ 完成！已清理 {len(db_positions)} 个持仓")

    else:
        print("💡 提示:")
        print("   使用 --check-bybit 检查 Bybit 实际持仓（需要 LIVE 模式）")
        print("   使用 --force 强制清理所有 OPEN 持仓（谨慎使用）")
        print("   使用 --dry-run 查看将要执行的操作（不实际修改）")


if __name__ == "__main__":
    main()
