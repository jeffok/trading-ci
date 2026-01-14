#!/bin/bash
# -*- coding: utf-8 -*-
# 数据库完整性检查脚本

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

# 优先使用环境变量（容器内运行时）
if [ -n "${DATABASE_URL:-}" ]; then
    DB_URL="$DATABASE_URL"
elif [ -f ".env" ]; then
    # 从 .env 文件读取
    DB_URL=$(grep "^DATABASE_URL=" .env | cut -d'=' -f2- | sed "s/^['\"]//;s/['\"]$//" | head -1)
fi

if [ -z "$DB_URL" ]; then
    print_error "无法获取数据库连接信息"
    echo "请设置 DATABASE_URL 环境变量或在 .env 文件中配置"
    echo ""
    echo "在容器内运行时，DATABASE_URL 应该已经设置"
    echo "检查方法："
    echo "  docker compose exec execution printenv DATABASE_URL"
    exit 1
fi

# 检测是否在容器内运行
USE_DOCKER=false
if [ -f "/.dockerenv" ] || [ -n "${DOCKER_CONTAINER:-}" ]; then
    # 在容器内，直接使用 psql
    USE_DOCKER=false
elif command -v psql > /dev/null 2>&1; then
    # 本地有 psql，测试是否支持 SCRAM
    if ! psql "$DB_URL" -c "SELECT 1;" > /dev/null 2>&1; then
        ERROR_MSG=$(psql "$DB_URL" -c "SELECT 1;" 2>&1 || true)
        if echo "$ERROR_MSG" | grep -q "SCRAM authentication requires libpq version 10"; then
            USE_DOCKER=true
        fi
    fi
else
    # 本地没有 psql，使用 Docker
    USE_DOCKER=true
fi

echo "=========================================="
echo "  数据库完整性检查"
echo "=========================================="
echo ""
print_info "数据库连接: ${DB_URL%%@*}@***"
echo ""

# 执行 SQL 查询的函数
run_sql() {
    local sql="$1"
    if [ "$USE_DOCKER" = true ]; then
        # 从容器环境变量读取 DATABASE_URL
        docker compose exec -T execution bash -c "psql \"\$DATABASE_URL\" -c \"$sql\"" 2>&1
    else
        # 直接使用 DB_URL（容器内或本地）
        psql "$DB_URL" -c "$sql" 2>&1
    fi
}

# 1. 检查数据库连接
print_info "1. 检查数据库连接..."
if run_sql "SELECT 1;" > /dev/null 2>&1; then
    print_success "数据库连接正常"
else
    print_error "数据库连接失败"
    exit 1
fi

echo ""

# 2. 检查必要的表是否存在
print_info "2. 检查必要的表..."
REQUIRED_TABLES=(
    "bars"
    "signals"
    "trade_plans"
    "orders"
    "positions"
    "execution_reports"
    "risk_events"
    "risk_state"
    "three_segment_setups"
    "entry_triggers"
    "pivot_points"
    "indicator_snapshots"
    "notifications"
    "execution_traces"
    "account_snapshots"
    "cooldowns"
    "ws_events"
    "backtest_runs"
    "backtest_trades"
)

MISSING_TABLES=()
for table in "${REQUIRED_TABLES[@]}"; do
    if run_sql "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '$table');" | grep -q "t"; then
        print_success "表 $table 存在"
    else
        print_error "表 $table 不存在"
        MISSING_TABLES+=("$table")
    fi
done

if [ ${#MISSING_TABLES[@]} -gt 0 ]; then
    echo ""
    print_error "缺少以下表: ${MISSING_TABLES[*]}"
    echo "   建议运行数据库迁移: python -m scripts.init_db"
else
    echo ""
    print_success "所有必要的表都存在"
fi

echo ""

# 3. 检查关键表的结构
print_info "3. 检查关键表的结构..."

check_table_structure() {
    local table=$1
    local required_columns=$2
    
    echo "   检查表 $table..."
    for col in $required_columns; do
        if run_sql "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = '$table' AND column_name = '$col');" | grep -q "t"; then
            echo "     ✅ 列 $col 存在"
        else
            echo "     ❌ 列 $col 不存在"
        fi
    done
}

echo "   检查 orders 表..."
check_table_structure "orders" "order_id idempotency_key symbol side order_type qty status bybit_order_id"

echo "   检查 positions 表..."
check_table_structure "positions" "position_id idempotency_key symbol side qty_total status"

echo "   检查 trade_plans 表..."
check_table_structure "trade_plans" "plan_id idempotency_key symbol side entry_price primary_sl_price"

echo "   检查 execution_reports 表..."
check_table_structure "execution_reports" "report_id plan_id symbol type status"

echo ""

# 4. 检查索引
print_info "4. 检查关键索引..."

KEY_INDEXES=(
    "orders_idempotency_key_idx"
    "positions_idempotency_key_idx"
    "positions_status_symbol_side_idx"
    "trade_plans_idempotency_key_idx"
    "execution_reports_plan_id_idx"
)

MISSING_INDEXES=()
for idx in "${KEY_INDEXES[@]}"; do
    if run_sql "SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname = '$idx');" | grep -q "t"; then
        print_success "索引 $idx 存在"
    else
        print_warning "索引 $idx 不存在（可能影响性能）"
        MISSING_INDEXES+=("$idx")
    fi
done

echo ""

# 5. 检查迁移版本
print_info "5. 检查数据库迁移版本..."
MIGRATION_TABLE_EXISTS=$(run_sql "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'schema_migrations');" | grep -o "t\|f" || echo "f")

if [ "$MIGRATION_TABLE_EXISTS" = "t" ]; then
    MIGRATION_COUNT=$(run_sql "SELECT COUNT(*) FROM schema_migrations;" | grep -oE "[0-9]+" | head -1)
    print_success "迁移表存在，已应用 $MIGRATION_COUNT 个迁移"
    
    echo ""
    echo "   已应用的迁移："
    run_sql "SELECT version, description, installed_on FROM schema_migrations ORDER BY installed_on DESC LIMIT 10;" | grep -v "^$" | tail -n +3 | head -10
    
    # 检查最新的迁移文件
    LATEST_MIGRATION=$(ls -1 migrations/postgres/V*.sql 2>/dev/null | sort -V | tail -1)
    if [ -n "$LATEST_MIGRATION" ]; then
        LATEST_VERSION=$(basename "$LATEST_MIGRATION" | cut -d'_' -f1)
        echo ""
        echo "   最新迁移文件: $LATEST_VERSION"
    fi
else
    print_warning "迁移表不存在，可能未运行迁移"
    echo "   建议运行: python -m scripts.init_db"
fi

echo ""

# 6. 检查数据完整性
print_info "6. 检查数据完整性..."

echo "   检查数据统计："
echo ""
run_sql "
SELECT 
    'bars' as table_name, COUNT(*) as count FROM bars
UNION ALL
SELECT 'signals', COUNT(*) FROM signals
UNION ALL
SELECT 'trade_plans', COUNT(*) FROM trade_plans
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'positions', COUNT(*) FROM positions
UNION ALL
SELECT 'execution_reports', COUNT(*) FROM execution_reports
UNION ALL
SELECT 'risk_events', COUNT(*) FROM risk_events
ORDER BY table_name;
" | grep -v "^$" | tail -n +3

echo ""

# 7. 检查外键约束
print_info "7. 检查外键约束..."
FK_COUNT=$(run_sql "SELECT COUNT(*) FROM information_schema.table_constraints WHERE constraint_type = 'FOREIGN KEY';" | grep -oE "[0-9]+" | head -1)
print_info "   找到 $FK_COUNT 个外键约束"

echo ""

# 8. 检查最近的数据
print_info "8. 检查最近的数据..."

echo "   最近的 trade_plans："
run_sql "SELECT plan_id, symbol, side, entry_price, created_at FROM trade_plans ORDER BY created_at DESC LIMIT 3;" | grep -v "^$" | tail -n +3 || echo "     (无数据)"

echo ""
echo "   最近的 orders："
run_sql "SELECT order_id, symbol, side, status, bybit_order_id, created_at FROM orders ORDER BY created_at DESC LIMIT 3;" | grep -v "^$" | tail -n +3 || echo "     (无数据)"

echo ""
echo "   最近的 execution_reports："
run_sql "SELECT report_id, symbol, type, status, created_at FROM execution_reports ORDER BY created_at DESC LIMIT 3;" | grep -v "^$" | tail -n +3 || echo "     (无数据)"

echo ""

# 9. 检查 OPEN 持仓
print_info "9. 检查 OPEN 持仓..."
OPEN_COUNT=$(run_sql "SELECT COUNT(*) FROM positions WHERE status='OPEN';" | grep -oE "[0-9]+" | head -1)
if [ "$OPEN_COUNT" = "0" ]; then
    print_success "没有 OPEN 持仓"
else
    print_warning "有 $OPEN_COUNT 个 OPEN 持仓"
    echo "   持仓列表："
    run_sql "SELECT position_id, symbol, side, qty_total, created_at FROM positions WHERE status='OPEN' ORDER BY created_at DESC;" | grep -v "^$" | tail -n +3
fi

echo ""

# 10. 总结
print_info "10. 检查总结"
echo ""

if [ ${#MISSING_TABLES[@]} -gt 0 ]; then
    print_error "❌ 数据库不完整：缺少 ${#MISSING_TABLES[@]} 个表"
    echo ""
    echo "修复建议："
    echo "   1. 运行数据库迁移："
    echo "      python -m scripts.init_db"
    echo ""
    echo "   2. 或在 Docker 容器中运行："
    echo "      docker compose exec execution python -m scripts.init_db"
    echo ""
    exit 1
else
    print_success "✅ 数据库完整性检查通过"
    echo ""
    echo "所有必要的表都存在，数据库结构完整。"
    echo ""
    echo "如果仍有问题，请检查："
    echo "   1. 执行服务日志：docker compose logs execution | tail -100"
    echo "   2. 消费者状态：redis-cli XINFO GROUPS stream:trade_plan"
    echo "   3. 执行轨迹：查询 execution_traces 表"
fi
