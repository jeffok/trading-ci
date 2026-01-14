# 手动实盘下单测试指南

## 🎯 目标

进行一次完整的实盘下单流程测试，验证：
1. trade_plan 是否能被正确消费
2. 订单是否能真实创建到 Bybit 交易所
3. 止损/止盈是否能正确设置
4. 数据库是否能正确记录

## ⚠️ 重要安全提示

**此操作会真实下单，涉及真实资金！**

1. ✅ 确保 `RISK_PCT` 设置合理（建议 ≤ 0.001，即 0.1%）
2. ✅ 确保 `MAX_OPEN_POSITIONS=1`（限制同时持仓数）
3. ✅ 准备好紧急停止方案
4. ✅ 实时监控执行服务日志
5. ✅ 在 Bybit 交易所验证订单

## 📋 测试前准备

### 1. 检查配置

```bash
# 运行准备检查
./scripts/prepare_live_trading.sh

# 确保：
# - EXECUTION_MODE=LIVE
# - Bybit API Key/Secret 已配置
# - 风险配置合理
```

### 2. 启用风控（强烈建议）

编辑 `.env` 文件：

```bash
# 启用账户熔断
ACCOUNT_KILL_SWITCH_ENABLED=true
DAILY_LOSS_LIMIT_PCT=0.02

# 启用风险熔断
RISK_CIRCUIT_ENABLED=true
DAILY_DRAWDOWN_SOFT_PCT=0.01
DAILY_DRAWDOWN_HARD_PCT=0.02

# 小金额测试
RISK_PCT=0.001  # 0.1%
MAX_OPEN_POSITIONS=1
```

重启执行服务：

```bash
docker compose restart execution
```

### 3. 启动监控

在另一个终端启动日志监控：

```bash
# 实时监控执行服务日志（最重要！）
docker compose logs -f execution
```

## 🚀 执行测试

### 方法1：使用测试脚本（推荐）

```bash
# 基本用法（会提示确认）
python scripts/live_trade_test.py \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000

# 跳过确认（谨慎使用）
python scripts/live_trade_test.py \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000 \
  --confirm

# 在 Docker 容器中运行
docker compose exec execution python -m scripts.live_trade_test \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000
```

### 方法2：使用 smoke_test 脚本

```bash
# ⚠️ 注意：这会真实下单！
SMOKE_SYMBOL=BTCUSDT \
SMOKE_SIDE=BUY \
SMOKE_ENTRY_PRICE=30000 \
SMOKE_SL_PRICE=29000 \
python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 30
```

## 📊 验证结果

### 1. 查看执行服务日志

```bash
# 查看最新日志
docker compose logs execution | tail -100

# 查找订单相关日志
docker compose logs execution | grep -i "order\|execution_report\|bybit"
```

### 2. 查询数据库

```bash
# 查询订单（替换 idempotency_key）
docker compose exec execution psql "$DATABASE_URL" -c "
SELECT 
    order_id, 
    symbol, 
    side, 
    order_type, 
    qty, 
    status, 
    bybit_order_id,  -- ⚠️ 如果为空，说明未真实下单
    created_at 
FROM orders 
ORDER BY created_at DESC 
LIMIT 10;"

# 查询持仓
docker compose exec execution psql "$DATABASE_URL" -c "
SELECT 
    position_id, 
    symbol, 
    side, 
    qty_total, 
    entry_price, 
    primary_sl_price, 
    status, 
    created_at 
FROM positions 
WHERE status='OPEN' 
ORDER BY created_at DESC;"

# 查询执行报告
docker compose exec execution psql "$DATABASE_URL" -c "
SELECT 
    report_id, 
    symbol, 
    type, 
    status, 
    plan_id, 
    created_at 
FROM execution_reports 
ORDER BY created_at DESC 
LIMIT 20;"
```

### 3. 通过 API 查询

```bash
# 查询订单
curl "http://localhost:8000/v1/orders?limit=10" | python3 -m json.tool

# 查询持仓
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool

# 查询执行报告
curl "http://localhost:8000/v1/execution-reports?limit=20" | python3 -m json.tool
```

### 4. 在 Bybit 交易所验证（最重要！）

1. **登录 Bybit 交易所**
2. **查看"订单"页面**
   - 应该能看到新创建的订单
   - 检查订单状态（Filled/Pending/Cancelled）
   - 检查订单类型、数量、价格
3. **查看"持仓"页面**
   - 如果订单已成交，应该能看到持仓
   - 检查持仓方向、数量、入场价格
4. **查看"条件单"页面**
   - 应该能看到止损单（Stop Loss）
   - 应该能看到止盈单（Take Profit）

## 🔍 关键验证点

### ✅ 订单真实创建

检查点：
- [ ] 数据库中的 `bybit_order_id` 不为空
- [ ] Bybit 交易所能看到订单
- [ ] 订单状态正确（Filled/Pending）

### ✅ 止损/止盈设置

检查点：
- [ ] Bybit 交易所的条件单页面能看到止损单
- [ ] 止损价格正确
- [ ] 止盈单（TP1/TP2）已设置

### ✅ 数据库记录

检查点：
- [ ] `orders` 表有记录
- [ ] `positions` 表有记录（如果订单已成交）
- [ ] `execution_reports` 表有记录

## 🛑 如果订单被拒绝

如果订单被拒绝，查看原因：

```bash
# 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=20" | python3 -m json.tool | grep -A 5 "REJECTED"

# 查看风险事件
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool

# 查看执行服务日志
docker compose logs execution | grep -i "rejected\|error\|blocked" | tail -20
```

常见拒绝原因：
- `position_mutex_blocked`：已有同币种同向持仓
- `max_positions_blocked`：超过最大持仓数限制
- `kill_switch_on`：Kill Switch 已启用
- `risk_circuit_blocked`：风险熔断触发
- `cooldown_blocked`：冷却期未结束

## 🧹 测试后清理（可选）

如果测试后想清理测试数据：

```bash
# 清理测试订单和持仓（谨慎使用）
docker compose exec execution psql "$DATABASE_URL" -c "
UPDATE positions 
SET status='CLOSED', 
    updated_at=now(), 
    closed_at_ms=extract(epoch from now())::bigint * 1000,
    exit_reason='TEST_CLEANUP'
WHERE status='OPEN' AND meta->>'live_test' = 'true';"
```

## 📝 完整测试流程示例

```bash
# 1. 准备
./scripts/prepare_live_trading.sh

# 2. 启动监控（另一个终端）
docker compose logs -f execution

# 3. 执行测试
python scripts/live_trade_test.py \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000 \
  --wait-seconds 30

# 4. 验证订单
# - 查看执行服务日志
# - 查询数据库
# - 在 Bybit 交易所验证

# 5. 如果需要，手动平仓
# - 在 Bybit 交易所手动平仓
# - 或等待系统自动处理
```

## 💡 提示

1. **价格设置**：使用当前市场价格附近的合理价格
2. **金额控制**：确保 `RISK_PCT` 设置合理，避免单笔交易金额过大
3. **实时监控**：务必实时监控执行服务日志
4. **验证订单**：最重要是在 Bybit 交易所验证订单是否真实创建
5. **准备停止**：准备好紧急停止方案（Kill Switch）

---

**现在可以开始实盘测试了！** 🚀

记住：这是真实下单，请谨慎操作！
