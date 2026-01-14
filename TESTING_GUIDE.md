# 完整下单流程测试指南

本文档提供完整的下单流程测试步骤，涵盖从环境准备到结果验证的全过程。

## 📋 目录

1. [测试流程概览](#测试流程概览)
2. [环境准备](#环境准备)
3. [测试方式](#测试方式)
4. [结果验证](#结果验证)
5. [常见问题排查](#常见问题排查)

---

## 🎯 测试流程概览

完整的下单流程涉及以下服务链路：

```
市场数据 → 策略引擎 → 执行服务 → 通知服务
   ↓           ↓           ↓           ↓
bar_close → signal → trade_plan → execution_report
           (监控)    (自动周期)    (订单/持仓)
```

### 关键事件流

1. **marketdata-service**: 订阅 Bybit WebSocket，接收 K 线数据
   - 输出：`stream:bar_close` 事件

2. **strategy-service**: 消费 `bar_close`，计算指标，识别信号
   - 输出：`stream:signal`（监控周期）、`stream:trade_plan`（自动周期）

3. **execution-service**: 消费 `trade_plan`，执行下单
   - 输出：`stream:execution_report`（订单状态）、`stream:risk_event`（风险事件）

4. **notifier-service**: 消费 `execution_report` 和 `risk_event`
   - 输出：日志 + Telegram 通知（可选）

5. **api-service**: 提供查询接口，用于验证结果

---

## 🛠️ 环境准备

### 1. 准备外部依赖

#### PostgreSQL 数据库

```bash
# 创建数据库（注意：数据库名包含 "-" 需要用双引号）
psql -U postgres -c 'CREATE DATABASE "trading-ci";'

# 验证连接
psql -U postgres -d trading-ci -c "SELECT version();"
```

#### Redis

```bash
# 启动 Redis（如果使用 Docker）
docker run -d --name redis-trading -p 6379:6379 redis:7-alpine

# 验证连接
redis-cli ping
# 应返回: PONG
```

### 2. 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，至少配置以下必填项：
```

**必填配置项：**

```bash
# 数据库和 Redis
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trading-ci
REDIS_URL=redis://localhost:6379/0

# 执行模式（测试时使用 PAPER，实盘使用 LIVE）
EXECUTION_MODE=PAPER

# 回测/模拟盘初始资金
BACKTEST_EQUITY=10000

# 市场数据配置
MARKETDATA_SYMBOLS=BTCUSDT
MARKETDATA_TIMEFRAMES=15m,30m,1h,4h,8h,1d

# 如果测试实盘下单，需要配置 Bybit API（⚠️ 谨慎使用）
# BYBIT_API_KEY=your_api_key
# BYBIT_API_SECRET=your_api_secret
# EXECUTION_MODE=LIVE
```

### 3. 初始化数据库和 Redis Streams

```bash
# 方式1：手动初始化（推荐用于本地测试）
python -m scripts.init_db
python -m scripts.init_streams

# 方式2：使用 Docker 启动时会自动初始化（如果 SKIP_DB_MIGRATIONS=0）
```

---

## 🧪 测试方式

### 方式1：快速测试（Smoke Test）- 推荐用于快速验证

**适用场景**：快速验证执行服务是否正常工作，不依赖市场数据。

#### 步骤：

1. **启动所有服务**

```bash
# 使用 Docker Compose（推荐）
docker compose up --build

# 或单独启动服务（本地开发）
python -m services.marketdata.main &
python -m services.strategy.main &
python -m services.execution.main &
python -m services.notifier.main &
python -m services.api.main &
```

2. **等待服务启动（约 10-15 秒）**

```bash
# 检查服务健康状态
curl http://localhost:8000/health  # api-service
curl http://localhost:8001/health  # marketdata-service
curl http://localhost:8002/health  # strategy-service
curl http://localhost:8003/health  # execution-service
curl http://localhost:8004/health  # notifier-service
```

3. **运行 Smoke Test**

```bash
# 基础健康检查
python scripts/e2e_smoke_test.py

# 注入 trade_plan 并等待执行（推荐）
python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 10

# 自定义参数
SMOKE_SYMBOL=BTCUSDT \
SMOKE_TIMEFRAME=15m \
SMOKE_SIDE=BUY \
SMOKE_ENTRY_PRICE=30000 \
SMOKE_SL_PRICE=29000 \
python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 15
```

4. **查看测试结果**

脚本会自动输出：
- 服务健康状态
- Redis Streams 状态
- 注入的 trade_plan 信息
- 生成的 execution_report 和 risk_event

---

### 方式2：完整流程测试（Replay Backtest）- 推荐用于完整验证

**适用场景**：测试完整的市场数据 → 信号 → 下单流程，使用历史数据回放。

#### 步骤：

1. **启动服务（PAPER 模式）**

```bash
# 确保 .env 中配置：
EXECUTION_MODE=PAPER
BACKTEST_EQUITY=10000

# 启动服务
docker compose up --build
```

2. **准备历史数据**

```bash
# 方式A：从 Bybit REST API 拉取数据（自动写入数据库）
python scripts/replay_backtest.py \
  --symbol BTCUSDT \
  --timeframe 60 \
  --fetch \
  --fetch-limit 500

# 方式B：如果数据库中已有数据，跳过此步
```

3. **回放历史数据**

```bash
# 回放最近 500 根 1h K 线
python scripts/replay_backtest.py \
  --symbol BTCUSDT \
  --timeframe 60 \
  --limit 500 \
  --sleep-ms 10

# 回放指定时间范围
python scripts/replay_backtest.py \
  --symbol BTCUSDT \
  --timeframe 60 \
  --start-ms 1700000000000 \
  --end-ms 1700500000000 \
  --sleep-ms 5
```

**说明**：
- `--limit`: 从数据库读取最近 N 根 K 线
- `--start-ms` / `--end-ms`: 指定时间范围（毫秒时间戳）
- `--sleep-ms`: 每次发布事件后的延迟（避免压垮消费者）
- `--run-id`: 自定义运行 ID（可选，默认自动生成）

4. **使用一键回放脚本（推荐）**

```bash
# 自动回放 + 等待链路完成 + 生成报告
python scripts/run_replay_and_report.py \
  --symbol BTCUSDT \
  --timeframe 60 \
  --limit 500

# 报告会生成在 reports/ 目录下
# - reports/replay_<run_id>.md
# - reports/replay_<run_id>.json
```

---

### 方式3：实盘测试（Live Trading）- ⚠️ 谨慎使用

**适用场景**：在真实市场环境下测试，会真实下单。

#### 前置条件：

1. **配置 Bybit API**

```bash
# .env 文件中配置
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret
BYBIT_BASE_URL=https://api.bybit.com
EXECUTION_MODE=LIVE
ENV=prod
```

2. **安全建议**

- ✅ 使用测试网 API（`https://api-testnet.bybit.com`）先测试
- ✅ 设置小金额的 `RISK_PCT`（如 0.001 = 0.1%）
- ✅ 启用所有风控开关：
  ```bash
  ACCOUNT_KILL_SWITCH_ENABLED=true
  RISK_CIRCUIT_ENABLED=true
  MAX_OPEN_POSITIONS=1  # 限制同时持仓数
  ```
- ✅ 准备紧急停止方案（Kill Switch）

3. **启动服务并监控**

```bash
# 启动服务
docker compose up --build

# 监控日志
docker compose logs -f execution

# 监控风险状态
watch -n 5 'curl -s http://localhost:8000/v1/risk-state?trade_date=$(date +%Y-%m-%d) | jq'
```

4. **紧急停止**

```bash
# 方式1：通过 API（需要 ADMIN_TOKEN）
curl -X POST http://localhost:8000/v1/admin/kill-switch \
  -H "X-Admin-Token: your_admin_token" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# 方式2：停止服务
docker compose down
```

---

## ✅ 结果验证

### 1. 通过 API 查询结果

#### 查询交易计划

```bash
# 查询最近的交易计划
curl http://localhost:8000/v1/trade-plans?limit=10 | jq

# 查询特定交易对的交易计划
curl "http://localhost:8000/v1/trade-plans?limit=50" | jq '.items[] | select(.symbol=="BTCUSDT")'
```

#### 查询订单

```bash
# 查询所有订单
curl http://localhost:8000/v1/orders?limit=20 | jq

# 查询特定状态的订单
curl "http://localhost:8000/v1/orders?limit=50" | jq '.items[] | select(.status=="FILLED")'
```

#### 查询持仓

```bash
# 查询当前持仓
curl http://localhost:8000/v1/positions?limit=10 | jq

# 查询特定交易对的持仓
curl "http://localhost:8000/v1/positions?limit=50" | jq '.items[] | select(.symbol=="BTCUSDT" and .status=="OPEN")'
```

#### 查询执行报告

```bash
# 查询执行报告（包含订单状态变化）
curl http://localhost:8000/v1/execution-reports?limit=20 | jq

# 查询特定交易计划的执行报告
curl "http://localhost:8000/v1/execution-reports?limit=100" | \
  jq '.items[] | select(.payload.plan_id=="your_plan_id")'
```

#### 查询执行轨迹（用于调试）

```bash
# 查询特定交易计划的执行轨迹
curl "http://localhost:8000/v1/execution-traces?idempotency_key=your_idempotency_key&limit=50" | jq
```

#### 查询风险状态

```bash
# 查询今日风险状态
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-state?trade_date=${TRADE_DATE}" | jq

# 查询风险事件
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | jq
```

#### 查询回测结果（Replay 模式）

```bash
# 查询回测运行记录
curl "http://localhost:8000/v1/backtest-runs?symbol=BTCUSDT&timeframe=60" | jq

# 查询回测交易记录
curl "http://localhost:8000/v1/backtest-trades?run_id=your_run_id&limit=100" | jq

# 对比回测结果
curl "http://localhost:8000/v1/backtest-compare?run_id=your_run_id&limit_trades=50" | jq
```

### 2. 直接查询数据库

```bash
# 连接数据库
psql -U postgres -d trading-ci

# 查询交易计划
SELECT plan_id, symbol, timeframe, side, entry_price, primary_sl_price, status, created_at 
FROM trade_plans 
ORDER BY created_at DESC 
LIMIT 10;

# 查询订单
SELECT order_id, symbol, purpose, side, order_type, qty, price, status, created_at 
FROM orders 
ORDER BY created_at DESC 
LIMIT 10;

# 查询持仓
SELECT position_id, symbol, side, qty, entry_price, sl_price, status, created_at 
FROM positions 
WHERE status = 'OPEN'
ORDER BY created_at DESC;

# 查询执行报告
SELECT event_id, payload->>'plan_id' as plan_id, payload->>'typ' as type, 
       payload->>'severity' as severity, created_at 
FROM execution_reports 
ORDER BY created_at DESC 
LIMIT 20;
```

### 3. 检查 Redis Streams

```bash
# 连接 Redis
redis-cli

# 查看 stream:bar_close 最新消息
XREVRANGE stream:bar_close + - COUNT 5

# 查看 stream:trade_plan 最新消息
XREVRANGE stream:trade_plan + - COUNT 5

# 查看 stream:execution_report 最新消息
XREVRANGE stream:execution_report + - COUNT 10

# 查看消费者组状态
XINFO GROUPS stream:trade_plan
XINFO GROUPS stream:execution_report

# 查看待处理消息（Pending）
XPENDING stream:trade_plan bot-group
```

### 4. 检查服务日志

```bash
# Docker Compose 日志
docker compose logs -f execution  # 执行服务日志
docker compose logs -f strategy    # 策略服务日志
docker compose logs -f marketdata # 市场数据服务日志
docker compose logs -f notifier   # 通知服务日志

# 查看特定服务的错误日志
docker compose logs execution | grep -i error
docker compose logs execution | grep -i "execution_report"
```

---

## 🔍 常见问题排查

### 1. 服务无法启动

**问题**：服务启动失败或健康检查失败

**排查步骤**：

```bash
# 1. 检查环境变量
docker compose config | grep -E "DATABASE_URL|REDIS_URL|EXECUTION_MODE"

# 2. 检查数据库连接
psql -U postgres -d trading-ci -c "SELECT 1;"

# 3. 检查 Redis 连接
redis-cli ping

# 4. 查看服务日志
docker compose logs <service_name>

# 5. 检查端口占用
lsof -i :8000  # api-service
lsof -i :8001  # marketdata-service
lsof -i :8002  # strategy-service
lsof -i :8003  # execution-service
lsof -i :8004  # notifier-service
```

### 2. 没有生成 trade_plan

**问题**：市场数据正常，但没有生成交易计划

**排查步骤**：

```bash
# 1. 检查 bar_close 事件是否发布
redis-cli XREVRANGE stream:bar_close + - COUNT 10

# 2. 检查策略服务是否消费 bar_close
docker compose logs strategy | grep -i "bar_close"

# 3. 检查信号生成
curl http://localhost:8000/v1/signals?limit=10 | jq

# 4. 检查策略配置
curl http://localhost:8000/v1/config | jq '.config | {AUTO_TIMEFRAMES, MIN_CONFIRMATIONS, RISK_PCT}'

# 5. 检查数据库中的 setups 和 triggers
psql -U postgres -d trading-ci -c "SELECT * FROM three_segment_setups ORDER BY created_at DESC LIMIT 5;"
psql -U postgres -d trading-ci -c "SELECT * FROM entry_triggers ORDER BY created_at DESC LIMIT 5;"
```

### 3. trade_plan 没有执行

**问题**：有 trade_plan，但没有生成订单

**排查步骤**：

```bash
# 1. 检查 trade_plan 是否发布到 Redis
redis-cli XREVRANGE stream:trade_plan + - COUNT 5

# 2. 检查执行服务是否消费 trade_plan
docker compose logs execution | grep -i "trade_plan"

# 3. 检查执行模式
curl http://localhost:8000/v1/config | jq '.config.EXECUTION_MODE'

# 4. 检查风控限制
curl http://localhost:8000/v1/risk-state?trade_date=$(date +%Y-%m-%d) | jq

# 5. 检查执行轨迹
# 找到 trade_plan 的 idempotency_key，然后查询
curl "http://localhost:8000/v1/execution-traces?idempotency_key=<idempotency_key>&limit=50" | jq

# 6. 检查 DLQ（死信队列）
curl -H "X-Admin-Token: your_admin_token" http://localhost:8000/v1/dlq?limit=10 | jq
```

### 4. 订单状态异常

**问题**：订单创建但状态不正确

**排查步骤**：

```bash
# 1. 查询订单详情
curl "http://localhost:8000/v1/orders?limit=50" | jq '.items[] | select(.order_id=="your_order_id")'

# 2. 查询执行报告
curl "http://localhost:8000/v1/execution-reports?limit=100" | \
  jq '.items[] | select(.payload.order_id=="your_order_id")'

# 3. 检查 Bybit API 连接（LIVE 模式）
# 查看执行服务日志中的 API 调用记录
docker compose logs execution | grep -i "bybit\|api\|error"

# 4. 检查限流状态
docker compose logs execution | grep -i "rate.*limit\|429"
```

### 5. PAPER 模式订单没有成交

**问题**：PAPER 模式下订单状态一直是 PENDING

**排查步骤**：

```bash
# PAPER 模式下，订单应该立即成交（模拟）
# 1. 检查 paper_sim 是否正常工作
docker compose logs execution | grep -i "paper\|sim"

# 2. 检查 bar_close 事件是否被 paper_sim 消费
docker compose logs execution | grep -i "bar_close.*paper"

# 3. 检查订单的 fill_price
psql -U postgres -d trading-ci -c \
  "SELECT order_id, status, payload->>'fill_price' FROM orders WHERE status='FILLED' LIMIT 5;"
```

### 6. 数据不一致

**问题**：数据库和 Redis Streams 数据不一致

**排查步骤**：

```bash
# 1. 检查 Redis Streams 的消费者组状态
redis-cli XINFO GROUPS stream:trade_plan
redis-cli XPENDING stream:trade_plan bot-group

# 2. 检查是否有大量 pending 消息
# 如果有，可能需要重新消费或清理

# 3. 检查数据库和 Redis 的事件数量
psql -U postgres -d trading-ci -c "SELECT COUNT(*) FROM trade_plans;"
redis-cli XLEN stream:trade_plan

# 4. 重启消费者（如果 pending 过多）
docker compose restart execution strategy
```

---

## 📊 测试检查清单

### 基础功能测试

- [ ] 所有服务正常启动
- [ ] 数据库迁移成功
- [ ] Redis Streams 初始化成功
- [ ] 健康检查通过

### 市场数据测试

- [ ] marketdata-service 连接到 Bybit WebSocket
- [ ] bar_close 事件正常发布
- [ ] 数据写入数据库（bars 表）
- [ ] 缺口回填功能正常（如启用）

### 策略服务测试

- [ ] strategy-service 消费 bar_close
- [ ] 指标计算正常（MACD、RSI 等）
- [ ] 信号生成（signals）
- [ ] 交易计划生成（trade_plans）

### 执行服务测试

- [ ] execution-service 消费 trade_plan
- [ ] 订单创建（ENTRY）
- [ ] 止损设置（SL）
- [ ] 止盈设置（TP1/TP2）
- [ ] 订单状态更新
- [ ] 持仓管理

### 通知服务测试

- [ ] notifier-service 消费 execution_report
- [ ] 日志输出正常
- [ ] Telegram 通知（如配置）

### API 服务测试

- [ ] 所有查询接口正常
- [ ] 数据返回正确
- [ ] 管理员接口（需要 token）

### 风控测试

- [ ] 最大持仓限制
- [ ] 冷却期功能
- [ ] 熔断机制（如启用）
- [ ] Kill Switch（紧急停止）

---

## 🎓 进阶测试场景

### 场景1：测试完整生命周期

1. 使用 replay_backtest 回放历史数据
2. 等待信号生成和交易计划
3. 验证订单执行
4. 验证 TP/SL 触发
5. 验证持仓关闭

### 场景2：测试风控机制

1. 设置 `MAX_OPEN_POSITIONS=1`
2. 注入多个 trade_plan
3. 验证只有第一个执行，其他被拒绝

### 场景3：测试错误处理

1. 注入格式错误的 trade_plan
2. 验证 DLQ 中是否有记录
3. 验证服务不崩溃

### 场景4：测试性能

1. 回放大量历史数据（如 5000 根 K 线）
2. 监控服务响应时间
3. 检查内存和 CPU 使用

---

## 📚 相关文档

- [README.md](./README.md) - 项目概述
- [.env.example](./.env.example) - 环境变量配置示例
- [CHANGELOG.md](./CHANGELOG.md) - 版本变更记录
- [MACD_Project.md](./MACD_Project.md) - 项目详细设计文档

---

## 💡 提示

1. **测试环境隔离**：建议使用独立的数据库和 Redis 实例进行测试
2. **日志监控**：测试时保持日志监控，及时发现问题
3. **逐步测试**：先测试单个服务，再测试完整流程
4. **实盘谨慎**：实盘测试前务必充分验证，使用小金额测试
5. **备份数据**：测试前备份数据库，便于恢复

---

**最后更新**：2024-01-14
