#!/bin/bash
# -*- coding: utf-8 -*-
# 数据库连接测试脚本

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
echo "  数据库连接测试"
echo "=========================================="
echo ""

# 方法1：从 .env 文件读取
print_info "方法1：从 .env 文件读取 DATABASE_URL"
if [ -f ".env" ]; then
    DB_URL=$(grep "^DATABASE_URL=" .env | cut -d'=' -f2- | sed "s/^['\"]//;s/['\"]$//" | head -1)
    if [ -n "$DB_URL" ]; then
        echo "   找到: ${DB_URL%%@*}@***"
        
        # 解析连接字符串
        if [[ "$DB_URL" =~ postgresql://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+)$ ]]; then
            DB_USER="${BASH_REMATCH[1]}"
            DB_PASS="${BASH_REMATCH[2]}"
            DB_HOST="${BASH_REMATCH[3]}"
            DB_PORT="${BASH_REMATCH[4]}"
            DB_NAME="${BASH_REMATCH[5]}"
            
            echo "   解析结果:"
            echo "     用户: $DB_USER"
            echo "     主机: $DB_HOST"
            echo "     端口: $DB_PORT"
            echo "     数据库: $DB_NAME"
            echo ""
            
            # 测试连接
            print_info "测试连接..."
            if PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" > /dev/null 2>&1; then
                print_success "连接成功！"
            else
                print_error "连接失败"
                echo ""
                echo "   尝试手动连接："
                echo "   PGPASSWORD='$DB_PASS' psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c \"SELECT 1;\""
                echo ""
            fi
            
            # 测试使用完整 URL
            print_info "测试使用完整 URL..."
            if psql "$DB_URL" -c "SELECT 1;" > /dev/null 2>&1; then
                print_success "使用完整 URL 连接成功！"
            else
                print_error "使用完整 URL 连接失败"
                echo ""
                echo "   错误信息："
                psql "$DB_URL" -c "SELECT 1;" 2>&1 | head -5 || true
            fi
        else
            print_warning "无法解析 DATABASE_URL 格式"
            echo "   格式应为: postgresql://user:password@host:port/database"
            echo "   当前值: ${DB_URL%%@*}@***"
        fi
    else
        print_warning ".env 文件中未找到 DATABASE_URL"
    fi
else
    print_warning ".env 文件不存在"
fi

echo ""

# 方法2：从环境变量读取
print_info "方法2：从环境变量读取 DATABASE_URL"
if [ -n "${DATABASE_URL:-}" ]; then
    echo "   找到环境变量: ${DATABASE_URL%%@*}@***"
    if psql "$DATABASE_URL" -c "SELECT 1;" > /dev/null 2>&1; then
        print_success "环境变量连接成功！"
    else
        print_error "环境变量连接失败"
        psql "$DATABASE_URL" -c "SELECT 1;" 2>&1 | head -5 || true
    fi
else
    print_warning "环境变量 DATABASE_URL 未设置"
fi

echo ""

# 方法3：使用 Docker 容器测试
print_info "方法3：在 Docker 容器中测试"
if command -v docker > /dev/null 2>&1 && docker compose ps execution > /dev/null 2>&1; then
    echo "   尝试在 execution 容器中测试..."
    if docker compose exec -T execution python3 -c "
import os
from libs.db.pg import get_conn
try:
    with get_conn(os.environ['DATABASE_URL']) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
            print('✅ 容器内连接成功')
except Exception as e:
    print(f'❌ 容器内连接失败: {e}')
" 2>&1; then
        print_success "容器内连接测试完成"
    else
        print_error "容器内连接失败"
    fi
else
    print_warning "Docker 容器不可用，跳过容器测试"
fi

echo ""
print_info "诊断建议："
echo "   1. 检查 .env 文件中的 DATABASE_URL 格式是否正确"
echo "   2. 检查数据库服务是否运行"
echo "   3. 检查用户名密码是否正确"
echo "   4. 检查数据库是否存在"
echo "   5. 检查网络连接和防火墙设置"
echo ""
echo "   如果使用 Docker，可以尝试："
echo "   docker compose exec execution psql \$DATABASE_URL -c \"SELECT 1;\""
