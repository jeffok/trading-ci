#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 显示所有 OPEN 持仓的详细信息（Python 版本，适用于容器内运行）

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from libs.db.pg import get_conn
from libs.common.config import settings

def main():
    print("=" * 50)
    print("  查看所有 OPEN 持仓")
    print("=" * 50)
    print()
    
    db_url = settings.database_url
    
    print(f"[INFO] 查询所有 OPEN 持仓...")
    print()
    
    # 查询所有 OPEN 持仓
    with get_conn(db_url) as conn:
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
            
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            
            if not rows:
                print("没有找到 OPEN 持仓")
            else:
                # 打印表头
                header = " | ".join(f"{col:20}" for col in cols)
                print(header)
                print("-" * len(header))
                
                # 打印数据
                for row in rows:
                    row_str = " | ".join(f"{str(v) if v is not None else 'NULL':20}" for v in row)
                    print(row_str)
    
    print()
    print(f"[INFO] 持仓数量统计：")
    print()
    
    # 统计信息
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    COUNT(*) as total_open,
                    COUNT(CASE WHEN position_id LIKE 'paper-%' OR idempotency_key LIKE 'paper-%' THEN 1 END) as paper_count,
                    COUNT(CASE WHEN idempotency_key LIKE 'idem-%' THEN 1 END) as test_count
                FROM positions 
                WHERE status = 'OPEN';
            """)
            
            cols = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            
            if row:
                stats = dict(zip(cols, row))
                print(f"  总 OPEN 持仓数: {stats['total_open']}")
                print(f"  PAPER 模式持仓: {stats['paper_count']}")
                print(f"  测试注入持仓: {stats['test_count']}")

if __name__ == "__main__":
    main()
