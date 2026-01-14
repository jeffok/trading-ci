#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库完整性检查脚本

检查数据库表、结构、索引、迁移版本等完整性。

使用方法：
  在 Docker 容器中运行：
    docker compose exec execution python -m scripts.check_db_integrity
  
  或本地运行（需要安装依赖）：
    python -m scripts.check_db_integrity
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from libs.common.config import settings
    from libs.db.pg import get_conn
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    print("\n💡 提示：在 Docker 容器中运行：")
    print("   docker compose exec execution python -m scripts.check_db_integrity")
    sys.exit(1)


def check_table_exists(conn, table_name: str) -> bool:
    """检查表是否存在"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
            (table_name,),
        )
        return cur.fetchone()[0]


def check_column_exists(conn, table_name: str, column_name: str) -> bool:
    """检查列是否存在"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = %s AND column_name = %s)",
            (table_name, column_name),
        )
        return cur.fetchone()[0]


def check_index_exists(conn, index_name: str) -> bool:
    """检查索引是否存在"""
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname = %s)", (index_name,))
        return cur.fetchone()[0]


def get_migration_count(conn) -> tuple[int, list]:
    """获取迁移数量和列表"""
    if not check_table_exists(conn, "app_migrations"):
        return 0, []
    
    with conn.cursor() as cur:
        cur.execute("SELECT filename, applied_at FROM app_migrations ORDER BY applied_at DESC")
        rows = cur.fetchall()
        return len(rows), rows


def get_table_count(conn, table_name: str) -> int:
    """获取表的记录数"""
    if not check_table_exists(conn, table_name):
        return -1
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            return cur.fetchone()[0]
    except Exception:
        return -2


def main():
    print("=" * 60)
    print("  数据库完整性检查")
    print("=" * 60)
    print()
    
    # 检查数据库连接
    print("[1] 检查数据库连接...")
    try:
        with get_conn(settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            print("   ✅ 数据库连接正常")
    except Exception as e:
        print(f"   ❌ 数据库连接失败: {e}")
        sys.exit(1)
    
    print()
    
    # 检查必要的表
    print("[2] 检查必要的表...")
    REQUIRED_TABLES = [
        "bars",
        "signals",
        "trade_plans",
        "orders",
        "positions",
        "execution_reports",
        "risk_events",
        "risk_state",
        "setups",  # 注意：实际表名是 setups，不是 three_segment_setups
        "triggers",  # 注意：实际表名是 triggers，不是 entry_triggers
        "pivots",  # 注意：实际表名是 pivots，不是 pivot_points
        "indicator_snapshots",
        "notifications",
        "execution_traces",
        "account_snapshots",
        "cooldowns",
        "ws_events",
        "backtest_runs",
        "backtest_trades",
        "app_migrations",
    ]
    
    missing_tables = []
    with get_conn(settings.database_url) as conn:
        for table in REQUIRED_TABLES:
            if check_table_exists(conn, table):
                print(f"   ✅ 表 {table} 存在")
            else:
                print(f"   ❌ 表 {table} 不存在")
                missing_tables.append(table)
    
    if missing_tables:
        print()
        print(f"   ⚠️  缺少 {len(missing_tables)} 个表: {', '.join(missing_tables)}")
        print("   建议运行数据库迁移: python -m scripts.init_db")
    else:
        print()
        print("   ✅ 所有必要的表都存在")
    
    print()
    
    # 检查关键表的结构
    print("[3] 检查关键表的结构...")
    KEY_TABLES = {
        "orders": ["order_id", "idempotency_key", "symbol", "side", "order_type", "qty", "status", "bybit_order_id"],
        "positions": ["position_id", "idempotency_key", "symbol", "side", "qty_total", "status"],
        "trade_plans": ["plan_id", "idempotency_key", "symbol", "side", "entry_price", "primary_sl_price"],
        "execution_reports": ["report_id", "plan_id", "symbol", "type", "status"],
    }
    
    with get_conn(settings.database_url) as conn:
        for table, columns in KEY_TABLES.items():
            if not check_table_exists(conn, table):
                print(f"   ⚠️  表 {table} 不存在，跳过结构检查")
                continue
            
            print(f"   检查表 {table}...")
            missing_cols = []
            for col in columns:
                if check_column_exists(conn, table, col):
                    print(f"     ✅ 列 {col} 存在")
                else:
                    print(f"     ❌ 列 {col} 不存在")
                    missing_cols.append(col)
            
            if missing_cols:
                print(f"     ⚠️  表 {table} 缺少列: {', '.join(missing_cols)}")
    
    print()
    
    # 检查迁移版本
    print("[4] 检查数据库迁移版本...")
    with get_conn(settings.database_url) as conn:
        migration_count, migrations = get_migration_count(conn)
        
        if migration_count == 0:
            print("   ⚠️  迁移表不存在或为空，可能未运行迁移")
            print("   建议运行: python -m scripts.init_db")
        else:
            print(f"   ✅ 已应用 {migration_count} 个迁移")
            print()
            print("   最近的迁移：")
            for filename, applied_at in migrations[:10]:
                print(f"     - {filename} ({applied_at})")
            
            # 检查迁移文件数量
            migrations_dir = project_root / "migrations" / "postgres"
            migration_files = sorted(migrations_dir.glob("V*.sql"))
            if len(migration_files) > migration_count:
                print()
                print(f"   ⚠️  迁移文件数量 ({len(migration_files)}) 大于已应用数量 ({migration_count})")
                print("   建议运行: python -m scripts.init_db")
    
    print()
    
    # 检查数据统计
    print("[5] 检查数据统计...")
    STAT_TABLES = [
        "bars",
        "signals",
        "trade_plans",
        "orders",
        "positions",
        "execution_reports",
        "risk_events",
    ]
    
    with get_conn(settings.database_url) as conn:
        print("   表记录数：")
        for table in STAT_TABLES:
            count = get_table_count(conn, table)
            if count == -1:
                print(f"     {table}: 表不存在")
            elif count == -2:
                print(f"     {table}: 查询失败")
            else:
                print(f"     {table}: {count} 条记录")
    
    print()
    
    # 检查 OPEN 持仓
    print("[6] 检查 OPEN 持仓...")
    with get_conn(settings.database_url) as conn:
        if check_table_exists(conn, "positions"):
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'")
                open_count = cur.fetchone()[0]
                
                if open_count == 0:
                    print("   ✅ 没有 OPEN 持仓")
                else:
                    print(f"   ⚠️  有 {open_count} 个 OPEN 持仓")
                    cur.execute(
                        "SELECT position_id, symbol, side, qty_total, created_at FROM positions WHERE status='OPEN' ORDER BY created_at DESC LIMIT 5"
                    )
                    print("   持仓列表：")
                    for row in cur.fetchall():
                        print(f"     - {row[1]} {row[2]} qty={row[3]} (id={row[0][:20]}...)")
        else:
            print("   ⚠️  positions 表不存在")
    
    print()
    
    # 总结
    print("=" * 60)
    print("  检查总结")
    print("=" * 60)
    print()
    
    if missing_tables:
        print("❌ 数据库不完整：缺少以下表")
        for table in missing_tables:
            print(f"   - {table}")
        print()
        print("修复建议：")
        print("   运行数据库迁移：")
        print("     python -m scripts.init_db")
        print("   或在 Docker 容器中：")
        print("     docker compose exec execution python -m scripts.init_db")
        sys.exit(1)
    else:
        print("✅ 数据库完整性检查通过")
        print()
        print("所有必要的表都存在，数据库结构完整。")
        print()
        print("如果仍有问题，请检查：")
        print("   1. 执行服务日志：docker compose logs execution | tail -100")
        print("   2. 消费者状态：redis-cli XINFO GROUPS stream:trade_plan")
        print("   3. 执行轨迹：查询 execution_traces 表")


if __name__ == "__main__":
    main()
