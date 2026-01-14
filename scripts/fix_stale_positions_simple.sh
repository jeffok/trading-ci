#!/bin/bash
# -*- coding: utf-8 -*-
# 修复数据库中的无效持仓 - 简化版本（使用 SQL）

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# 从 .env 文件或环境变量获取数据库连接信息
DB_URL=""
if [ -f ".env" ]; then
    # 从 .env 文件中提取 DATABASE_URL（处理可能的引号）
    DB_URL=$(grep "^DATABASE_URL=" .env | cut -d'=' -f2- | sed "s/^['\"]//;s/['\"]$//" | head -1)
fi

# 如果 .env 中没有，尝试环境变量
if [ -z "$DB_URL" ]; then
    DB_URL="${DATABASE_URL:-}"
fi

# 如果还是没有，尝试从单独的环境变量构建
if [ -z "$DB_URL" ]; then
    DB_HOST="${DB_HOST:-localhost}"
    DB_PORT="${DB_PORT:-5432}"
    DB_NAME="${DB_NAME:-trading-ci}"
    DB_USER="${DB_USER:-postgres}"
    DB_URL="postgresql://${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
fi

# 解析参数
DRY_RUN=false
FORCE=false
SYMBOL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --symbol)
            SYMBOL="$2"
            shift 2
            ;;
        --help|-h)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --dry-run      仅显示，不实际修改"
            echo "  --force        强制清理所有 OPEN 持仓（谨慎使用）"
            echo "  --symbol SYM   只清理指定交易对的持仓"
            echo "  --help, -h     显示帮助信息"
            echo ""
            echo "环境变量:"
            echo "  DATABASE_URL    数据库连接 URL（优先使用）"
            echo "  或单独设置:"
            echo "  DB_HOST        数据库主机（默认: localhost）"
            echo "  DB_PORT        数据库端口（默认: 5432）"
            echo "  DB_NAME        数据库名称（默认: trading-ci）"
            echo "  DB_USER        数据库用户（默认: postgres）"
            exit 0
            ;;
        *)
            print_error "未知参数: $1"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "  修复数据库中的无效持仓"
echo "=========================================="
echo ""

# 检查 psql 是否可用
if ! command -v psql > /dev/null 2>&1; then
    print_error "未找到 psql 命令"
    echo ""
    echo "💡 提示："
    echo "   1. 安装 PostgreSQL 客户端"
    echo "   2. 或在 Docker 容器中运行："
    echo "      docker compose exec execution bash scripts/fix_stale_positions_simple.sh --dry-run"
    exit 1
fi

print_info "数据库连接: ${DB_URL%%@*}@***"
echo ""

# 查询 OPEN 持仓
print_info "查询数据库中的 OPEN 持仓..."
OPEN_COUNT=$(psql "${DB_URL}" -t -c "SELECT COUNT(*) FROM positions WHERE status='OPEN';" 2>/dev/null | tr -d ' ' || echo "0")

if [ "$OPEN_COUNT" = "0" ] || [ -z "$OPEN_COUNT" ]; then
    print_success "数据库中没有 OPEN 状态的持仓"
    exit 0
fi

print_warning "找到 $OPEN_COUNT 个 OPEN 持仓"
echo ""

# 显示持仓列表
print_info "持仓列表:"
psql "${DB_URL}" -c "
SELECT 
    position_id,
    symbol,
    timeframe,
    side,
    qty_total,
    entry_price,
    idempotency_key,
    created_at
FROM positions
WHERE status = 'OPEN'
ORDER BY created_at DESC;
" 2>/dev/null || {
    print_error "查询失败，请检查数据库连接"
    exit 1
}

echo ""

# 根据参数决定操作
if [ "$DRY_RUN" = true ]; then
    print_info "DRY RUN 模式：不会实际修改数据库"
    echo ""
    print_info "要实际清理，请使用："
    if [ -n "$SYMBOL" ]; then
        echo "  $0 --symbol $SYMBOL"
    else
        echo "  $0 --force"
    fi
    exit 0
fi

if [ "$FORCE" = false ] && [ -z "$SYMBOL" ]; then
    print_warning "需要指定 --force 或 --symbol 参数才能清理"
    echo ""
    print_info "使用示例："
    echo "  $0 --dry-run              # 查看持仓"
    echo "  $0 --force                # 清理所有 OPEN 持仓"
    echo "  $0 --symbol BTCUSDT       # 只清理 BTCUSDT 的持仓"
    exit 0
fi

# 确认操作
if [ "$FORCE" = true ]; then
    print_warning "⚠️  将清理所有 OPEN 持仓"
    read -p "确认继续? (yes/no): " confirm
    if [ "$confirm" != "yes" ] && [ "$confirm" != "y" ]; then
        print_info "取消操作"
        exit 0
    fi
    
    print_info "开始清理所有 OPEN 持仓..."
    psql "${DB_URL}" -c "
    UPDATE positions
    SET 
        status = 'CLOSED',
        updated_at = now(),
        closed_at_ms = extract(epoch from now())::bigint * 1000,
        exit_reason = 'MANUAL_CLEANUP'
    WHERE status = 'OPEN';
    " 2>/dev/null && {
        print_success "完成！已清理所有 OPEN 持仓"
    } || {
        print_error "清理失败"
        exit 1
    }
    
elif [ -n "$SYMBOL" ]; then
    print_warning "⚠️  将清理 $SYMBOL 的所有 OPEN 持仓"
    read -p "确认继续? (yes/no): " confirm
    if [ "$confirm" != "yes" ] && [ "$confirm" != "y" ]; then
        print_info "取消操作"
        exit 0
    fi
    
    print_info "开始清理 $SYMBOL 的 OPEN 持仓..."
    psql "${DB_URL}" -c "
    UPDATE positions
    SET 
        status = 'CLOSED',
        updated_at = now(),
        closed_at_ms = extract(epoch from now())::bigint * 1000,
        exit_reason = 'MANUAL_CLEANUP'
    WHERE status = 'OPEN' AND symbol = '$SYMBOL';
    " 2>/dev/null && {
        print_success "完成！已清理 $SYMBOL 的 OPEN 持仓"
    } || {
        print_error "清理失败"
        exit 1
    }
fi

# 验证结果
echo ""
print_info "验证清理结果..."
REMAINING=$(psql "${DB_URL}" -t -c "SELECT COUNT(*) FROM positions WHERE status='OPEN';" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$REMAINING" = "0" ]; then
    print_success "所有 OPEN 持仓已清理"
else
    print_warning "仍有 $REMAINING 个 OPEN 持仓"
fi
