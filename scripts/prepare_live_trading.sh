#!/bin/bash
# -*- coding: utf-8 -*-
# 实盘交易准备脚本

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

echo "=========================================="
echo "  实盘交易准备检查"
echo "=========================================="
echo ""

# 检查 .env 文件
if [ ! -f ".env" ]; then
    print_error ".env 文件不存在"
    echo "请先复制 .env.example 并配置："
    echo "  cp .env.example .env"
    exit 1
fi

print_success ".env 文件存在"
echo ""

# 检查关键配置
print_info "检查关键配置..."

# 读取 .env 文件
source .env 2>/dev/null || true

# 检查执行模式
if [ "${EXECUTION_MODE:-}" != "LIVE" ]; then
    print_error "EXECUTION_MODE 不是 LIVE"
    echo "   当前值: ${EXECUTION_MODE:-未设置}"
    echo "   请设置: EXECUTION_MODE=LIVE"
    exit 1
fi
print_success "EXECUTION_MODE=LIVE"

# 检查 Bybit API
if [ -z "${BYBIT_API_KEY:-}" ] || [ -z "${BYBIT_API_SECRET:-}" ]; then
    print_error "Bybit API Key/Secret 未配置"
    echo "   请设置: BYBIT_API_KEY 和 BYBIT_API_SECRET"
    exit 1
fi
print_success "Bybit API Key/Secret 已配置"

# 检查风险配置
if [ -z "${RISK_PCT:-}" ] || (( $(echo "${RISK_PCT:-0} > 0.01" | bc -l) )); then
    print_warning "RISK_PCT 可能过大（当前: ${RISK_PCT:-未设置}）"
    echo "   实盘建议: RISK_PCT=0.001 到 0.005"
fi

if [ "${ACCOUNT_KILL_SWITCH_ENABLED:-false}" != "true" ]; then
    print_warning "ACCOUNT_KILL_SWITCH_ENABLED 未启用"
    echo "   强烈建议启用: ACCOUNT_KILL_SWITCH_ENABLED=true"
fi

if [ "${RISK_CIRCUIT_ENABLED:-false}" != "true" ]; then
    print_warning "RISK_CIRCUIT_ENABLED 未启用"
    echo "   强烈建议启用: RISK_CIRCUIT_ENABLED=true"
fi

echo ""

# 检查数据库连接
print_info "检查数据库连接..."
if command -v psql > /dev/null 2>&1; then
    # 尝试从 .env 文件读取 DATABASE_URL
    DB_URL=""
    if [ -f ".env" ]; then
        # 从 .env 文件中提取 DATABASE_URL（处理可能的引号）
        DB_URL=$(grep "^DATABASE_URL=" .env | cut -d'=' -f2- | sed "s/^['\"]//;s/['\"]$//" | head -1)
    fi
    
    # 如果 .env 中没有，尝试环境变量
    if [ -z "$DB_URL" ]; then
        DB_URL="${DATABASE_URL:-}"
    fi
    
    # 如果还是没有，使用默认值
    if [ -z "$DB_URL" ]; then
        DB_URL="postgresql://postgres:postgres@localhost:5432/trading-ci"
        print_warning "使用默认数据库连接: $DB_URL"
    else
        print_info "使用 DATABASE_URL: ${DB_URL%%@*}@***"
    fi
    
    # 测试连接
    if psql "$DB_URL" -c "SELECT 1;" > /dev/null 2>&1; then
        print_success "数据库连接正常"
    else
        ERROR_MSG=$(psql "$DB_URL" -c "SELECT 1;" 2>&1 || true)
        if echo "$ERROR_MSG" | grep -q "SCRAM authentication requires libpq version 10"; then
            print_warning "本地 psql 版本过旧，不支持 SCRAM 认证"
            print_info "尝试在 Docker 容器中测试..."
            if docker compose exec -T execution psql "$DB_URL" -c "SELECT 1;" > /dev/null 2>&1; then
                print_success "Docker 容器内数据库连接正常（本地 psql 版本过旧不影响使用）"
            else
                print_error "Docker 容器内连接也失败"
                echo "   请检查 DATABASE_URL 配置"
            fi
        else
            print_error "数据库连接失败"
            echo "   连接字符串: ${DB_URL%%@*}@***"
            echo "   错误信息: $ERROR_MSG"
            echo "   请检查："
            echo "   1. DATABASE_URL 格式是否正确"
            echo "   2. 数据库服务是否运行"
            echo "   3. 用户名密码是否正确"
            echo "   4. 数据库是否存在"
        fi
        # 不退出，允许继续检查其他项
    fi
else
    print_warning "未安装 psql，跳过数据库检查"
    echo "   可以通过 Docker 容器检查："
    echo "   docker compose exec execution psql \$DATABASE_URL -c \"SELECT 1;\""
fi

# 检查 Redis 连接
print_info "检查 Redis 连接..."
if command -v redis-cli > /dev/null 2>&1; then
    if redis-cli ping > /dev/null 2>&1; then
        print_success "Redis 连接正常"
    else
        print_error "Redis 连接失败"
        echo "   请检查 REDIS_URL 配置"
        exit 1
    fi
else
    print_warning "未安装 redis-cli，跳过 Redis 检查"
fi

echo ""

# 检查无效持仓
print_info "检查无效持仓..."
if [ -f "scripts/fix_stale_positions_simple.sh" ]; then
    OPEN_COUNT=$(./scripts/fix_stale_positions_simple.sh --dry-run 2>&1 | grep -oP "找到 \K\d+" || echo "0")
    if [ "$OPEN_COUNT" != "0" ] && [ -n "$OPEN_COUNT" ]; then
        print_warning "发现 $OPEN_COUNT 个 OPEN 持仓"
        echo "   建议先清理："
        echo "   ./scripts/fix_stale_positions_simple.sh --dry-run"
        echo "   ./scripts/fix_stale_positions_simple.sh --force"
        echo ""
        read -p "是否现在清理? (yes/no): " confirm
        if [ "$confirm" = "yes" ] || [ "$confirm" = "y" ]; then
            ./scripts/fix_stale_positions_simple.sh --force
        fi
    else
        print_success "没有无效持仓"
    fi
else
    print_warning "未找到修复脚本，跳过持仓检查"
fi

echo ""

# 检查服务状态
print_info "检查服务状态..."
if command -v docker > /dev/null 2>&1 && docker compose ps > /dev/null 2>&1; then
    print_info "Docker Compose 可用"
    echo ""
    echo "下一步操作："
    echo "  1. 启动服务："
    echo "     docker compose up -d"
    echo ""
    echo "  2. 监控执行服务日志："
    echo "     docker compose logs -f execution"
    echo ""
    echo "  3. 检查服务健康状态："
    echo "     curl http://localhost:8003/health | python3 -m json.tool"
    echo ""
    echo "  4. 监控订单执行："
    echo "     curl http://localhost:8000/v1/orders?limit=10 | python3 -m json.tool"
else
    print_warning "Docker Compose 不可用，请手动检查服务状态"
fi

echo ""
print_success "准备检查完成！"
echo ""
print_warning "⚠️  实盘交易提醒："
echo "   1. 确保风险配置合理（RISK_PCT ≤ 0.005）"
echo "   2. 启用所有风控开关"
echo "   3. 准备好紧急停止方案（Kill Switch）"
echo "   4. 实时监控执行服务日志"
echo "   5. 在 Bybit 交易所验证订单"
