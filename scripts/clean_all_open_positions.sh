#!/bin/bash
# -*- coding: utf-8 -*-
# 清理所有 OPEN 持仓（用于清理无效持仓）

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 从环境变量或 .env 文件读取 DATABASE_URL
DB_URL=""
if [ -n "${DATABASE_URL:-}" ]; then
    DB_URL="$DATABASE_URL"
elif [ -f ".env" ]; then
    DB_URL=$(grep "^DATABASE_URL=" .env | cut -d'=' -f2- | sed "s/^['\"]//;s/['\"]$//" | head -1)
fi

if [ -z "$DB_URL" ]; then
    print_error "无法获取数据库连接信息"
    exit 1
fi

# 检测是否在容器内运行
USE_DOCKER=false
if [ -f "/.dockerenv" ] || [ -n "${DOCKER_CONTAINER:-}" ]; then
    USE_DOCKER=false
elif command -v psql > /dev/null 2>&1; then
    if ! psql "$DB_URL" -c "SELECT 1;" > /dev/null 2>&1; then
        ERROR_MSG=$(psql "$DB_URL" -c "SELECT 1;" 2>&1 || true)
        if echo "$ERROR_MSG" | grep -q "SCRAM authentication requires libpq version 10"; then
            USE_DOCKER=true
        fi
    fi
else
    USE_DOCKER=true
fi

echo "=========================================="
echo "  清理所有 OPEN 持仓"
echo "=========================================="
echo ""

# 执行 SQL
run_sql() {
    local sql="$1"
    if [ "$USE_DOCKER" = true ]; then
        docker compose exec -T execution bash -c "psql \"\$DATABASE_URL\" -c \"$sql\"" 2>&1
    else
        psql "$DB_URL" -c "$sql" 2>&1
    fi
}

# 查询所有 OPEN 持仓
print_info "查询所有 OPEN 持仓..."
OPEN_POSITIONS=$(run_sql "
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
" | grep -v "^$" | tail -n +3)

if [ -z "$OPEN_POSITIONS" ] || echo "$OPEN_POSITIONS" | grep -q "0 rows"; then
    print_success "没有 OPEN 持仓"
    exit 0
fi

echo ""
print_warning "找到以下 OPEN 持仓："
echo "$OPEN_POSITIONS"
echo ""

# 显示详细信息
print_info "持仓详细信息："
run_sql "
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
" | grep -v "^$" | tail -n +3

echo ""

# 确认清理
print_warning "⚠️  这将清理所有 OPEN 持仓"
read -p "确认继续? (yes/no): " confirm
if [ "$confirm" != "yes" ] && [ "$confirm" != "y" ]; then
    print_info "取消操作"
    exit 0
fi

# 清理持仓
print_info "开始清理..."
run_sql "
UPDATE positions 
SET 
    status = 'CLOSED',
    updated_at = now(),
    closed_at_ms = extract(epoch from now())::bigint * 1000,
    exit_reason = 'MANUAL_CLEANUP'
WHERE status = 'OPEN';
" > /dev/null 2>&1

if [ $? -eq 0 ]; then
    print_success "完成！已清理所有 OPEN 持仓"
    
    # 验证
    echo ""
    print_info "验证清理结果..."
    REMAINING=$(run_sql "SELECT COUNT(*) FROM positions WHERE status='OPEN';" | grep -oE "[0-9]+" | head -1)
    if [ "$REMAINING" = "0" ]; then
        print_success "所有 OPEN 持仓已清理"
    else
        print_warning "仍有 $REMAINING 个 OPEN 持仓"
    fi
else
    print_error "清理失败"
    exit 1
fi

echo ""
print_info "清理完成！现在可以重新进行实盘测试了。"
