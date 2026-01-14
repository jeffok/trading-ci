# 同币种同向互斥机制说明

## 📋 问题描述

你收到的通知显示：
```
❌ 执行异常：BTCUSDT
status：ORDER_REJECTED
原因：position_mutex_blocked

🔒 同币种同向互斥阻断：BTCUSDT
incoming：15m
existing：15m
```

## ✅ 这是正常的风控行为

这是系统的**同币种同向互斥保护机制**，用于防止：
- 同一交易对（BTCUSDT）同时持有多个同方向（都是做多或都是做空）的仓位
- 避免过度暴露风险

## 🔍 工作原理

### 时间框架优先级

系统按以下优先级排序：

| 时间框架 | 优先级 | 说明 |
|---------|--------|------|
| 1d      | 3      | 最高优先级 |
| 4h      | 2      | 高优先级 |
| 1h      | 1      | 中等优先级 |
| 15m/30m/8h | 0   | 最低优先级（监控周期） |

### 判断逻辑

1. **检查是否存在同币种同向持仓**
   - 查询数据库中是否有 `status='OPEN'` 且 `symbol` 和 `side` 相同的持仓

2. **比较优先级**
   - 如果 incoming 优先级 **≤** existing 优先级 → **阻止**（BLOCK）
   - 如果 incoming 优先级 **>** existing 优先级 → 根据配置决定行为

3. **处理策略**（当 incoming 优先级更高时）

   配置项：`POSITION_MUTEX_UPGRADE_ACTION`
   
   - `CLOSE_LOWER_AND_OPEN`（默认）：先强制平掉低优先级仓位，再执行新开仓
   - `BLOCK`：直接拒绝，不替换

## 📊 你的情况分析

```
existing: BTCUSDT 15m (优先级 0)
incoming: BTCUSDT 15m (优先级 0)
结果: incoming (0) ≤ existing (0) → 被阻止 ✅
```

**原因**：两个都是 15m 时间框架，优先级相同，系统选择保护现有持仓。

## 🔧 解决方案

### 方案1：等待现有持仓关闭（推荐）

等待现有持仓（`idem-d309b7af7794472293111fb1b6aa4d23`）：
- 触发止损（SL）
- 触发止盈（TP）
- 触发次日规则退出
- 手动平仓

然后新的 trade_plan 就可以执行了。

### 方案2：查看当前持仓状态

```bash
# 查询当前持仓
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool

# 或直接查询数据库
psql -U postgres -d trading-ci -c "
SELECT position_id, symbol, timeframe, side, qty_total, entry_price, status, opened_at_ms 
FROM positions 
WHERE status='OPEN' 
ORDER BY opened_at_ms DESC;"
```

### 方案3：调整配置（如果需要）

如果你想允许同优先级替换，可以修改配置：

```bash
# .env 文件中设置
POSITION_MUTEX_UPGRADE_ACTION=CLOSE_LOWER_AND_OPEN

# 但注意：这个配置只在 incoming 优先级更高时生效
# 对于同优先级（如 15m vs 15m），仍然会被阻止
```

**⚠️ 警告**：修改配置需要谨慎，可能导致风险暴露增加。

### 方案4：手动平仓（紧急情况）

如果需要立即平掉现有持仓：

```bash
# 1. 查询持仓详情
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool

# 2. 如果使用 LIVE 模式，可以在 Bybit 交易所手动平仓
# 3. 系统会在下次 position_sync 时检测到并更新状态
```

## 📈 优先级升级示例

### 示例1：允许替换
```
existing: BTCUSDT 15m (优先级 0)
incoming: BTCUSDT 1h (优先级 1)
结果: incoming (1) > existing (0) → 先平掉 15m，再开 1h ✅
```

### 示例2：允许替换
```
existing: BTCUSDT 1h (优先级 1)
incoming: BTCUSDT 4h (优先级 2)
结果: incoming (2) > existing (1) → 先平掉 1h，再开 4h ✅
```

### 示例3：被阻止
```
existing: BTCUSDT 1h (优先级 1)
incoming: BTCUSDT 15m (优先级 0)
结果: incoming (0) ≤ existing (1) → 被阻止 ❌
```

## 🔍 查询相关配置

```bash
# 查看当前配置
curl http://localhost:8000/v1/config | python3 -m json.tool | grep -i "POSITION_MUTEX"

# 应该看到：
# "POSITION_MUTEX_UPGRADE_ACTION": "CLOSE_LOWER_AND_OPEN"
```

## 📝 相关环境变量

在 `.env` 文件中：

```bash
# 同币种同向持仓互斥升级动作
# 可选值：BLOCK（拒绝）/ CLOSE_LOWER_AND_OPEN（先平低优先级再开仓）
POSITION_MUTEX_UPGRADE_ACTION=CLOSE_LOWER_AND_OPEN
```

## 💡 最佳实践

1. **理解这是保护机制**：避免过度暴露风险
2. **等待自然退出**：让现有持仓按策略自然退出
3. **监控持仓状态**：定期查看当前持仓
4. **合理设置优先级**：理解时间框架优先级规则

## 🆘 如果需要帮助

如果这个行为不符合你的预期，可以：

1. **查看完整日志**：
   ```bash
   docker compose logs execution | grep -i "position_mutex" | tail -20
   ```

2. **查看风险事件**：
   ```bash
   TRADE_DATE=$(date +%Y-%m-%d)
   curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool
   ```

3. **检查现有持仓**：
   ```bash
   curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool
   ```

---

**总结**：这是正常的风控行为，系统正在保护你避免同时持有多个同方向仓位。等待现有持仓自然退出后，新的交易计划就可以执行了。
