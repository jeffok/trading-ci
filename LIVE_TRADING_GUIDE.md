# 实盘交易测试指南

## ⚠️ 重要安全提示

**实盘交易涉及真实资金，请务必谨慎操作！**

1. ✅ **先清理无效持仓**：确保数据库状态与交易所一致
2. ✅ **使用小金额测试**：设置较小的 `RISK_PCT`（如 0.001 = 0.1%）
3. ✅ **启用所有风控**：确保所有保护机制已启用
4. ✅ **准备紧急停止方案**：知道如何快速停止交易
5. ✅ **监控日志**：实时监控执行服务日志

---

## 📋 实盘测试前准备清单

### 1. 清理无效持仓

```bash
# 查看当前持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 同步数据库持仓与交易所持仓（自动检测并修复无效持仓）
docker compose exec execution python -m scripts.trading_test_tool sync

# 或者先查看将要执行的操作（dry-run 模式）
docker compose exec execution python -m scripts.trading_test_tool sync --dry-run

# 验证清理结果
docker compose exec execution python -m scripts.trading_test_tool positions
```

### 2. 配置环境变量

编辑 `.env` 文件，确保以下配置：

```bash
# ========== 必填配置 ==========
# 执行模式：必须设置为 LIVE
EXECUTION_MODE=LIVE

# 环境：生产环境
ENV=prod

# Bybit API（实盘交易必填）
BYBIT_API_KEY=your_real_api_key
BYBIT_API_SECRET=your_real_api_secret
BYBIT_BASE_URL=https://api.bybit.com
BYBIT_REST_BASE_URL=https://api.bybit.com

# 数据库和 Redis
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trading-ci
REDIS_URL=redis://localhost:6379/0

# ========== 风控配置（强烈建议） ==========
# 风险百分比（实盘建议：0.001-0.005，即 0.1%-0.5%）
RISK_PCT=0.001

# 最大同时持仓数（建议：1-3）
MAX_OPEN_POSITIONS=1

# 账户熔断（强烈建议启用）
ACCOUNT_KILL_SWITCH_ENABLED=true
DAILY_LOSS_LIMIT_PCT=0.02

# 风险熔断（强烈建议启用）
RISK_CIRCUIT_ENABLED=true
DAILY_DRAWDOWN_SOFT_PCT=0.01
DAILY_DRAWDOWN_HARD_PCT=0.02

# ========== 其他重要配置 ==========
# 管理员令牌（用于紧急停止）
ADMIN_TOKEN=your_strong_admin_token

# 通知（可选，但建议配置）
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

### 3. 验证配置

```bash
# 检查配置（脱敏）
curl http://localhost:8000/v1/config | python3 -m json.tool | grep -E "EXECUTION_MODE|RISK_PCT|MAX_OPEN_POSITIONS|ACCOUNT_KILL_SWITCH_ENABLED"

# 应该看到：
# "EXECUTION_MODE": "LIVE"
# "RISK_PCT": 0.001
# "MAX_OPEN_POSITIONS": 1
# "ACCOUNT_KILL_SWITCH_ENABLED": true
```

### 4. 检查服务状态

```bash
# 检查所有服务健康状态
for port in 8000 8001 8002 8003 8004; do
  echo "检查端口 $port:"
  curl -s http://localhost:$port/health | python3 -m json.tool || echo "失败"
  echo ""
done

# 特别检查执行服务
curl http://localhost:8003/health | python3 -m json.tool
# 应该看到 "execution_mode": "LIVE"
```

---

## 🚀 实盘测试流程

### 步骤1：启动服务

```bash
# 确保所有服务运行
docker compose up -d

# 查看服务状态
docker compose ps

# 监控执行服务日志（重要！）
docker compose logs -f execution
```

### 步骤2：等待市场数据

系统需要接收市场数据才能生成交易信号：

```bash
# 检查 bar_close 事件是否正常
redis-cli XREVRANGE stream:bar_close + - COUNT 5

# 检查市场数据服务日志
docker compose logs marketdata | tail -20
```

### 步骤3：监控信号生成

```bash
# 查看最近的信号
curl "http://localhost:8000/v1/signals?limit=10" | python3 -m json.tool

# 查看交易计划
curl "http://localhost:8000/v1/trade-plans?limit=10" | python3 -m json.tool
```

### 步骤4：监控订单执行

```bash
# 实时监控执行服务日志
docker compose logs -f execution

# 查看订单
curl "http://localhost:8000/v1/orders?limit=10" | python3 -m json.tool

# 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=20" | python3 -m json.tool

# 查看持仓
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool
```

### 步骤5：验证交易所订单

在 Bybit 交易所界面验证：
- 订单是否真实创建
- 持仓是否正确
- 止损/止盈是否设置

---

## 🔍 实时监控命令

### 监控执行服务（最重要）

```bash
# 实时日志
docker compose logs -f execution

# 只看错误
docker compose logs execution | grep -i "error\|exception\|rejected"

# 只看订单相关
docker compose logs execution | grep -i "order\|position\|execution_report"
```

### 监控风险状态

```bash
# 查询今日风险状态
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-state?trade_date=${TRADE_DATE}" | python3 -m json.tool

# 查询风险事件
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool
```

### 监控 Redis Streams

```bash
# 监控关键事件流
watch -n 2 'redis-cli XREVRANGE stream:trade_plan + - COUNT 3'
watch -n 2 'redis-cli XREVRANGE stream:execution_report + - COUNT 5'
watch -n 2 'redis-cli XREVRANGE stream:risk_event + - COUNT 5'
```

---

## 🛑 紧急停止方案

### 方案1：通过 API 启用 Kill Switch（推荐）

```bash
# 启用 Kill Switch（停止新开仓）
curl -X POST http://localhost:8000/v1/admin/kill-switch \
  -H "X-Admin-Token: your_admin_token" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# 验证状态
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-state?trade_date=${TRADE_DATE}" | python3 -m json.tool | grep kill_switch
```

### 方案2：停止服务

```bash
# 停止所有服务
docker compose down

# 或只停止执行服务
docker compose stop execution
```

### 方案3：在 Bybit 交易所手动操作

- 在 Bybit 交易所界面手动平仓
- 取消所有挂单
- 系统会在下次同步时检测到

---

## 📊 验证真实下单

### 检查订单是否真实创建

```bash
# 1. 查看数据库中的订单
psql -U postgres -d trading-ci -c "
SELECT order_id, symbol, side, order_type, qty, status, bybit_order_id, created_at 
FROM orders 
ORDER BY created_at DESC 
LIMIT 10;"

# 2. 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=10" | python3 -m json.tool

# 3. 查看执行轨迹（用于调试）
curl "http://localhost:8000/v1/execution-traces?idempotency_key=your_idempotency_key&limit=50" | python3 -m json.tool
```

### 验证 Bybit 交易所

1. 登录 Bybit 交易所
2. 查看"订单"页面，确认订单已创建
3. 查看"持仓"页面，确认持仓正确
4. 查看"条件单"页面，确认止损/止盈已设置

---

## ⚙️ 测试场景

### 场景1：等待自然信号（推荐）

让系统正常运行，等待策略自然生成信号：

```bash
# 监控日志
docker compose logs -f execution

# 等待信号生成和执行
# 系统会自动：
# 1. 接收市场数据
# 2. 生成交易信号
# 3. 创建交易计划
# 4. 执行下单
```

### 场景2：手动注入 trade_plan（快速测试）

如果需要快速测试下单流程：

```bash
# 注入测试 trade_plan（会真实下单！）
SMOKE_SYMBOL=BTCUSDT \
SMOKE_SIDE=BUY \
SMOKE_ENTRY_PRICE=30000 \
SMOKE_SL_PRICE=29000 \
python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 20

# ⚠️ 注意：这会真实下单，请确保金额设置合理！
```

---

## 🔐 安全建议

### 1. 金额控制

```bash
# 设置非常小的风险百分比
RISK_PCT=0.001  # 0.1%，每笔交易只使用账户的 0.1%

# 限制最大持仓数
MAX_OPEN_POSITIONS=1  # 同时只允许 1 个持仓
```

### 2. 风控启用

```bash
# 启用账户熔断
ACCOUNT_KILL_SWITCH_ENABLED=true
DAILY_LOSS_LIMIT_PCT=0.02  # 单日亏损 2% 触发熔断

# 启用风险熔断
RISK_CIRCUIT_ENABLED=true
DAILY_DRAWDOWN_SOFT_PCT=0.01  # 回撤 1% 停止新开仓
DAILY_DRAWDOWN_HARD_PCT=0.02  # 回撤 2% 强制平仓
```

### 3. API Key 权限

在 Bybit 创建 API Key 时：
- ✅ 只授予"交易"权限
- ✅ **不要**授予"提现"权限
- ✅ 设置 IP 白名单（如果可能）
- ✅ 设置合理的 API Key 有效期

### 4. 监控告警

```bash
# 配置 Telegram 通知（强烈建议）
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 这样可以在手机上实时收到交易通知
```

---

## 📝 测试检查清单

- [ ] 已清理无效持仓
- [ ] 执行模式设置为 `LIVE`
- [ ] Bybit API Key/Secret 已配置
- [ ] 风险百分比设置合理（≤0.005）
- [ ] 最大持仓数限制（≤3）
- [ ] 账户熔断已启用
- [ ] 风险熔断已启用
- [ ] 管理员令牌已设置
- [ ] Telegram 通知已配置（可选但推荐）
- [ ] 所有服务正常运行
- [ ] 市场数据正常接收
- [ ] 已准备好紧急停止方案
- [ ] 已了解如何查看订单和持仓

---

## 🆘 常见问题

### Q1: 订单没有创建？

```bash
# 检查执行服务日志
docker compose logs execution | tail -50

# 检查是否有错误
docker compose logs execution | grep -i "error\|exception"

# 检查风控状态
curl "http://localhost:8000/v1/risk-state?trade_date=$(date +%Y-%m-%d)" | python3 -m json.tool
```

### Q2: 订单被拒绝？

```bash
# 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=20" | python3 -m json.tool

# 查看风险事件
curl "http://localhost:8000/v1/risk-events?trade_date=$(date +%Y-%m-%d)&limit=20" | python3 -m json.tool
```

### Q3: 如何确认订单真实创建？

1. 查看数据库中的 `bybit_order_id`（如果为空，说明未真实下单）
2. 在 Bybit 交易所界面查看订单
3. 查看执行报告中的订单状态

---

## 📚 相关文档

- [COMPLETE_TESTING_GUIDE.md](./COMPLETE_TESTING_GUIDE.md) - 完整测试指南
- [SYNC_MECHANISM.md](./SYNC_MECHANISM.md) - 订单与持仓同步机制说明
- [.env.example](./.env.example) - 环境变量配置示例

---

**最后提醒**：实盘交易涉及真实资金，请务必：
1. 充分测试后再使用真实资金
2. 从小金额开始
3. 实时监控
4. 准备好紧急停止方案

祝交易顺利！🚀
