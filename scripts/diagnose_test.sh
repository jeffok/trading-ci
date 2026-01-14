#!/bin/bash
# -*- coding: utf-8 -*-
# 诊断脚本 - 排查下单流程测试问题

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

API_BASE="http://localhost:8000"

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
echo "   Trading-CI 诊断脚本"
echo "=========================================="
echo ""

# 1. 检查 Redis Streams 状态
print_info "1. 检查 Redis Streams 状态..."
if command -v redis-cli > /dev/null 2>&1; then
    echo ""
    echo "stream:trade_plan 最新消息："
    redis-cli XREVRANGE stream:trade_plan + - COUNT 3 2>/dev/null || echo "无法连接 Redis"
    
    echo ""
    echo "stream:execution_report 最新消息："
    redis-cli XREVRANGE stream:execution_report + - COUNT 3 2>/dev/null || echo "无法连接 Redis"
    
    echo ""
    echo "stream:risk_event 最新消息："
    redis-cli XREVRANGE stream:risk_event + - COUNT 3 2>/dev/null || echo "无法连接 Redis"
    
    echo ""
    echo "消费者组状态："
    redis-cli XINFO GROUPS stream:trade_plan 2>/dev/null || echo "无法查询"
else
    print_warning "未安装 redis-cli，跳过 Redis 检查"
fi

echo ""
print_info "2. 检查 API 接口..."
echo ""

# 检查 API 是否返回空列表（不是 404）
check_api() {
    local endpoint=$1
    local name=$2
    local response=$(curl -s "${API_BASE}${endpoint}")
    
    if echo "$response" | grep -q "Not Found"; then
        print_error "${name}: API 返回 Not Found"
        echo "  响应: $response"
    elif echo "$response" | grep -q '"items"'; then
        local count=$(echo "$response" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('items', [])))" 2>/dev/null || echo "?")
        if [ "$count" = "0" ]; then
            print_warning "${name}: 返回空列表（数据库中没有数据）"
        else
            print_success "${name}: 找到 $count 条记录"
        fi
    else
        print_warning "${name}: 响应格式异常"
        echo "  响应: $response"
    fi
}

check_api "/v1/trade-plans?limit=5" "交易计划"
check_api "/v1/orders?limit=5" "订单"
check_api "/v1/positions?limit=5" "持仓"
check_api "/v1/execution-reports?limit=5" "执行报告"

echo ""
print_info "3. 检查配置..."
echo ""

# 检查执行模式
exec_mode=$(curl -s "${API_BASE}/v1/config" 2>/dev/null | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('config', {}).get('EXECUTION_MODE', 'unknown'))" 2>/dev/null || echo "unknown")
echo "执行模式: $exec_mode"

if [ "$exec_mode" = "LIVE" ]; then
    print_warning "当前是 LIVE 模式，需要配置 Bybit API Key/Secret"
    echo "  建议：设置 EXECUTION_MODE=PAPER 进行测试"
fi

echo ""
print_info "4. 检查数据库（如果可用）..."
echo ""

if command -v psql > /dev/null 2>&1; then
    echo "trade_plans 表记录数："
    psql -U postgres -d trading-ci -t -c "SELECT COUNT(*) FROM trade_plans;" 2>/dev/null || echo "无法查询"
    
    echo ""
    echo "orders 表记录数："
    psql -U postgres -d trading-ci -t -c "SELECT COUNT(*) FROM orders;" 2>/dev/null || echo "无法查询"
    
    echo ""
    echo "execution_reports 表记录数："
    psql -U postgres -d trading-ci -t -c "SELECT COUNT(*) FROM execution_reports;" 2>/dev/null || echo "无法查询"
    
    echo ""
    echo "最近的 trade_plan（如果有）："
    psql -U postgres -d trading-ci -c "SELECT plan_id, symbol, side, entry_price, status, created_at FROM trade_plans ORDER BY created_at DESC LIMIT 3;" 2>/dev/null || echo "无法查询"
else
    print_warning "未安装 psql，跳过数据库检查"
fi

echo ""
print_info "5. 建议的排查步骤："
echo ""
echo "1. 查看执行服务日志："
echo "   docker compose logs execution | tail -50"
echo "   或"
echo "   docker compose logs execution | grep -i 'trade_plan\|error\|exception'"
echo ""
echo "2. 如果执行模式是 LIVE，检查 Bybit API 配置："
echo "   - BYBIT_API_KEY 是否设置"
echo "   - BYBIT_API_SECRET 是否设置"
echo "   - 建议先使用 PAPER 模式测试：EXECUTION_MODE=PAPER"
echo ""
echo "3. 手动检查 Redis Streams："
echo "   redis-cli XREVRANGE stream:trade_plan + - COUNT 5"
echo "   redis-cli XREVRANGE stream:execution_report + - COUNT 5"
echo ""
echo "4. 检查消费者是否在处理消息："
echo "   redis-cli XINFO GROUPS stream:trade_plan"
echo "   redis-cli XPENDING stream:trade_plan bot-group"
echo ""
echo "5. 重新注入 trade_plan 并观察日志："
echo "   python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 20"
echo "   # 同时在另一个终端查看日志："
echo "   docker compose logs -f execution"
