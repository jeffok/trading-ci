# 下单机制说明

## 📋 下单方式

### LIVE 模式（实盘）

**默认方式**：**Market 订单（市价单）**

- **订单类型**：Market（市价单）
- **时间类型**：IOC（Immediate or Cancel，立即成交或取消）
- **特点**：立即以当前市场价格成交，保证成交速度

**可选方式**：**Limit 订单（限价单）**

- **配置**：设置 `EXECUTION_ENTRY_ORDER_TYPE=Limit`
- **订单类型**：Limit（限价单）
- **时间类型**：GTC（Good Till Cancel，直到取消）
- **价格**：使用 `entry_price`（收盘价）
- **特点**：
  - 如果未成交，系统会自动处理：
    - 超时未成交（默认 15 秒）→ 取消并重新定价（+5 bps）
    - 部分成交停滞（默认 20 秒）→ 取消剩余并重新定价
    - 最多重试 2 次
    - 如果重试失败，降级为 Market 订单

### PAPER/BACKTEST 模式（模拟）

- **订单类型**：Market（模拟）
- **特点**：立即成交，不调用交易所 API

---

## 🎯 触发下单的条件

### 完整流程

```
市场数据（bar_close）
  ↓
策略层检测（strategy-service）
  ↓
生成 trade_plan（如果满足条件）
  ↓
执行层接收（execution-service）
  ↓
风控检查（多个闸门）
  ↓
下单执行
```

### 阶段1：策略层触发条件（strategy-service）

**输入**：`stream:bar_close`（K 线收盘事件）

**必须满足的条件**：

1. **三段背离检测** ✅
   - MACD histogram 三段顶/底背离
   - 必须识别出三段结构（两次缩短 + 段落分隔）

2. **Vegas 同向强门槛** ✅（必须）
   - 做多（LONG）：Vegas 状态必须是 `Bullish`
   - 做空（SHORT）：Vegas 状态必须是 `Bearish`
   - 不满足则直接返回，不生成信号

3. **确认数门槛** ✅
   - 至少命中 `min_confirmations` 个确认项（默认 2 个）
   - 确认项包括：
     - `ENGULFING`：吞没形态
     - `RSI_DIV`：RSI 背离
     - `OBV_DIV`：OBV 背离
     - `FVG_PROXIMITY`：FVG 接近度

4. **时间框架限制** ✅
   - 只有 `auto_timeframes`（默认：1h, 4h, 1d）才会生成 `trade_plan`
   - 其他时间框架（如 15m, 30m, 8h）只生成 `signal`，不生成 `trade_plan`

**输出**：
- `stream:signal`：所有时间框架都会生成（用于监控）
- `stream:trade_plan`：仅自动下单周期生成（触发执行）

---

### 阶段2：执行层触发条件（execution-service）

**输入**：`stream:trade_plan`

**必须通过的风控闸门**：

#### 1. Kill Switch 检查 ✅
- **账户级 Kill Switch**：如果启用，拒绝所有新开仓
- **检查位置**：`is_kill_switch_on()`

#### 2. 交易计划生命周期检查 ✅
- **过期检查**：如果 `expires_at_ms` 已过期，拒绝执行
- **默认 TTL**：1 根 K 线（可配置 `TRADE_PLAN_TTL_BARS`）

#### 3. 风险熔断检查 ✅
- **风险状态检查**：如果 `risk_state` 中 `kill_switch`、`hard_halt` 或 `soft_halt` 为 true，拒绝执行

#### 4. 冷却期检查 ✅
- **检查条件**：如果 `cooldown_enabled=true`
- **规则**：同币种同方向在冷却期内不允许再次开仓
- **冷却时长**：根据时间框架配置（如 1h 对应 `COOLDOWN_BARS_1H`）

#### 5. 最大持仓数检查 ✅
- **检查条件**：`max_open_positions > 0`
- **规则**：如果当前 OPEN 持仓数 >= `max_open_positions`，拒绝执行
- **默认值**：3

#### 6. 持仓互斥检查 ✅
- **规则**：同一币种同一方向只能有一个持仓
- **优先级**：高时间框架可以关闭低时间框架的持仓（互斥升级）
- **时间框架优先级**：1d > 4h > 1h > 其他

#### 7. 仓位计算检查 ✅
- **计算**：根据 `risk_pct`、`equity`、`entry_price`、`stop_price` 计算仓位
- **检查**：如果计算出的 `qty_total <= 0`，拒绝执行

**全部通过后**：执行下单

---

## 📊 下单执行流程

### LIVE 模式下单流程

```
1. 计算仓位
   ↓
2. 创建持仓记录（positions 表）
   ↓
3. 下 ENTRY 订单（Market 或 Limit）
   ↓
4. 设置止损（set_trading_stop API）
   ↓
5. 创建 TP1 订单（Limit，reduce-only，40%）
   ↓
6. 创建 TP2 订单（Limit，reduce-only，40%）
   ↓
7. 记录订单到数据库（orders 表）
   ↓
8. 发布执行报告（execution_report）
```

### PAPER/BACKTEST 模式下单流程

```
1. 计算仓位
   ↓
2. 创建持仓记录（positions 表）
   ↓
3. 模拟 ENTRY 订单（立即成交）
   ↓
4. 创建 TP1 订单（仅记录，不实际下单）
   ↓
5. 创建 TP2 订单（仅记录，不实际下单）
   ↓
6. 记录订单到数据库（orders 表）
   ↓
7. 发布执行报告（execution_report）
   ↓
8. 等待 paper_sim 在 bar_close 时模拟撮合
```

---

## 🔍 监控和日志

### 查看交易计划

```bash
# 查看 Redis Streams 中的 trade_plan
redis-cli XREVRANGE stream:trade_plan + - COUNT 10

# 查看数据库中的 trade_plans
psql -U postgres -d trading-ci -c "
SELECT plan_id, symbol, timeframe, side, entry_price, primary_sl_price, status, created_at 
FROM trade_plans 
ORDER BY created_at DESC 
LIMIT 10;"
```

### 查看执行报告

```bash
# 查看执行报告
docker compose exec execution python -m scripts.trading_test_tool orders

# 查看 Redis Streams 中的执行报告
redis-cli XREVRANGE stream:execution_report + - COUNT 20
```

### 查看信号

```bash
# 查看数据库中的信号
psql -U postgres -d trading-ci -c "
SELECT signal_id, symbol, timeframe, bias, hit_count, hits, created_at 
FROM signals 
ORDER BY created_at DESC 
LIMIT 10;"
```

---

## ⚙️ 配置参数

### 关键环境变量

```bash
# 自动下单时间框架（只有这些时间框架会生成 trade_plan）
AUTO_TIMEFRAMES=1h,4h,1d

# 监控时间框架（只生成 signal，不生成 trade_plan）
MONITOR_TIMEFRAMES=15m,30m,8h

# 最小确认数（默认 2）
MIN_CONFIRMATIONS=2

# 入场订单类型（Market 或 Limit）
EXECUTION_ENTRY_ORDER_TYPE=Market

# Limit 订单超时时间（毫秒）
EXECUTION_ENTRY_TIMEOUT_MS=15000

# 最大持仓数
MAX_OPEN_POSITIONS=3

# 冷却期启用
COOLDOWN_ENABLED=true

# 风险百分比
RISK_PCT=0.005

# ========== 仓位控制（实际价值） ==========
# 最低下单金额（USDT）
MIN_ORDER_VALUE_USDT=10.0

# 最高下单金额（USDT）
MAX_ORDER_VALUE_USDT=10000.0

# 合约倍数（1-125）
LEVERAGE=1

# 保证金模式（isolated=逐仓，cross=全仓）
MARGIN_MODE=isolated
```

---

## 💰 仓位控制与资金管理

### 仓位计算方式

系统使用**实际价值（USDT）**来计算仓位，而不是简单的合约数量。

**计算公式**：
```
1. 风险金额 = equity * risk_pct
2. 单位风险 = abs(entry - stop)
3. 合约数量 = 风险金额 / 单位风险
4. 实际下单金额 = (合约数量 * 入场价格) / 杠杆倍数
5. 应用最低/最高金额限制
6. 取整和最小值校验
```

**实际价值说明**：
- 实际价值 = (合约数量 * 入场价格) / 杠杆倍数
- 这是实际占用的保证金金额，不是合约名义价值
- 例如：0.1 BTC @ 50000 USDT，10倍杠杆 = (0.1 * 50000) / 10 = 500 USDT

### 金额限制

系统会自动应用最低/最高金额限制：

- **低于最低金额**：自动调整为 `MIN_ORDER_VALUE_USDT`
- **超过最高金额**：自动调整为 `MAX_ORDER_VALUE_USDT`
- **调整后仍不符合要求**：拒绝订单并发送错误报告

### 逐仓 vs 全仓模式

- **逐仓（isolated）**：
  - 每个持仓独立保证金
  - 风险隔离，推荐使用
  - 需要设置杠杆倍数

- **全仓（cross）**：
  - 所有持仓共享保证金
  - 风险更高，不推荐
  - 杠杆倍数设为 0

系统会在下单前自动设置逐仓/全仓模式和杠杆倍数。

### 杠杆倍数

- **杠杆越高**：所需保证金越少，但风险越大
- **建议设置**：1-10倍（较安全）
- **最大支持**：125倍（Bybit 限制）

### 计算示例

#### 示例1：逐仓模式，10倍杠杆

**输入**：
- equity = 10000 USDT
- risk_pct = 0.005 (0.5%)
- entry = 50000 USDT
- stop = 49000 USDT
- leverage = 10
- min_order_value_usdt = 10 USDT
- max_order_value_usdt = 1000 USDT

**计算**：
1. 风险金额 = 10000 * 0.005 = 50 USDT
2. 单位风险 = |50000 - 49000| = 1000 USDT
3. 合约数量 = 50 / 1000 = 0.05 BTC
4. 实际下单金额 = (0.05 * 50000) / 10 = 250 USDT
5. ✅ 在范围内（10 ≤ 250 ≤ 1000）

#### 示例2：低于最低金额

**输入**：
- 计算出的 order_value_usdt = 5 USDT
- min_order_value_usdt = 10 USDT

**处理**：
- 自动调整为 10 USDT
- 重新计算 qty = (10 * 10) / 50000 = 0.002 BTC

#### 示例3：超过最高金额

**输入**：
- 计算出的 order_value_usdt = 2000 USDT
- max_order_value_usdt = 1000 USDT

**处理**：
- 自动调整为 1000 USDT
- 重新计算 qty = (1000 * 10) / 50000 = 0.2 BTC

---

## 📝 示例场景

### 场景1：正常触发下单

1. **市场数据**：BTCUSDT 1h K 线收盘
2. **策略检测**：
   - ✅ 检测到三段背离
   - ✅ Vegas 状态 = Bullish（做多方向）
   - ✅ 命中 2 个确认项（ENGULFING + RSI_DIV）
   - ✅ 时间框架 = 1h（在 auto_timeframes 中）
3. **生成 trade_plan**：发布到 `stream:trade_plan`
4. **执行层检查**：
   - ✅ Kill Switch：未启用
   - ✅ 交易计划：未过期
   - ✅ 风险熔断：未触发
   - ✅ 冷却期：无
   - ✅ 最大持仓：当前 2 个 < 3
   - ✅ 持仓互斥：无冲突
   - ✅ 仓位计算：成功
5. **执行下单**：Market 订单，立即成交

### 场景2：被风控拦截

1. **策略检测**：满足所有条件，生成 `trade_plan`
2. **执行层检查**：
   - ❌ 最大持仓：当前 3 个 >= 3
3. **拒绝执行**：发布 `REJECTED` 执行报告，原因：`MAX_POSITIONS_BLOCKED`

### 场景3：冷却期拦截

1. **策略检测**：满足所有条件，生成 `trade_plan`
2. **执行层检查**：
   - ❌ 冷却期：BTCUSDT LONG 方向在冷却期内
3. **拒绝执行**：发布 `REJECTED` 执行报告，原因：`COOLDOWN_BLOCKED`

---

## ⚠️ 重要说明

1. **收盘确认**：只有在 K 线收盘时才会触发下单（通过 `bar_close` 事件）
2. **幂等性**：使用 `idempotency_key` 保证不会重复下单
3. **自动执行**：满足条件后自动下单，无需手动干预
4. **风控优先**：所有风控闸门必须全部通过才能下单
5. **时间框架限制**：只有配置的 `auto_timeframes` 才会自动下单

---

## 📚 相关文档

- [STOP_LOSS_TAKE_PROFIT_RULES.md](./STOP_LOSS_TAKE_PROFIT_RULES.md) - 止损/止盈规则
- [SYNC_MECHANISM.md](./SYNC_MECHANISM.md) - 订单与持仓同步机制
- [TELEGRAM_NOTIFICATIONS.md](./TELEGRAM_NOTIFICATIONS.md) - Telegram 通知说明
- [services/strategy/README.md](./services/strategy/README.md) - 策略服务说明
- [services/execution/README.md](./services/execution/README.md) - 执行服务说明
