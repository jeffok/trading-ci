#!/bin/bash
# -*- coding: utf-8 -*-
# 快速测试脚本 - 一键完成下单流程测试

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
API_BASE="http://localhost:8000"
WAIT_TIME=15

# 打印函数
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

# 检查服务健康状态
check_health() {
    print_info "检查服务健康状态..."
    
    local services=("api:8000" "marketdata:8001" "strategy:8002" "execution:8003" "notifier:8004")
    local all_ok=true
    
    for svc in "${services[@]}"; do
        IFS=':' read -r name port <<< "$svc"
        if curl -s -f "${API_BASE%:8000}:${port}/health" > /dev/null 2>&1; then
            print_success "${name} 服务正常"
        else
            print_error "${name} 服务异常"
            all_ok=false
        fi
    done
    
    if [ "$all_ok" = false ]; then
        print_error "部分服务未启动，请先启动所有服务"
        return 1
    fi
    
    return 0
}

# 检查数据库连接
check_database() {
    print_info "检查数据库连接..."
    
    if command -v psql > /dev/null 2>&1; then
        if psql -U postgres -d trading-ci -c "SELECT 1;" > /dev/null 2>&1; then
            print_success "数据库连接正常"
            return 0
        else
            print_error "数据库连接失败"
            return 1
        fi
    else
        print_warning "未安装 psql，跳过数据库检查"
        return 0
    fi
}

# 检查 Redis 连接
check_redis() {
    print_info "检查 Redis 连接..."
    
    if command -v redis-cli > /dev/null 2>&1; then
        if redis-cli ping > /dev/null 2>&1; then
            print_success "Redis 连接正常"
            return 0
        else
            print_error "Redis 连接失败"
            return 1
        fi
    else
        print_warning "未安装 redis-cli，跳过 Redis 检查"
        return 0
    fi
}

# 运行 Smoke Test
run_smoke_test() {
    print_info "运行 Smoke Test（注入 trade_plan）..."
    
    if [ ! -f "scripts/e2e_smoke_test.py" ]; then
        print_error "找不到 e2e_smoke_test.py 脚本"
        return 1
    fi
    
    python3 scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds "$WAIT_TIME"
    
    if [ $? -eq 0 ]; then
        print_success "Smoke Test 完成"
        return 0
    else
        print_error "Smoke Test 失败"
        return 1
    fi
}

# 查询测试结果
query_results() {
    print_info "查询测试结果..."
    
    echo ""
    print_info "=== 最近的交易计划 ==="
    curl -s "${API_BASE}/v1/trade-plans?limit=3" | python3 -m json.tool 2>/dev/null || echo "查询失败"
    
    echo ""
    print_info "=== 最近的订单 ==="
    curl -s "${API_BASE}/v1/orders?limit=5" | python3 -m json.tool 2>/dev/null || echo "查询失败"
    
    echo ""
    print_info "=== 当前持仓 ==="
    curl -s "${API_BASE}/v1/positions?limit=5" | python3 -m json.tool 2>/dev/null || echo "查询失败"
    
    echo ""
    print_info "=== 最近的执行报告 ==="
    curl -s "${API_BASE}/v1/execution-reports?limit=5" | python3 -m json.tool 2>/dev/null || echo "查询失败"
}

# 主函数
main() {
    echo "=========================================="
    echo "   Trading-CI 快速测试脚本"
    echo "=========================================="
    echo ""
    
    # 解析参数
    SKIP_CHECKS=false
    SKIP_QUERY=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-checks)
                SKIP_CHECKS=true
                shift
                ;;
            --skip-query)
                SKIP_QUERY=true
                shift
                ;;
            --wait-time)
                WAIT_TIME="$2"
                shift 2
                ;;
            --help|-h)
                echo "用法: $0 [选项]"
                echo ""
                echo "选项:"
                echo "  --skip-checks    跳过健康检查"
                echo "  --skip-query     跳过结果查询"
                echo "  --wait-time N    等待时间（秒，默认15）"
                echo "  --help, -h       显示帮助信息"
                exit 0
                ;;
            *)
                print_error "未知参数: $1"
                echo "使用 --help 查看帮助"
                exit 1
                ;;
        esac
    done
    
    # 执行检查
    if [ "$SKIP_CHECKS" = false ]; then
        check_health || exit 1
        check_database || exit 1
        check_redis || exit 1
        echo ""
    fi
    
    # 运行测试
    run_smoke_test || exit 1
    
    echo ""
    
    # 查询结果
    if [ "$SKIP_QUERY" = false ]; then
        query_results
    fi
    
    echo ""
    print_success "测试完成！"
    print_info "使用以下命令查看详细结果："
    echo "  curl ${API_BASE}/v1/trade-plans?limit=10 | jq"
    echo "  curl ${API_BASE}/v1/orders?limit=10 | jq"
    echo "  curl ${API_BASE}/v1/execution-reports?limit=10 | jq"
}

# 运行主函数
main "$@"
