# 订单与持仓同步机制说明

本文档详细说明整个交易系统中订单和持仓与 Bybit 交易所的同步机制。

## 概述

系统采用**多层次的同步机制**，确保数据库状态与交易所状态保持一致：

1. **WebSocket 实时同步**（主要机制）
2. **REST API 轮询兜底**（备用机制）
3. **定期对账检查**（一致性验证）
4. **手动同步工具**（紧急修复）

---

## 1. 订单同步机制

### 1.1 WebSocket 实时同步 (`ws_private_ingest.py`)

**触发条件**：
- `BYBIT_PRIVATE_WS_ENABLED=true`
- `EXECUTION_MODE=LIVE`
- 已配置 `BYBIT_API_KEY` 和 `BYBIT_API_SECRET`

**工作原理**：
- 订阅 Bybit private WebSocket：`order`, `execution`
- 实时接收订单状态更新（Filled, Cancelled, PartiallyFilled 等）
- 自动更新 `orders` 表的 `status` 字段
- 记录成交详情到 `fills` 表
- 发布 `execution_report` 事件到 Redis Streams

**更新内容**：
- 订单状态 (`status`)
- 成交数量 (`filled_qty`, `cum_exec_qty`)
- 成交均价 (`avg_price`)
- WebSocket 原始数据 (`payload.ws_payload`)

**优势**：
- 实时性强（毫秒级延迟）
- 减少 REST API 调用
- 自动处理订单状态变化

### 1.2 REST API 轮询兜底 (`reconcile.py`)

**触发条件**：
- 每 5 秒运行一次（`reconcile_open_orders_poll_interval_sec`）
- 仅在 LIVE 模式下运行
- 如果启用了 WS，会减少轮询频率（避免重复）

**工作原理**：
- 调用 `open_orders` API 查询所有订单状态
- 检查 TP1/TP2 是否成交
- 检测订单超时和部分成交
- 更新订单状态到数据库

**检查内容**：
- TP1/TP2 成交状态
- 订单超时（`order_poll_timeout_sec`，默认 20 秒）
- 部分成交停滞（`execution_entry_partial_fill_timeout_ms`）

**优势**：
- 作为 WS 的兜底机制
- 可以检测到 WS 遗漏的更新
- 处理订单异常情况

### 1.3 订单异常处理 (`order_manager.py`)

**触发条件**：
- ENTRY 订单类型为 Limit
- 订单超时或部分成交停滞

**处理流程**：
1. **超时未成交**：
   - 取消订单
   - 重新定价（`execution_entry_reprice_bps`，默认 5 bps）
   - 重试下单（最多 `execution_entry_max_retries` 次）
   - 如果重试失败，降级为 Market 订单

2. **部分成交停滞**：
   - 取消剩余订单
   - 重新定价剩余数量
   - 重试或降级为 Market

**配置参数**：
- `execution_entry_timeout_ms`: 超时时间（默认 15000ms）
- `execution_entry_partial_fill_timeout_ms`: 部分成交停滞时间（默认 20000ms）
- `execution_entry_max_retries`: 最大重试次数（默认 2）
- `execution_entry_reprice_bps`: 重新定价基点（默认 5）
- `execution_entry_fallback_market`: 是否降级为 Market（默认 true）

---

## 2. 持仓同步机制

### 2.1 WebSocket 实时同步 (`ws_private_ingest.py`)

**工作原理**：
- 订阅 `position` 主题
- 接收持仓快照更新
- 更新 `positions` 表的 `meta.ws_position` 字段
- 记录到 `ws_events` 表（审计）

**更新内容**：
- 持仓数量 (`size`)
- 持仓方向 (`side`)
- 持仓均价 (`avgPrice`)
- 标记价格 (`markPrice`)
- 未实现盈亏 (`unrealisedPnl`)

### 2.2 REST API 定期同步 (`position_sync.py`)

**触发条件**：
- 每 10 秒运行一次（`run_position_sync_loop`）
- 仅在 LIVE 模式下运行

**工作原理**：
1. 查询数据库中所有 `status='OPEN'` 的持仓
2. 调用 `position_list` API 查询交易所实际持仓
3. **关键检查**：如果交易所 `size=0`，但数据库是 `OPEN`，则：
   - 更新数据库状态为 `CLOSED`
   - 设置 `exit_reason`：
     - 如果 TP1 未成交 → `STOP_LOSS`（触发冷却）
     - 否则 → `EXCHANGE_CLOSED`
   - 发布 `execution_report` 事件
   - 如果启用冷却，写入 `cooldowns` 表

**检测场景**：
- ✅ 手动平仓（交易所 size=0，数据库 OPEN）
- ✅ 止损触发（交易所 size=0，数据库 OPEN）
- ✅ 止盈触发（交易所 size=0，数据库 OPEN）
- ✅ 强制平仓（交易所 size=0，数据库 OPEN）

**优势**：
- 自动检测手动平仓
- 自动修复数据不一致
- 触发冷却机制（防止重复开仓）

### 2.3 一致性漂移检测 (`reconcile.py`)

**触发条件**：
- `CONSISTENCY_DRIFT_ENABLED=true`（默认启用）
- 每 5 秒运行一次

**工作原理**：
- 比较 WebSocket 持仓快照 (`meta.ws_position.size`) 与数据库持仓 (`qty_total`)
- 如果漂移超过阈值（`consistency_drift_threshold_pct`，默认 10%），则：
  - 发布 `CONSISTENCY_DRIFT` 风险事件
  - 记录到 `risk_events` 表
  - 在窗口期内（`consistency_drift_window_ms`，默认 5 分钟）只报警一次

**检测内容**：
- 持仓数量不一致
- 持仓方向不一致（通过 WS 快照）

---

## 3. 手动同步工具 (`trading_test_tool.py`)

### 3.1 同步命令 (`sync`)

**用途**：
- 手动触发持仓同步检查
- 修复数据不一致
- 诊断同步问题

**使用方法**：
```bash
# 检查模式（不修改数据库）
docker compose exec execution python -m scripts.trading_test_tool sync --dry-run

# 实际执行同步
docker compose exec execution python -m scripts.trading_test_tool sync
```

**工作流程**：
1. 查询数据库中所有 OPEN 持仓
2. 通过 Bybit API 查询交易所实际持仓
3. 对比状态：
   - 交易所 size=0，数据库 OPEN → 更新为 CLOSED
   - 交易所有持仓 → 状态一致，跳过
4. 显示同步结果

### 3.2 诊断命令 (`diagnose`)

**用途**：
- 诊断下单失败原因
- 检查持仓状态
- 检查账户余额
- 检查风险控制规则

**使用方法**：
```bash
docker compose exec execution python -m scripts.trading_test_tool diagnose \
  --symbol BTCUSDT \
  --side BUY
```

---

## 4. 同步机制总结

### 4.1 订单同步流程

```
下单 → WebSocket 实时更新 → REST 轮询兜底 → 异常处理
  ↓           ↓                    ↓              ↓
数据库     数据库更新          状态检查        重试/降级
```

### 4.2 持仓同步流程

```
开仓 → WebSocket 实时更新 → REST 定期检查 → 一致性验证
  ↓           ↓                    ↓              ↓
数据库     快照更新           手动平仓检测     漂移检测
```

### 4.3 手动平仓检测流程

```
手动平仓（交易所）
    ↓
position_sync 检测到 size=0
    ↓
更新数据库 status=CLOSED
    ↓
设置 exit_reason=EXCHANGE_CLOSED 或 STOP_LOSS
    ↓
发布 execution_report
    ↓
触发冷却（如果适用）
```

---

## 5. 配置参数

### 5.1 WebSocket 配置

```env
# 启用私有 WebSocket
BYBIT_PRIVATE_WS_ENABLED=true

# WebSocket URL（默认）
BYBIT_PRIVATE_WS_URL=wss://stream.bybit.com/v5/private

# 订阅主题
BYBIT_PRIVATE_WS_SUBSCRIPTIONS=order,execution,position,wallet
```

### 5.2 轮询配置

```env
# 订单轮询间隔（秒）
RECONCILE_OPEN_ORDERS_POLL_INTERVAL_SEC=5.0

# 持仓同步间隔（秒，代码中硬编码为 10 秒）
# position_sync.py: await asyncio.sleep(10.0)

# 一致性漂移阈值（百分比）
CONSISTENCY_DRIFT_THRESHOLD_PCT=0.10

# 一致性漂移窗口（毫秒）
CONSISTENCY_DRIFT_WINDOW_MS=300000
```

### 5.3 订单超时配置

```env
# 订单超时时间（秒）
ORDER_POLL_TIMEOUT_SEC=20.0

# 订单超时告警窗口（毫秒）
ORDER_TIMEOUT_ALERT_WINDOW_MS=60000

# ENTRY 订单超时（毫秒）
EXECUTION_ENTRY_TIMEOUT_MS=15000

# 部分成交停滞时间（毫秒）
EXECUTION_ENTRY_PARTIAL_FILL_TIMEOUT_MS=20000
```

---

## 6. 监控和告警

### 6.1 风险事件类型

系统会发布以下风险事件：

- `WS_RECONNECT`: WebSocket 重连
- `RATE_LIMIT`: API 限频
- `ORDER_TIMEOUT`: 订单超时
- `ORDER_PARTIAL_FILL`: 部分成交
- `CONSISTENCY_DRIFT`: 一致性漂移
- `POSITION_SYNC_FAILED`: 持仓同步失败

### 6.2 执行报告类型

系统会发布以下执行报告：

- `ENTRY_SUBMITTED`: 入场订单已提交
- `ENTRY_FILLED`: 入场订单已成交
- `TP_FILLED`: 止盈订单已成交
- `SL_UPDATE`: 止损价格更新
- `POSITION_CLOSED`: 持仓已关闭
- `ORDER_REJECTED`: 订单被拒绝

---

## 7. 最佳实践

### 7.1 确保同步机制正常工作

1. **启用 WebSocket**：
   ```env
   BYBIT_PRIVATE_WS_ENABLED=true
   ```

2. **定期检查同步状态**：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool sync --dry-run
   ```

3. **监控风险事件**：
   ```bash
   docker compose logs execution | grep -i "risk_event\|consistency\|sync"
   ```

### 7.2 手动平仓后的处理

如果手动在交易所平仓：

1. **自动检测**（推荐）：
   - `position_sync` 会在 10 秒内自动检测并更新

2. **手动同步**（如果需要立即修复）：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool sync
   ```

3. **验证结果**：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool positions
   ```

### 7.3 故障排查

如果发现数据不一致：

1. **运行诊断**：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool diagnose \
     --symbol BTCUSDT \
     --side BUY
   ```

2. **检查日志**：
   ```bash
   docker compose logs execution | tail -100
   ```

3. **检查 WebSocket 连接**：
   ```bash
   docker compose logs execution | grep -i "ws\|websocket"
   ```

4. **手动同步**：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool sync
   ```

---

## 8. 总结

系统通过**多层次、多机制的同步策略**，确保订单和持仓状态与交易所保持一致：

1. ✅ **WebSocket 实时同步**：毫秒级延迟，自动更新
2. ✅ **REST API 轮询兜底**：确保不遗漏更新
3. ✅ **定期对账检查**：验证一致性
4. ✅ **手动同步工具**：紧急修复和诊断

**关键特性**：
- 自动检测手动平仓
- 自动修复数据不一致
- 实时状态更新
- 完善的监控和告警

**建议**：
- 启用 WebSocket 以获得最佳性能
- 定期运行 `sync --dry-run` 检查状态
- 监控风险事件和执行报告
- 在手动平仓后等待自动同步（或手动触发）
