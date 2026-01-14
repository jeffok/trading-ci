#!/bin/bash
# -*- coding: utf-8 -*-
# 检查交易执行状态

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

IDEMPOTENCY_KEY="${1:-}"

if [ -z "$IDEMPOTENCY_KEY" ]; then
    echo "用法: $0 <idempotency_key>"
    echo ""
    echo "示例:"
    echo "  $0 idem-83f85a847e574327a4ba0eac7311b35a"
    exit 1
fi

echo "=========================================="
echo "  检查交易执行状态"
echo "=========================================="
echo ""
print_info "Idempotency Key: $IDEMPOTENCY_KEY"
echo ""

# 1. 检查 Redis Streams
print_info "1. 检查 Redis Streams..."
if command -v redis-cli > /dev/null 2>&1; then
    echo ""
    echo "stream:trade_plan 最新消息："
    redis-cli XREVRANGE stream:trade_plan + - COUNT 3 2>/dev/null | head -20 || echo "无法连接 Redis"
    
    echo ""
    echo "stream:execution_report 最新消息："
    redis-cli XREVRANGE stream:execution_report + - COUNT 5 2>/dev/null | head -30 || echo "无法连接 Redis"
    
    echo ""
    echo "stream:risk_event 最新消息："
    redis-cli XREVRANGE stream:risk_event + - COUNT 5 2>/dev/null | head -30 || echo "无法连接 Redis"
    
    echo ""
    echo "消费者组状态："
    redis-cli XINFO GROUPS stream:trade_plan 2>/dev/null || echo "无法查询"
    redis-cli XPENDING stream:trade_plan bot-group 2>/dev/null || echo "无法查询"
else
    print_warning "未安装 redis-cli，跳过 Redis 检查"
fi

echo ""

# 2. 检查数据库
print_info "2. 检查数据库..."
if command -v docker > /dev/null 2>&1 && docker compose ps execution > /dev/null 2>&1; then
    DB_URL=$(docker compose exec -T execution printenv DATABASE_URL 2>/dev/null || echo "")
    if [ -n "$DB_URL" ]; then
        echo ""
        echo "订单："
        docker compose exec -T execution psql "$DB_URL" -c "
        SELECT 
            order_id, 
            symbol, 
            side, 
            status, 
            bybit_order_id,
            created_at 
        FROM orders 
        WHERE idempotency_key='$IDEMPOTENCY_KEY' 
        ORDER BY created_at DESC;" 2>/dev/null || echo "查询失败"
        
        echo ""
        echo "持仓："
        docker compose exec -T execution psql "$DB_URL" -c "
        SELECT 
            position_id, 
            symbol, 
            side, 
            status, 
            created_at 
        FROM positions 
        WHERE idempotency_key='$IDEMPOTENCY_KEY' 
        ORDER BY created_at DESC;" 2>/dev/null || echo "查询失败"
        
        echo ""
        echo "执行报告："
        docker compose exec -T execution psql "$DB_URL" -c "
        SELECT 
            report_id, 
            symbol, 
            type, 
            status, 
            created_at 
        FROM execution_reports 
        WHERE plan_id IN (
            SELECT plan_id FROM trade_plans WHERE idempotency_key='$IDEMPOTENCY_KEY'
        )
        ORDER BY created_at DESC 
        LIMIT 10;" 2>/dev/null || echo "查询失败"
        
        echo ""
        echo "执行轨迹："
        docker compose exec -T execution psql "$DB_URL" -c "
        SELECT 
            trace_id, 
            step, 
            status, 
            detail, 
            created_at 
        FROM execution_traces 
        WHERE idempotency_key='$IDEMPOTENCY_KEY' 
        ORDER BY created_at DESC 
        LIMIT 20;" 2>/dev/null || echo "查询失败"
    else
        print_warning "无法从容器读取 DATABASE_URL"
    fi
else
    print_warning "Docker 容器不可用，跳过数据库检查"
fi

echo ""

# 3. 检查执行服务日志
print_info "3. 检查执行服务日志..."
if command -v docker > /dev/null 2>&1 && docker compose ps execution > /dev/null 2>&1; then
    echo ""
    echo "最近的执行服务日志（包含 idempotency_key）："
    docker compose logs execution --tail 100 2>/dev/null | grep -i "$IDEMPOTENCY_KEY" || echo "未找到相关日志"
    
    echo ""
    echo "最近的错误日志："
    docker compose logs execution --tail 50 2>/dev/null | grep -i "error\|exception\|traceback\|failed" | tail -10 || echo "未找到错误日志"
    
    echo ""
    echo "最近的 trade_plan 相关日志："
    docker compose logs execution --tail 100 2>/dev/null | grep -i "trade_plan\|execute_trade_plan" | tail -10 || echo "未找到相关日志"
else
    print_warning "Docker 容器不可用，跳过日志检查"
fi

echo ""
print_info "4. 建议的排查步骤："
echo ""
echo "1. 查看执行服务完整日志："
echo "   docker compose logs execution | tail -100"
echo ""
echo "2. 实时监控执行服务："
echo "   docker compose logs -f execution"
echo ""
echo "3. 检查执行服务是否正常运行："
echo "   docker compose ps execution"
echo "   curl http://localhost:8003/health"
echo ""
echo "4. 检查消费者是否在处理消息："
echo "   redis-cli XINFO GROUPS stream:trade_plan"
echo "   redis-cli XPENDING stream:trade_plan bot-group"
echo ""
echo "5. 如果消费者卡住，重启执行服务："
echo "   docker compose restart execution"
