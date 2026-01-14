#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 强制关闭指定持仓或所有 OPEN 持仓（Python 版本，适用于容器内运行）

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from libs.db.pg import get_conn
from libs.common.config import settings

def show_open_positions(db_url: str):
    """显示所有 OPEN 持仓"""
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
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
            
            return positions

def close_position(db_url: str, position_id: str) -> bool:
    """关闭指定持仓"""
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
                print(f"❌ 未找到匹配的 OPEN 持仓: {position_id}")
                return False
            
            print(f"✅ 找到持仓: {dict(zip(['position_id', 'symbol', 'side', 'qty_total', 'status'], row))}")
            
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
                print(f"✅ 已关闭持仓: {result[0]}")
                return True
            else:
                print("❌ 关闭失败")
                return False

def close_all_positions(db_url: str) -> int:
    """关闭所有 OPEN 持仓"""
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
            
            print(f"⚠️  找到 {len(positions)} 个 OPEN 持仓，将全部关闭")
            print()
            
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
            
            print(f"✅ 已关闭 {len(closed)} 个持仓")
            for pos in closed:
                print(f"   - {pos[0]}")
            
            return len(closed)

def main():
    parser = argparse.ArgumentParser(description="强制关闭持仓")
    parser.add_argument("position_id", nargs="?", help="持仓 ID（可选，不提供则显示所有 OPEN 持仓）")
    parser.add_argument("--all", action="store_true", help="关闭所有 OPEN 持仓")
    parser.add_argument("--yes", action="store_true", help="跳过确认提示")
    
    args = parser.parse_args()
    
    db_url = settings.database_url
    
    print("=" * 50)
    print("  强制关闭持仓")
    print("=" * 50)
    print()
    
    if args.all:
        # 显示将要关闭的持仓
        positions = show_open_positions(db_url)
        
        if not positions:
            return
        
        print()
        if not args.yes:
            confirm = input("确认关闭所有 OPEN 持仓? (yes/no): ")
            if confirm.lower() not in ['yes', 'y']:
                print("取消操作")
                return
        
        print()
        print("[INFO] 开始关闭...")
        count = close_all_positions(db_url)
        
    elif args.position_id:
        # 关闭指定持仓
        if not args.yes:
            positions = show_open_positions(db_url)
            print()
            confirm = input(f"确认关闭持仓 {args.position_id}? (yes/no): ")
            if confirm.lower() not in ['yes', 'y']:
                print("取消操作")
                return
        
        print()
        print("[INFO] 开始关闭...")
        close_position(db_url, args.position_id)
        
    else:
        # 只显示持仓
        show_open_positions(db_url)
        print()
        print("用法:")
        print("  python -m scripts.force_close_position <position_id>  # 关闭指定持仓")
        print("  python -m scripts.force_close_position --all          # 关闭所有 OPEN 持仓")
        return
    
    # 验证结果
    print()
    print("[INFO] 验证结果...")
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN';")
            remaining = cur.fetchone()[0]
            
            if remaining == 0:
                print("✅ 所有 OPEN 持仓已清理")
            else:
                print(f"⚠️  仍有 {remaining} 个 OPEN 持仓")

if __name__ == "__main__":
    main()
