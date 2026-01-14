# Telegram 通知说明

## 📋 概述

系统会自动将**重要事件**发送到 Telegram，包括下单、止损、止盈等关键操作。

**触发条件**：
- 只有 `IMPORTANT`、`CRITICAL`、`EMERGENCY` 级别的消息才会发送
- 需要配置 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`

---

## 🎯 下单相关通知

### 1. 开仓成交（FILLED）

**触发时机**：ENTRY 订单成交时

**消息样式**：
```
📗 开仓成交：BTCUSDT 多
数量：0.0100
开仓均价：95449.2000
周期：1h
#plan_id abc123def456
```

**说明**：
- 📗 绿色图标表示开仓
- 显示交易对、方向（多/空）、数量、均价
- 包含时间框架和 plan_id

---

### 2. 订单已提交（ORDER_SUBMITTED）

**触发时机**：订单提交到交易所时（LIVE 模式）

**消息样式**：
```
🧾 订单已提交：BTCUSDT 多
数量：0.0100
价格：95449.2000
order_id：abc123def456
```

**说明**：
- 🧾 表示订单提交
- 显示订单基本信息

---

### 3. 订单被拒绝（ORDER_REJECTED）

**触发时机**：订单被拒绝时

**消息样式**：
```
❌ 执行异常：BTCUSDT 多
status：ORDER_REJECTED
原因：position_mutex_blocked
#plan_id abc123def456
```

**常见拒绝原因**：
- `position_mutex_blocked`：同币种同向持仓互斥
- `MAX_POSITIONS_BLOCKED`：超过最大持仓数
- `COOLDOWN_BLOCKED`：冷却期内
- `KILL_SWITCH_ON`：账户熔断已启用
- `RISK_CIRCUIT_HALT`：风险熔断触发

---

## 🛑 止损相关通知

### 1. 初始止损触发（PRIMARY_SL_HIT）

**触发时机**：初始止损被触发时

**消息样式**：
```
🛑 止损成交
BTCUSDT 多
数量：0.0100
开仓均价：95449.2000
平仓均价：93540.2200
🔴 本次亏损：19.0898 USDT
当前连续亏损次数：1
原因：PRIMARY_SL_HIT
#plan_id abc123def456
```

**说明**：
- 🛑 红色图标表示止损
- 显示盈亏金额（USDT）
- 显示连续亏损次数
- 包含平仓原因

---

### 2. 二级止损/规则退出（SECONDARY_SL_EXIT）

**触发时机**：次日规则触发或 Runner 止损触发时

**消息样式**：
```
🟠 二级止损/规则退出
BTCUSDT 多
数量：0.0100
开仓均价：95449.2000
平仓均价：94000.0000
🔴 本次亏损：14.4920 USDT
当前连续亏损次数：2
原因：secondary_rule
#plan_id abc123def456
```

**说明**：
- 🟠 橙色图标表示二级退出
- 同样显示盈亏和连续亏损次数

---

### 3. Runner 止损更新（RUNNER_SL_UPDATED）

**触发时机**：TP2 成交后，Runner 止损价格更新时

**消息样式**：
```
🟡 Runner 止损更新：BTCUSDT 多
新止损：96000.0000
```

**说明**：
- 🟡 黄色图标表示更新
- 显示新的止损价格
- 只更新，不触发平仓

---

## 🎯 止盈相关通知

### 1. 止盈成交（TP_HIT）

**触发时机**：TP1 或 TP2 成交时

**消息样式**：
```
🎯 止盈成交
BTCUSDT 多
数量：0.0100
开仓均价：95449.2000
平仓均价：105000.0000
🟢 本次盈利：95.5080 USDT
当前连续亏损次数：0
原因：TP_HIT
#plan_id abc123def456
```

**说明**：
- 🎯 表示止盈
- 🟢 绿色表示盈利
- 显示盈利金额
- 连续亏损次数会重置为 0

---

### 2. 平仓成交（POSITION_CLOSED）

**触发时机**：持仓完全平仓时（包括所有 TP 和 Runner）

**消息样式**：
```
📘 平仓成交：BTCUSDT 多
数量：0.0100
开仓均价：95449.2000
平仓均价：105000.0000
🟢 本次盈利：95.5080 USDT
当前连续亏损次数：0
原因：POSITION_CLOSED
#plan_id abc123def456
```

**说明**：
- 📘 蓝色图标表示平仓
- 显示最终盈亏
- 包含连续亏损统计

---

## ⚠️ 风险事件通知

### 1. 账户熔断（KILL_SWITCH_ON）

**消息样式**：
```
🛑 账户熔断（Kill Switch）已开启：BTCUSDT
原因：daily_loss_limit_exceeded
```

---

### 2. 最大持仓限制（MAX_POSITIONS_BLOCKED）

**消息样式**：
```
🚫 最大持仓限制触发：BTCUSDT
当前/上限：3/3
```

---

### 3. 持仓互斥阻断（POSITION_MUTEX_BLOCKED）

**消息样式**：
```
🔒 同币种同向互斥阻断：BTCUSDT
incoming：1h
existing：4h
existing_idem：xyz789abc123
```

---

### 4. 冷却期阻断（COOLDOWN_BLOCKED）

**消息样式**：
```
⏸️ 冷却中：BTCUSDT
周期：1h
until_ts_ms：1768400519060
原因：STOP_LOSS
```

---

### 5. API 限频（RATE_LIMIT）

**消息样式**：
```
⏳ Bybit API 限频触发：BTCUSDT
retCode：10006
retMsg：Too many requests
endpoint：/v5/order/create
建议等待：5000 ms
建议：Bybit 10006 限频；逐交易对监控请优先使用 public API（WS/market），私有接口集中调用并降频。
```

---

### 6. 信号过期（SIGNAL_EXPIRED）

**消息样式**：
```
⌛ 信号/计划已过期：BTCUSDT
expires_at_ms：1768400519060
now_ms：1768400520000
plan_id：abc123def456
```

---

### 7. 订单超时（ORDER_TIMEOUT）

**消息样式**：
```
⏱️ 订单超时：BTCUSDT
purpose：ENTRY
order_id：abc123def456
age_ms：20000
action：CANCEL_AND_RETRY
```

---

### 8. 订单重试（ORDER_RETRY）

**消息样式**：
```
🔁 订单重试：BTCUSDT
purpose：ENTRY
order_id：abc123def456
attempt：2
new_price：95454.2000
```

---

### 9. 降级市价（ORDER_FALLBACK_MARKET）

**消息样式**：
```
🟠 降级市价：BTCUSDT
purpose：ENTRY
order_id：abc123def456
remaining_qty：0.0050
```

---

### 10. 订单撤销（ORDER_CANCELLED）

**消息样式**：
```
✅ 订单撤销：BTCUSDT
purpose：TP1
order_id：abc123def456
reason：position_close:forced_exit
```

---

### 11. 订单部分成交（ORDER_PARTIAL_FILL）

**消息样式**：
```
🧩 订单部分成交：BTCUSDT
order_id：abc123def456
已成/总量：0.0050/0.0100
```

---

## 📊 数据质量事件通知

### 1. 行情缺口（DATA_GAP）

**消息样式**：
```
🧯 行情缺口：BTCUSDT
周期：1h
close_time_ms：1768400519060
lag_ms：300000
missing_bars：5
```

---

### 2. 行情延迟（DATA_LAG）

**消息样式**：
```
⏱️ 行情延迟：BTCUSDT
周期：1h
close_time_ms：1768400519060
lag_ms：120000
```

---

### 3. Bar 修订/重复（BAR_DUPLICATE）

**消息样式**：
```
🧩 Bar 修订/重复：BTCUSDT
周期：1h
close_time_ms：1768400519060
diffs：close:95449.2→95450.0, volume:100.5→101.2
```

---

### 4. 异常跳变（PRICE_JUMP）

**消息样式**：
```
📈 异常跳变：BTCUSDT
周期：1h
jump：5.23%
阈值：3.00%
```

---

### 5. 成交量异常（VOLUME_ANOMALY）

**消息样式**：
```
📊 成交量异常：BTCUSDT
周期：1h
倍数：3.45x
```

---

### 6. 仓位一致性漂移（CONSISTENCY_DRIFT）

**消息样式**：
```
🧭 仓位一致性漂移：BTCUSDT
漂移比例：5.23%
阈值：3.00%
本地/WS：0.0100/0.0095
idempotency_key：abc123def456
```

---

## ⚙️ 配置

### 环境变量

```bash
# Telegram Bot Token（从 @BotFather 获取）
TELEGRAM_BOT_TOKEN=your_bot_token

# Telegram Chat ID（从 @userinfobot 获取）
TELEGRAM_CHAT_ID=your_chat_id
```

### 通知级别

只有以下级别的消息才会发送到 Telegram：
- `IMPORTANT`：重要事件（下单、止损、止盈等）
- `CRITICAL`：关键事件
- `EMERGENCY`：紧急事件

`INFO` 级别的消息不会发送，只记录到日志。

---

## 🔍 消息特点

### 1. 中文友好
- 所有消息使用中文
- 方向显示为"多"或"空"
- 金额显示为 USDT

### 2. 图标标识
- 📗 开仓（绿色）
- 📘 平仓（蓝色）
- 🛑 止损（红色）
- 🎯 止盈（绿色）
- ❌ 异常（红色）
- ⚠️ 警告（黄色）

### 3. 详细信息
- 包含交易对、方向、数量、价格
- 显示盈亏金额（USDT）
- 显示连续亏损次数
- 包含 plan_id 用于追踪

### 4. 幂等性
- 使用 `event_id` 作为 `notification_id`
- 避免重复发送
- 失败自动重试（指数退避）

---

## 📝 完整示例

### 完整交易流程的通知示例

```
1. 开仓成交
📗 开仓成交：BTCUSDT 多
数量：0.0100
开仓均价：95449.2000
周期：1h
#plan_id abc123def456

2. TP1 成交（部分平仓，不发送通知）
（TP1/TP2 部分平仓不单独通知，只在最终平仓时通知）

3. TP2 成交（部分平仓，不发送通知）

4. Runner 止损更新
🟡 Runner 止损更新：BTCUSDT 多
新止损：96000.0000

5. 最终平仓
📘 平仓成交：BTCUSDT 多
数量：0.0100
开仓均价：95449.2000
平仓均价：105000.0000
🟢 本次盈利：95.5080 USDT
当前连续亏损次数：0
原因：POSITION_CLOSED
#plan_id abc123def456
```

---

## ⚠️ 注意事项

1. **部分平仓不通知**：TP1/TP2 部分平仓不会单独发送通知，只在最终完全平仓时发送
2. **重试机制**：发送失败会自动重试，使用指数退避策略
3. **幂等性**：相同事件不会重复发送
4. **级别过滤**：只有 IMPORTANT/CRITICAL/EMERGENCY 级别才会发送

---

## 📚 相关文档

- [ORDER_PLACEMENT_MECHANISM.md](./ORDER_PLACEMENT_MECHANISM.md) - 下单机制说明
- [STOP_LOSS_TAKE_PROFIT_RULES.md](./STOP_LOSS_TAKE_PROFIT_RULES.md) - 止损/止盈规则
- [services/notifier/README.md](./services/notifier/README.md) - 通知服务说明
