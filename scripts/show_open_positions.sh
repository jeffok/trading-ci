#!/bin/bash
# -*- coding: utf-8 -*-
# 显示所有 OPEN 持仓的详细信息

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

# 从环境变量或 .env 文件读取 DATABASE_URL
DB_URL=""
if [ -n "${DATABASE_URL:-}" ]; then
    DB_URL="$DATABASE_URL"
elif [ -f ".env" ]; then
    DB_URL=$(grep "^DATABASE_URL=" .env | cut -d'=' -f2- | sed "s/^['\"]//;s/['\"]$//" | head -1)
fi

if [ -z "$DB_URL" ]; then
    echo -e "${RED}[ERROR]${NC} 无法获取数据库连接信息"
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

# 执行 SQL
run_sql() {
    local sql="$1"
    if [ "$USE_DOCKER" = true ]; then
        docker compose exec -T execution bash -c "psql \"\$DATABASE_URL\" -c \"$sql\"" 2>&1
    else
        psql "$DB_URL" -c "$sql" 2>&1
    fi
}

echo "=========================================="
echo "  查看所有 OPEN 持仓"
echo "=========================================="
echo ""

print_info "查询所有 OPEN 持仓..."
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
"

echo ""
print_info "持仓数量统计："
run_sql "
SELECT 
    COUNT(*) as total_open,
    COUNT(CASE WHEN position_id LIKE 'paper-%' OR idempotency_key LIKE 'paper-%' THEN 1 END) as paper_count,
    COUNT(CASE WHEN idempotency_key LIKE 'idem-%' THEN 1 END) as test_count
FROM positions 
WHERE status = 'OPEN';
"
