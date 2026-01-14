# 实盘交易快速开始

## ✅ 当前状态检查

根据你的输出：

1. ✅ **无效持仓已清理**：`fix_stale_positions_simple.sh` 显示没有 OPEN 持仓
2. ✅ **执行服务正常**：健康检查返回 `execution_mode: LIVE`
3. ✅ **配置正确**：Bybit API Key/Secret 已配置
4. ⚠️ **API 返回 Not Found**：可能是数据库中没有数据（正常）

## 🚀 实盘测试步骤

### 步骤1：确认服务运行状态

```bash
# 检查所有服务
docker compose ps

# 检查执行服务健康状态
curl http://localhost:8003/health | python3 -m json.tool

# 应该看到：
# {
#   "env": "prod",
#   "service": "execution-service",
#   "redis_ok": true,
#   "db_url_present": true,
#   "execution_mode": "LIVE"
# }
```

### 步骤2：启用风控（强烈建议）

编辑 `.env` 文件，确保以下配置：

```bash
# 启用账户熔断
ACCOUNT_KILL_SWITCH_ENABLED=true
DAILY_LOSS_LIMIT_PCT=0.02

# 启用风险熔断
RISK_CIRCUIT_ENABLED=true
DAILY_DRAWDOWN_SOFT_PCT=0.01
DAILY_DRAWDOWN_HARD_PCT=0.02

# 设置小金额测试
RISK_PCT=0.001  # 0.1%
MAX_OPEN_POSITIONS=1
```

然后重启执行服务：

```bash
docker compose restart execution
```

### 步骤3：监控执行服务日志

```bash
# 实时监控（重要！）
docker compose logs -f execution
```

### 步骤4：等待或触发交易

#### 方式A：等待自然信号（推荐）

让系统正常运行，等待策略自然生成信号：

```bash
# 监控日志，等待信号生成
docker compose logs -f execution

# 系统会自动：
# 1. 接收市场数据（marketdata-service）
# 2. 生成交易信号（strategy-service）
# 3. 创建交易计划
# 4. 执行下单（execution-service）
```

#### 方式B：手动注入 trade_plan（快速测试）

⚠️ **注意：这会真实下单！**

```bash
# 注入测试 trade_plan
SMOKE_SYMBOL=BTCUSDT \
SMOKE_SIDE=BUY \
SMOKE_ENTRY_PRICE=30000 \
SMOKE_SL_PRICE=29000 \
python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 20
```

### 步骤5：验证真实下单

#### 查看订单

```bash
# 查看订单（如果 API 返回 Not Found，说明还没有订单，这是正常的）
curl "http://localhost:8000/v1/orders?limit=10" | python3 -m json.tool

# 或直接查询数据库
docker compose exec execution psql "$DATABASE_URL" -c "
SELECT order_id, symbol, side, order_type, qty, status, bybit_order_id, created_at 
FROM orders 
ORDER BY created_at DESC 
LIMIT 10;"
```

#### 查看执行报告

```bash
# 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=20" | python3 -m json.tool

# 或查询数据库
docker compose exec execution psql "$DATABASE_URL" -c "
SELECT report_id, symbol, type, severity, plan_id, status, created_at 
FROM execution_reports 
ORDER BY created_at DESC 
LIMIT 20;"
```

#### 在 Bybit 交易所验证

1. 登录 Bybit 交易所
2. 查看"订单"页面，确认订单已创建
3. 查看"持仓"页面，确认持仓正确
4. 查看"条件单"页面，确认止损/止盈已设置

## 🔍 API 返回 "Not Found" 说明

如果 API 返回 `{"detail": "Not Found"}`，可能的原因：

1. **数据库中没有数据**（正常情况）
   - 如果还没有生成订单/持仓，这是正常的
   - 等待系统生成交易后，API 就会返回数据

2. **API 路由问题**
   - 检查 API 服务是否正常运行：`curl http://localhost:8000/health`
   - 检查 API 日志：`docker compose logs api | tail -20`

3. **数据库连接问题**
   - 检查 API 服务的数据库连接：`docker compose logs api | grep -i "error\|database"`

## 🛑 紧急停止

如果需要立即停止交易：

```bash
# 方法1：启用 Kill Switch（推荐）
curl -X POST http://localhost:8000/v1/admin/kill-switch \
  -H "X-Admin-Token: your_admin_token" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# 方法2：停止执行服务
docker compose stop execution

# 方法3：停止所有服务
docker compose down
```

## 📊 监控命令

### 实时监控

```bash
# 执行服务日志（最重要）
docker compose logs -f execution

# 策略服务日志
docker compose logs -f strategy

# 市场数据服务日志
docker compose logs -f marketdata
```

### 查询状态

```bash
# 查询风险状态
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-state?trade_date=${TRADE_DATE}" | python3 -m json.tool

# 查询风险事件
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool

# 查询持仓
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool

# 查询订单
curl "http://localhost:8000/v1/orders?limit=10" | python3 -m json.tool
```

## ✅ 检查清单

- [x] 无效持仓已清理
- [x] 执行模式设置为 LIVE
- [x] Bybit API Key/Secret 已配置
- [ ] 风控开关已启用（建议启用）
- [x] 执行服务正常运行
- [ ] 实时监控日志（重要！）
- [ ] 准备好紧急停止方案

## 💡 提示

1. **API 返回 Not Found 是正常的**：如果数据库中没有数据，这是预期行为
2. **等待信号生成**：系统需要接收市场数据才能生成交易信号
3. **实时监控**：务必实时监控执行服务日志
4. **小金额测试**：建议先用小金额测试（RISK_PCT=0.001）
5. **验证订单**：在 Bybit 交易所界面验证订单是否真实创建

---

**你现在可以开始实盘测试了！** 🚀

监控执行服务日志，等待交易信号生成和执行。
