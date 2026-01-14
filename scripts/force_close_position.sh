#!/bin/bash
# -*- coding: utf-8 -*-
# 强制关闭指定持仓（通过 position_id 或 idempotency_key）

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

# 执行 SQL
run_sql() {
    local sql="$1"
    if [ "$USE_DOCKER" = true ]; then
        docker compose exec -T execution bash -c "psql \"\$DATABASE_URL\" -c \"$sql\"" 2>&1
    else
        psql "$DB_URL" -c "$sql" 2>&1
    fi
}

# 参数处理
POSITION_ID="${1:-}"
FORCE_ALL="${2:-}"

if [ -z "$POSITION_ID" ] && [ "$FORCE_ALL" != "all" ]; then
    echo "用法: $0 <position_id> 或 $0 all"
    echo ""
    echo "示例:"
    echo "  $0 paper-pos-2d1df043db..."
    echo "  $0 all  # 关闭所有 OPEN 持仓"
    echo ""
    echo "先查看所有 OPEN 持仓："
    ./scripts/show_open_positions.sh
    exit 1
fi

echo "=========================================="
echo "  强制关闭持仓"
echo "=========================================="
echo ""

if [ "$FORCE_ALL" = "all" ] || [ "$POSITION_ID" = "all" ]; then
    print_warning "⚠️  将关闭所有 OPEN 持仓"
    
    # 显示将要关闭的持仓
    print_info "将要关闭的持仓："
    run_sql "
    SELECT 
        position_id,
        idempotency_key,
        symbol,
        side,
        qty_total,
        status
    FROM positions 
    WHERE status = 'OPEN'
    ORDER BY created_at DESC;
    "
    
    echo ""
    read -p "确认关闭所有 OPEN 持仓? (yes/no): " confirm
    if [ "$confirm" != "yes" ] && [ "$confirm" != "y" ]; then
        print_info "取消操作"
        exit 0
    fi
    
    # 关闭所有
    print_info "关闭所有 OPEN 持仓..."
    RESULT=$(run_sql "
    UPDATE positions 
    SET 
        status = 'CLOSED',
        updated_at = now(),
        closed_at_ms = extract(epoch from now())::bigint * 1000,
        exit_reason = 'MANUAL_FORCE_CLOSE'
    WHERE status = 'OPEN'
    RETURNING position_id;
    " | grep -v "^$" | tail -n +3)
    
    if [ -n "$RESULT" ]; then
        print_success "已关闭以下持仓："
        echo "$RESULT"
    else
        print_warning "没有找到 OPEN 持仓"
    fi
else
    # 关闭指定持仓
    print_info "查找持仓: $POSITION_ID"
    
    # 先检查是否存在
    EXISTS=$(run_sql "
    SELECT position_id, symbol, side, qty_total, status 
    FROM positions 
    WHERE (position_id = '$POSITION_ID' OR idempotency_key = '$POSITION_ID' OR position_id LIKE '$POSITION_ID%')
    AND status = 'OPEN';
    " | grep -v "^$" | tail -n +3)
    
    if [ -z "$EXISTS" ] || echo "$EXISTS" | grep -q "0 rows"; then
        print_error "未找到匹配的 OPEN 持仓: $POSITION_ID"
        echo ""
        print_info "当前所有 OPEN 持仓："
        run_sql "SELECT position_id, idempotency_key, symbol, side, status FROM positions WHERE status = 'OPEN';"
        exit 1
    fi
    
    echo ""
    print_warning "找到持仓："
    echo "$EXISTS"
    echo ""
    read -p "确认关闭此持仓? (yes/no): " confirm
    if [ "$confirm" != "yes" ] && [ "$confirm" != "y" ]; then
        print_info "取消操作"
        exit 0
    fi
    
    # 关闭指定持仓
    print_info "关闭持仓..."
    RESULT=$(run_sql "
    UPDATE positions 
    SET 
        status = 'CLOSED',
        updated_at = now(),
        closed_at_ms = extract(epoch from now())::bigint * 1000,
        exit_reason = 'MANUAL_FORCE_CLOSE'
    WHERE (position_id = '$POSITION_ID' OR idempotency_key = '$POSITION_ID' OR position_id LIKE '$POSITION_ID%')
    AND status = 'OPEN'
    RETURNING position_id;
    " | grep -v "^$" | tail -n +3)
    
    if [ -n "$RESULT" ]; then
        print_success "已关闭持仓: $RESULT"
    else
        print_error "关闭失败"
        exit 1
    fi
fi

echo ""
print_info "验证结果..."
REMAINING=$(run_sql "SELECT COUNT(*) FROM positions WHERE status='OPEN';" | grep -oE "[0-9]+" | head -1)
if [ "$REMAINING" = "0" ]; then
    print_success "所有 OPEN 持仓已清理"
else
    print_warning "仍有 $REMAINING 个 OPEN 持仓"
fi
