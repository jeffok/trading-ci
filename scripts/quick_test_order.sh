#!/bin/bash
# 快速测试下单脚本
# 用法: ./scripts/quick_test_order.sh BTCUSDT BUY

set -e

SYMBOL=${1:-BTCUSDT}
SIDE=${2:-BUY}

echo "=========================================="
echo "  快速测试下单"
echo "=========================================="
echo ""
echo "交易对: $SYMBOL"
echo "方向: $SIDE"
echo ""

# 检查是否在 Docker 环境中
if command -v docker &> /dev/null; then
    echo "📦 在 Docker 容器中执行..."
    docker compose exec execution python -m scripts.trading_test_tool test \
        --symbol "$SYMBOL" \
        --side "$SIDE" \
        --timeframe 1h \
        --sl-distance-pct 0.02 \
        --auto-diagnose \
        --confirm \
        --wait-seconds 30
else
    echo "💻 在本地环境执行..."
    python -m scripts.trading_test_tool test \
        --symbol "$SYMBOL" \
        --side "$SIDE" \
        --timeframe 1h \
        --sl-distance-pct 0.02 \
        --auto-diagnose \
        --confirm \
        --wait-seconds 30
fi

echo ""
echo "✅ 测试完成！"
echo ""
echo "💡 提示："
echo "  - 查看执行日志: docker compose logs -f execution"
echo "  - 查看订单: docker compose exec execution python -m scripts.trading_test_tool orders"
echo "  - 查看持仓: docker compose exec execution python -m scripts.trading_test_tool positions"
