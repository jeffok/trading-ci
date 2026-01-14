# 交易未执行问题排查

## 🔍 问题现象

trade_plan 已注入到 Redis Streams，但：
- ❌ 未找到执行报告
- ❌ 未找到风险事件
- ❌ 数据库中没有订单记录

## 📋 排查步骤

### 步骤1：检查执行服务日志（最重要）

```bash
# 查看最新日志
docker compose logs execution | tail -100

# 查找错误
docker compose logs execution | grep -i "error\|exception\|traceback\|failed" | tail -20

# 查找 trade_plan 相关日志
docker compose logs execution | grep -i "trade_plan\|execute_trade_plan" | tail -20

# 实时监控
docker compose logs -f execution
```

### 步骤2：检查消费者状态

```bash
# 检查消费者组状态
redis-cli XINFO GROUPS stream:trade_plan

# 检查待处理消息
redis-cli XPENDING stream:trade_plan bot-group

# 如果有很多 pending 消息，说明消费者可能卡住了
```

### 步骤3：检查执行服务状态

```bash
# 检查服务是否运行
docker compose ps execution

# 检查健康状态
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

### 步骤4：使用检查脚本

```bash
# 使用检查脚本（替换为你的 idempotency_key）
./scripts/check_trade_execution.sh idem-83f85a847e574327a4ba0eac7311b35a
```

### 步骤5：检查数据库

```bash
# 检查订单
docker compose exec execution psql "$DATABASE_URL" -c "
SELECT order_id, symbol, side, status, bybit_order_id, created_at 
FROM orders 
WHERE idempotency_key='idem-83f85a847e574327a4ba0eac7311b35a' 
ORDER BY created_at DESC;"

# 检查执行报告
docker compose exec execution psql "$DATABASE_URL" -c "
SELECT report_id, symbol, type, status, created_at 
FROM execution_reports 
ORDER BY created_at DESC 
LIMIT 10;"

# 检查执行轨迹
docker compose exec execution psql "$DATABASE_URL" -c "
SELECT trace_id, step, status, detail, created_at 
FROM execution_traces 
WHERE idempotency_key='idem-83f85a847e574327a4ba0eac7311b35a' 
ORDER BY created_at DESC 
LIMIT 20;"
```

## 🔧 常见问题和解决方案

### 问题1：执行服务未启动或崩溃

**症状**：服务健康检查失败

**解决**：
```bash
# 重启执行服务
docker compose restart execution

# 查看启动日志
docker compose logs execution | tail -50
```

### 问题2：消费者未处理消息

**症状**：有很多 pending 消息

**解决**：
```bash
# 重启执行服务
docker compose restart execution

# 检查消费者是否恢复
redis-cli XINFO GROUPS stream:trade_plan
```

### 问题3：执行过程中出错

**症状**：日志中有错误信息

**解决**：
```bash
# 查看详细错误
docker compose logs execution | grep -A 20 "error\|exception\|traceback"

# 常见错误：
# - Schema 验证失败（已修复）
# - Bybit API 调用失败
# - 数据库连接失败
# - 风控规则阻止
```

### 问题4：Bybit API 配置错误

**症状**：API 调用失败

**解决**：
```bash
# 检查 API 配置
curl http://localhost:8000/v1/config | python3 -m json.tool | grep BYBIT

# 检查 API Key/Secret 是否正确
# 检查 API 权限是否足够
```

### 问题5：风控规则阻止

**症状**：订单被拒绝

**解决**：
```bash
# 查看风险事件
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool

# 检查风控状态
curl "http://localhost:8000/v1/risk-state?trade_date=${TRADE_DATE}" | python3 -m json.tool
```

## 🚀 快速修复

如果执行服务没有处理消息，尝试：

```bash
# 1. 重启执行服务
docker compose restart execution

# 2. 等待几秒后检查日志
sleep 5
docker compose logs execution | tail -50

# 3. 检查消费者状态
redis-cli XINFO GROUPS stream:trade_plan

# 4. 如果还是不行，重新注入 trade_plan
python scripts/live_trade_test.py \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000 \
  --confirm
```

## 📊 验证修复

修复后，应该能看到：

1. **执行服务日志**中有处理 trade_plan 的记录
2. **数据库**中有订单记录（`orders` 表）
3. **执行报告**中有记录（`execution_reports` 表）
4. **Bybit 交易所**中有订单

---

**请先运行检查脚本，查看详细状态：**

```bash
./scripts/check_trade_execution.sh idem-83f85a847e574327a4ba0eac7311b35a
```
