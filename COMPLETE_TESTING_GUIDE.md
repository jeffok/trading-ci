# 完整测试指南

本文档提供完整的测试流程，包括系统测试、功能测试和实盘测试。

---

## 📋 目录

1. [系统测试](#系统测试)
2. [功能测试](#功能测试)
3. [实盘测试](#实盘测试)
4. [测试工具完整命令列表](#测试工具完整命令列表)
5. [测试检查清单](#测试检查清单)

---

## 🔧 系统测试

系统测试验证基础功能和环境是否正常。

### 阶段1：环境准备

#### 1.1 检查服务状态

```bash
# 检查所有服务是否运行
docker compose ps

# 应该看到所有服务状态为 "Up"
# - api-service (8000)
# - marketdata-service (8001)
# - strategy-service (8002)
# - execution-service (8003)
# - notifier-service (8004)
```

#### 1.2 初始化数据库和 Redis Streams

```bash
# 初始化数据库（如果还没初始化）
docker compose exec execution python -m scripts.trading_test_tool init-db

# 初始化 Redis Streams（如果还没初始化）
docker compose exec execution python -m scripts.trading_test_tool init-streams

# 验证数据库完整性
docker compose exec execution python -m scripts.trading_test_tool db-check
```

#### 1.3 检查数据库连接

```bash
# 测试数据库连接
docker compose exec execution python -c "
import sys
sys.path.insert(0, '/app')
from libs.db.pg import get_conn
from libs.common.config import settings

try:
    with get_conn(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT version()')
            print('✅ 数据库连接正常')
except Exception as e:
    print(f'❌ 数据库连接失败: {e}')
    sys.exit(1)
"
```

#### 1.4 检查 Redis 连接

```bash
# 测试 Redis 连接
docker compose exec execution python -c "
import sys
sys.path.insert(0, '/app')
import redis
from libs.common.config import settings

try:
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    r.ping()
    print('✅ Redis 连接正常')
except Exception as e:
    print(f'❌ Redis 连接失败: {e}')
    sys.exit(1)
"
```

### 阶段2：服务健康检查

#### 2.1 使用统一测试工具检查

```bash
# 运行完整的准备检查（包含健康检查和 Redis Streams 检查）
docker compose exec execution python -m scripts.trading_test_tool prepare
```

**预期输出：**
- ✅ EXECUTION_MODE 检查
- ✅ Bybit API Key/Secret 检查
- ✅ 所有服务健康状态
- ✅ Redis Streams 状态
- ✅ 风险配置显示

#### 2.2 手动检查各服务健康状态

```bash
# 检查所有服务健康状态
for port in 8000 8001 8002 8003 8004; do
  echo "=== 端口 $port ==="
  curl -s http://localhost:$port/health | python3 -m json.tool || echo "❌ 失败"
  echo ""
done
```

**预期结果：**
- api-service (8000): `{"env": "prod", "service": "api-service"}`
- marketdata-service (8001): `{"env": "prod", "service": "marketdata-service"}`
- strategy-service (8002): `{"env": "prod", "service": "strategy-service"}`
- execution-service (8003): `{"env": "prod", "service": "execution-service", "execution_mode": "LIVE"}`
- notifier-service (8004): `{"env": "prod", "service": "notifier-service"}`

### 阶段3：数据库完整性检查

```bash
# 运行数据库完整性检查
docker compose exec execution python -m scripts.trading_test_tool db-check
```

**检查项：**
- ✅ 所有必需的表是否存在
- ✅ 表的列结构是否正确
- ✅ 迁移是否已应用
- ✅ 数据统计

---

## 🧪 功能测试

功能测试验证各个模块的功能是否正常。

### 阶段1：市场数据功能测试

#### 1.1 检查市场数据服务

```bash
# 查看市场数据服务日志
docker compose logs marketdata | tail -50

# 检查是否连接到 Bybit WebSocket
docker compose logs marketdata | grep -i "websocket\|connected\|subscribed"
```

#### 1.2 检查 bar_close 事件

```bash
# 检查 bar_close 事件是否正常发布
docker compose exec execution redis-cli XREVRANGE stream:bar_close + - COUNT 5

# 检查数据库中的 bars
docker compose exec execution python -c "
import sys
sys.path.insert(0, '/app')
from libs.db.pg import get_conn
from libs.common.config import settings

with get_conn(settings.database_url) as conn:
    with conn.cursor() as cur:
        cur.execute('''
            SELECT symbol, timeframe, close_price, close_time_ms
            FROM bars
            ORDER BY close_time_ms DESC
            LIMIT 5;
        ''')
        rows = cur.fetchall()
        if rows:
            print('✅ 找到最新 bars:')
            for row in rows:
                print(f'  {row[0]} {row[1]} = {row[2]} @ {row[3]}')
        else:
            print('⚠️  数据库中没有 bars')
"
```

### 阶段2：策略功能测试

#### 2.1 检查策略服务

```bash
# 查看策略服务日志
docker compose logs strategy | tail -50

# 检查是否消费 bar_close
docker compose logs strategy | grep -i "bar_close\|signal\|trade_plan"
```

#### 2.2 检查信号和交易计划

```bash
# 通过 API 查看信号
curl "http://localhost:8000/v1/signals?limit=10" | python3 -m json.tool

# 通过 API 查看交易计划
curl "http://localhost:8000/v1/trade-plans?limit=10" | python3 -m json.tool

# 检查 Redis Streams
docker compose exec execution redis-cli XREVRANGE stream:signal + - COUNT 5
docker compose exec execution redis-cli XREVRANGE stream:trade_plan + - COUNT 5
```

### 阶段3：执行功能测试（PAPER 模式）

⚠️ **在实盘测试前，先在 PAPER 模式下测试执行功能**

#### 3.1 切换到 PAPER 模式

```bash
# 编辑 .env 文件
# EXECUTION_MODE=PAPER

# 重启执行服务
docker compose restart execution

# 验证模式
curl http://localhost:8003/health | python3 -m json.tool | grep execution_mode
# 应该看到: "execution_mode": "PAPER"
```

#### 3.2 运行集成测试（必须！）

**集成测试说明：**

系统提供了多个集成测试命令，已整合到统一的测试工具 `trading_test_tool.py` 中：

##### 3.2.1 风控闸门测试（gates-test 命令）

**用途**：集成测试风控功能（MAX_POSITIONS_BLOCKED、mutex upgrade、cooldown）

**运行方式：**
```bash
# 在 PAPER/BACKTEST 模式下运行（推荐重置数据库）
docker compose exec execution python -m scripts.trading_test_tool gates-test --reset-db

# 不重置数据库
docker compose exec execution python -m scripts.trading_test_tool gates-test

# 自定义等待超时时间
docker compose exec execution python -m scripts.trading_test_tool gates-test --wait 15
```

**测试项：**
- **T1**: MAX_POSITIONS_BLOCKED（最大持仓数限制）- 第4个计划应该被拒绝
- **T2**: mutex upgrade（同币种同向互斥升级）- 4h 计划应该关闭 1h 持仓并开新仓
- **T3**: cooldown（冷却期功能）- 止损后重新入场应该被阻止

**预期结果：**
- ✅ 所有测试通过
- ✅ 风险事件正确生成（MAX_POSITIONS_BLOCKED、COOLDOWN_BLOCKED）
- ✅ 执行报告正确生成（REJECTED、EXITED、FILLED）

**何时使用：**
- **实盘测试前必须运行**，验证风控功能是否正常
- 验证风控规则是否正确执行
- 验证风险事件是否正确生成

##### 3.2.2 平仓测试（close-test 命令）

**用途**：测试平仓流程和通知消息（包含 PnL 和连续亏损统计）

**运行方式：**
```bash
# 在 PAPER/BACKTEST 模式下运行（使用默认参数）
docker compose exec execution python -m scripts.trading_test_tool close-test

# 自定义参数
docker compose exec execution python -m scripts.trading_test_tool close-test \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000 \
  --wait-before-close 5 \
  --wait-after-close 3 \
  --close-price 30050
```

**测试项：**
- 平仓流程（强制平仓）
- PnL 计算
- 连续亏损统计
- 通知消息格式（如果配置了 Telegram）

**预期结果：**
- ✅ 持仓成功创建
- ✅ 平仓成功执行
- ✅ PnL 正确计算
- ✅ 通知消息包含正确信息（如果配置了 Telegram）

**何时使用：**
- 验证平仓流程是否正常
- 验证通知消息格式是否正确
- 在实盘测试前验证平仓功能

##### 3.2.3 回放回测（replay 命令）

**用途**：使用历史 bars 回放 `stream:bar_close` 事件，测试完整服务链路

**运行方式：**
```bash
# 回放数据库中的最近 2000 根 1h bars
docker compose exec execution python -m scripts.trading_test_tool replay \
  --symbol BTCUSDT \
  --timeframe 60 \
  --limit 2000

# 指定时间范围回放
docker compose exec execution python -m scripts.trading_test_tool replay \
  --symbol BTCUSDT \
  --timeframe 60 \
  --start-ms 1700000000000 \
  --end-ms 1700500000000 \
  --sleep-ms 5

# 先从 Bybit REST 拉取数据再回放
docker compose exec execution python -m scripts.trading_test_tool replay \
  --symbol BTCUSDT \
  --timeframe 60 \
  --fetch \
  --fetch-limit 2000 \
  --limit 2000
```

**功能：**
- 从数据库读取历史 bars
- 或从 Bybit REST API 拉取 bars 并写入数据库
- 按时间顺序发布 `bar_close` 事件
- 生成回测运行记录

**何时使用：**
- 测试完整服务链路（marketdata → strategy → execution → notifier）
- 验证策略逻辑是否正确
- 回测历史数据

##### 3.2.4 限流器自测（ratelimit-test 命令）

**用途**：测试 Bybit API 限流器逻辑（不调用 Bybit，仅测试限流算法）

**运行方式：**
```bash
docker compose exec execution python -m scripts.trading_test_tool ratelimit-test
```

**功能：**
- 模拟 200 次请求（25% critical, 45% order-query, 30% account-query）
- 统计等待时间（mean, p50, p90, p99, max）
- 验证限流器配置

**何时使用：**
- 开发阶段验证限流器逻辑
- 调整限流器配置后验证

##### 3.2.5 WebSocket 处理自测（ws-test 命令）

**用途**：测试 WebSocket 消息解析与路由（不连接交易所，使用模拟消息）

**运行方式：**
```bash
docker compose exec execution python -m scripts.trading_test_tool ws-test
```

**功能：**
- 测试 order、execution、position、wallet 消息处理
- 验证消息解析不会崩溃
- 验证路由逻辑正确

**何时使用：**
- 开发阶段验证 WebSocket 处理逻辑
- 修改 WebSocket 处理代码后验证

#### 3.3 测试下单流程（PAPER 模式）

```bash
# 使用统一测试工具测试下单（PAPER 模式，不会真实下单）
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000 \
  --timeframe 15m
```

**验证项：**
- [ ] trade_plan 被成功消费
- [ ] 订单在数据库中创建（PAPER 模式）
- [ ] 持仓在数据库中创建
- [ ] execution_report 正确生成
- [ ] 无异常错误

### 阶段4：API 功能测试

#### 4.1 测试所有 API 端点

```bash
# 测试信号 API
curl "http://localhost:8000/v1/signals?limit=5" | python3 -m json.tool

# 测试交易计划 API
curl "http://localhost:8000/v1/trade-plans?limit=5" | python3 -m json.tool

# 测试订单 API
curl "http://localhost:8000/v1/orders?limit=5" | python3 -m json.tool

# 测试持仓 API
curl "http://localhost:8000/v1/positions?limit=5" | python3 -m json.tool

# 测试执行报告 API
curl "http://localhost:8000/v1/execution-reports?limit=5" | python3 -m json.tool

# 测试风险事件 API
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=5" | python3 -m json.tool

# 测试风险状态 API
curl "http://localhost:8000/v1/risk-state?trade_date=${TRADE_DATE}" | python3 -m json.tool

# 测试配置 API（脱敏）
curl "http://localhost:8000/v1/config" | python3 -m json.tool | grep -E "EXECUTION_MODE|RISK_PCT|MAX_OPEN_POSITIONS"
```

---

## 🚀 实盘测试

实盘测试在真实市场环境下进行，**会真实下单**。

### ⚠️ 重要安全提示

1. ✅ **先完成功能测试**：确保所有功能在 PAPER 模式下正常
2. ✅ **使用小金额测试**：设置 `RISK_PCT ≤ 0.001`（0.1%）
3. ✅ **启用所有风控**：确保所有保护机制已启用
4. ✅ **准备紧急停止方案**：知道如何快速停止交易
5. ✅ **实时监控日志**：始终保持日志监控
6. ✅ **在交易所验证**：所有操作后必须在 Bybit 交易所验证

### 阶段1：实盘测试前准备

#### 1.1 切换到 LIVE 模式

```bash
# 编辑 .env 文件
# EXECUTION_MODE=LIVE
# BYBIT_API_KEY=your_real_api_key
# BYBIT_API_SECRET=your_real_api_secret

# 重启执行服务
docker compose restart execution

# 验证模式
curl http://localhost:8003/health | python3 -m json.tool | grep execution_mode
# 应该看到: "execution_mode": "LIVE"
```

#### 1.2 运行准备检查

```bash
# 运行完整的准备检查
docker compose exec execution python -m scripts.trading_test_tool prepare
```

**检查项：**
- [ ] EXECUTION_MODE=LIVE
- [ ] Bybit API Key/Secret 已配置
- [ ] 所有服务健康检查通过
- [ ] Redis Streams 状态正常
- [ ] 风险配置合理（RISK_PCT ≤ 0.001）

#### 1.3 清理无效持仓

```bash
# 查看当前持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 如果有无效持仓，清理它们
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes

# 验证清理结果
docker compose exec execution python -m scripts.trading_test_tool positions
# 应该显示：没有找到 OPEN 持仓
```

#### 1.4 确认风险配置

编辑 `.env` 文件，确保以下配置：

```bash
# 小金额测试（强烈建议）
RISK_PCT=0.001  # 0.1%

# 限制持仓数
MAX_OPEN_POSITIONS=1

# 启用风控（强烈建议）
ACCOUNT_KILL_SWITCH_ENABLED=true
DAILY_LOSS_LIMIT_PCT=0.02

RISK_CIRCUIT_ENABLED=true
DAILY_DRAWDOWN_SOFT_PCT=0.01
DAILY_DRAWDOWN_HARD_PCT=0.02
```

重启执行服务使配置生效：

```bash
docker compose restart execution
```

### 阶段2：启动监控

#### 2.1 启动日志监控（重要！）

**在另一个终端窗口**启动日志监控：

```bash
# 监控执行服务日志（最重要）
docker compose logs -f execution

# 可选：同时监控其他服务
docker compose logs -f strategy
docker compose logs -f marketdata
```

### 阶段3：执行实盘测试下单

#### 3.1 获取当前市场价格

```bash
# 方式1：查看数据库最新 bar
docker compose exec execution python -c "
import sys
sys.path.insert(0, '/app')
from libs.db.pg import get_conn
from libs.common.config import settings

with get_conn(settings.database_url) as conn:
    with conn.cursor() as cur:
        cur.execute('''
            SELECT symbol, close_price, close_time_ms
            FROM bars
            WHERE symbol='BTCUSDT' AND timeframe='15m'
            ORDER BY close_time_ms DESC
            LIMIT 1;
        ''')
        row = cur.fetchone()
        if row:
            print(f'最新价格: {row[0]} = {row[1]} (时间: {row[2]})')
        else:
            print('未找到数据，请查看 Bybit 交易所获取当前价格')
"
```

**方式2：** 登录 Bybit 交易所，查看 BTCUSDT 当前价格

#### 3.2 执行测试下单

```bash
# 使用统一测试工具执行测试下单
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000 \
  --timeframe 15m \
  --wait-seconds 30
```

**参数说明：**
- `--symbol`: 交易对（BTCUSDT, ETHUSDT 等）
- `--side`: 方向（BUY 做多 或 SELL 做空）
- `--entry-price`: 入场价格（建议使用当前市场价格）
- `--sl-price`: 止损价格（确保与入场价格有合理距离）
- `--timeframe`: 时间框架（默认 15m）
- `--wait-seconds`: 等待执行的时间（默认 30 秒）

**执行过程：**
1. 工具会显示配置信息和交易参数
2. 要求确认（输入 'yes'）
3. 构建并发布 trade_plan
4. 等待执行服务处理
5. 检查执行结果（execution_report、risk_event）

#### 3.3 观察执行过程

在日志监控窗口中，你应该看到：

```
[INFO] 收到 trade_plan: plan_id=live-test-xxx
[INFO] 风险检查通过
[INFO] 创建订单: symbol=BTCUSDT, side=Buy, qty=0.003
[INFO] 订单创建成功: bybit_order_id=xxx
[INFO] 发布 execution_report: status=ORDER_FILLED
```

### 阶段4：验证结果

#### 4.1 查看订单

```bash
# 查看最新订单
docker compose exec execution python -m scripts.trading_test_tool orders

# 查看指定 idempotency_key 的订单（从 test 命令输出中获取）
docker compose exec execution python -m scripts.trading_test_tool orders \
  --idempotency-key idem-xxx

# 通过 API 查看
curl "http://localhost:8000/v1/orders?limit=10" | python3 -m json.tool
```

**验证项：**
- [ ] 订单已创建
- [ ] 订单状态正确（FILLED/PARTIALLY_FILLED/NEW）
- [ ] 订单价格和数量正确
- [ ] bybit_order_id 已记录

#### 4.2 查看持仓

```bash
# 查看持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 详细信息
docker compose exec execution python -m scripts.trading_test_tool positions --detailed

# 通过 API 查看
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool
```

**验证项：**
- [ ] 持仓已创建
- [ ] 持仓方向和数量正确
- [ ] 入场价格正确
- [ ] 止损价格已设置

#### 4.3 查看执行报告

```bash
# 通过 API 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=10" | python3 -m json.tool
```

**验证项：**
- [ ] execution_report 已生成
- [ ] 报告状态正确（ORDER_FILLED/POSITION_OPENED 等）
- [ ] 报告包含正确的 plan_id 和 idempotency_key

#### 4.4 查看风险事件

```bash
# 获取今天的日期
TRADE_DATE=$(date +%Y-%m-%d)

# 查看风险事件
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool

# 查看风险状态
curl "http://localhost:8000/v1/risk-state?trade_date=${TRADE_DATE}" | python3 -m json.tool
```

**验证项：**
- [ ] 没有异常风险事件
- [ ] 如果有风险事件，确认是预期的（如 position_mutex_blocked 等）

#### 4.5 在 Bybit 交易所验证（最重要！）

**必须手动在 Bybit 交易所验证：**

1. **登录 Bybit 交易所**
   - 访问 https://www.bybit.com
   - 登录你的账户

2. **查看"订单"页面**
   - 进入"交易" → "订单"
   - 确认订单已创建
   - 检查订单状态、价格、数量

3. **查看"持仓"页面**
   - 进入"交易" → "持仓"
   - 确认持仓已创建
   - 检查持仓方向、数量、入场价格

4. **查看"条件单"页面**
   - 进入"交易" → "条件单"
   - 确认止损单已设置
   - 确认止盈单已设置（TP1, TP2）

**验证项：**
- [ ] 订单在交易所中真实存在
- [ ] 持仓在交易所中真实存在
- [ ] 止损/止盈单已正确设置
- [ ] 价格和数量与系统记录一致

### 阶段5：后续监控

#### 5.1 监控订单执行

```bash
# 持续监控订单状态
watch -n 5 'docker compose exec execution python -m scripts.trading_test_tool orders --limit 5'

# 或通过 API
watch -n 5 'curl -s "http://localhost:8000/v1/orders?limit=5" | python3 -m json.tool'
```

#### 5.2 监控持仓变化

```bash
# 持续监控持仓
watch -n 10 'docker compose exec execution python -m scripts.trading_test_tool positions'
```

#### 5.3 查看执行轨迹（可选）

```bash
# 获取 idempotency_key（从 test 命令输出中）
IDEM_KEY="idem-xxx"

# 查看执行轨迹
curl "http://localhost:8000/v1/execution-traces?idempotency_key=${IDEM_KEY}&limit=50" | python3 -m json.tool
```

---

## 📊 测试检查清单

### 系统测试检查清单

- [ ] 所有服务正常启动
- [ ] 数据库连接正常
- [ ] Redis 连接正常
- [ ] 数据库完整性检查通过
- [ ] 所有服务健康检查通过
- [ ] Redis Streams 状态正常

### 功能测试检查清单

- [ ] 市场数据服务正常接收数据
- [ ] bar_close 事件正常发布
- [ ] 策略服务正常消费 bar_close
- [ ] 信号和交易计划正常生成
- [ ] 风控闸门测试通过（`gates-test` 命令）
- [ ] 平仓测试通过（`close-test` 命令）
- [ ] PAPER 模式下下单流程正常（`test` 命令）
- [ ] 所有 API 端点正常

### 实盘测试检查清单

- [ ] 切换到 LIVE 模式
- [ ] Bybit API Key/Secret 已配置
- [ ] 风险配置合理（RISK_PCT ≤ 0.001）
- [ ] 所有风控已启用
- [ ] 无效持仓已清理
- [ ] 日志监控已启动
- [ ] trade_plan 成功发布
- [ ] 执行服务成功消费 trade_plan
- [ ] 订单在 Bybit 交易所真实创建
- [ ] 持仓在 Bybit 交易所真实创建
- [ ] 止损/止盈单在 Bybit 交易所正确设置
- [ ] 数据库记录与交易所状态一致
- [ ] execution_report 正确生成
- [ ] 无异常风险事件

---

## 🔍 问题排查

### 问题1：订单未创建

**排查步骤：**

```bash
# 1. 查看执行服务日志
docker compose logs execution | tail -100

# 2. 检查 Redis Streams 消费者状态
docker compose exec execution redis-cli XINFO GROUPS stream:trade_plan

# 3. 检查是否有 pending 消息
docker compose exec execution redis-cli XPENDING stream:trade_plan bot-group

# 4. 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=10" | python3 -m json.tool

# 5. 查看风险事件
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool
```

### 问题2：订单被拒绝

**排查步骤：**

```bash
# 1. 查看执行报告中的原因
curl "http://localhost:8000/v1/execution-reports?limit=10" | python3 -m json.tool | grep -A 5 "reason"

# 2. 查看风险事件
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool

# 3. 检查持仓状态
docker compose exec execution python -m scripts.trading_test_tool positions

# 4. 检查风险状态
curl "http://localhost:8000/v1/risk-state?trade_date=${TRADE_DATE}" | python3 -m json.tool
```

### 问题3：数据库与交易所不一致

**排查步骤：**

```bash
# 1. 查看数据库持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 2. 在 Bybit 交易所手动验证

# 3. 如果发现不一致，清理无效持仓
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes

# 4. 在 LIVE 模式下，持仓同步会自动运行（每 10 秒）
# 查看同步日志
docker compose logs execution | grep -i "position_sync"
```

---

## 🛑 紧急停止

如果发现异常，立即执行：

### 1. 停止执行服务

```bash
docker compose stop execution
```

### 2. 在 Bybit 交易所手动平仓

- 登录 Bybit
- 找到持仓
- 手动平仓

### 3. 清理数据库状态

```bash
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes
```

### 4. 使用 Kill Switch（如果配置）

```bash
# 启用 Kill Switch
curl -X POST "http://localhost:8000/v1/admin/kill-switch?action=on" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"

# 检查状态
curl "http://localhost:8000/v1/admin/kill-switch" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

---

## 📝 测试记录模板

```
测试时间: [日期时间]
测试人员: [姓名]
测试类型: [系统测试/功能测试/实盘测试]

系统测试:
- [ ] 环境准备完成
- [ ] 服务健康检查通过
- [ ] 数据库完整性检查通过

功能测试:
- [ ] 市场数据功能正常
- [ ] 策略功能正常
- [ ] 执行功能正常（PAPER 模式）
- [ ] 风控功能正常
- [ ] API 功能正常

实盘测试:
- [ ] 准备检查通过
- [ ] 无效持仓已清理
- [ ] 风险配置合理
- [ ] 订单在交易所创建
- [ ] 持仓在交易所创建
- [ ] 止损/止盈单已设置
- [ ] 数据一致性验证通过

问题记录:
[记录任何问题或异常]

备注:
[其他备注]
```

---

## 🎯 测试成功标准

### 系统测试成功标准

1. ✅ 所有服务正常启动
2. ✅ 数据库和 Redis 连接正常
3. ✅ 所有服务健康检查通过
4. ✅ 数据库完整性检查通过

### 功能测试成功标准

1. ✅ 市场数据正常接收和发布
2. ✅ 策略正常生成信号和交易计划
3. ✅ 风控功能正常（闸门测试通过）
4. ✅ 平仓功能正常（平仓测试通过）
5. ✅ PAPER 模式下下单流程正常
6. ✅ 所有 API 端点正常

### 实盘测试成功标准

1. ✅ 订单在 Bybit 交易所真实创建
2. ✅ 持仓在 Bybit 交易所真实创建
3. ✅ 止损/止盈单在 Bybit 交易所正确设置
4. ✅ 数据库记录与交易所状态一致
5. ✅ execution_report 正确生成
6. ✅ 无异常风险事件

---

## 💡 最佳实践

1. **按顺序测试**：先系统测试，再功能测试，最后实盘测试
2. **小金额开始**：首次实盘测试使用最小金额（RISK_PCT=0.001）
3. **逐步增加**：确认系统正常后，再逐步增加金额
4. **实时监控**：测试过程中始终保持日志监控
5. **及时验证**：每个步骤后立即验证结果
6. **记录问题**：遇到问题及时记录，便于后续排查
7. **定期检查**：定期检查持仓状态和风险状态

---

## 📚 相关文档

- `scripts/trading_test_tool.py` - 统一测试工具（所有测试功能）
- `LIVE_TRADING_GUIDE.md` - 实盘交易指南
- `TROUBLESHOOTING.md` - 问题排查指南
- `SYNC_MECHANISM.md` - 订单和持仓同步机制
- `CHANGELOG.md` - 变更日志

## 🛠️ 测试工具完整命令列表

所有测试功能已整合到 `trading_test_tool.py`，使用统一命令：

### 基础命令（实盘测试）

```bash
# 准备检查
docker compose exec execution python -m scripts.trading_test_tool prepare

# 查看持仓
docker compose exec execution python -m scripts.trading_test_tool positions
docker compose exec execution python -m scripts.trading_test_tool positions --detailed

# 清理持仓
docker compose exec execution python -m scripts.trading_test_tool clean --all
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes
docker compose exec execution python -m scripts.trading_test_tool clean <position_id>

# 执行测试下单（⚠️ 会真实下单！）
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT --side BUY
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT --side BUY --entry-price 30000 --sl-price 29000

# 查看订单
docker compose exec execution python -m scripts.trading_test_tool orders
docker compose exec execution python -m scripts.trading_test_tool orders --idempotency-key idem-xxx

# 诊断下单失败原因
docker compose exec execution python -m scripts.trading_test_tool diagnose \
  --symbol BTCUSDT --side BUY

# 同步持仓（检查并修复不一致）
docker compose exec execution python -m scripts.trading_test_tool sync
docker compose exec execution python -m scripts.trading_test_tool sync --dry-run
```

### 集成测试命令（PAPER/BACKTEST 模式）

```bash
# 平仓测试
docker compose exec execution python -m scripts.trading_test_tool close-test \
  --symbol BTCUSDT --side BUY --entry-price 30000 --sl-price 29000

# 风控闸门测试（实盘前必须运行！）
docker compose exec execution python -m scripts.trading_test_tool gates-test --reset-db

# 回放回测
docker compose exec execution python -m scripts.trading_test_tool replay \
  --symbol BTCUSDT --timeframe 60 --limit 2000

# 限流器自测（开发阶段）
docker compose exec execution python -m scripts.trading_test_tool ratelimit-test

# WebSocket 处理自测（开发阶段）
docker compose exec execution python -m scripts.trading_test_tool ws-test
```

### 查看帮助

```bash
# 查看所有命令
docker compose exec execution python -m scripts.trading_test_tool --help

# 查看特定命令的帮助
docker compose exec execution python -m scripts.trading_test_tool test --help
docker compose exec execution python -m scripts.trading_test_tool gates-test --help
docker compose exec execution python -m scripts.trading_test_tool replay --help
```

### 测试工具功能总览

| 命令 | 功能 | 模式要求 | 用途 |
|------|------|---------|------|
| `prepare` | 准备检查 | LIVE | 检查配置、服务状态、风险设置 |
| `positions` | 查看持仓 | 任意 | 查看所有 OPEN 持仓 |
| `clean` | 清理持仓 | 任意 | 清理无效的 OPEN 持仓 |
| `test` | 执行测试下单 | LIVE | 执行实盘测试下单（⚠️ 会真实下单） |
| `orders` | 查看订单 | 任意 | 查看订单列表 |
| `diagnose` | 诊断下单失败 | LIVE | 诊断下单失败原因 |
| `sync` | 同步持仓 | LIVE | 同步数据库持仓与交易所持仓 |
| `close-test` | 平仓测试 | PAPER/BACKTEST | 测试平仓流程和通知消息 |
| `gates-test` | 风控闸门测试 | PAPER/BACKTEST | 测试风控功能（必须运行） |
| `replay` | 回放回测 | PAPER/BACKTEST | 使用历史数据回放测试 |
| `ratelimit-test` | 限流器自测 | 任意 | 测试限流器逻辑（开发阶段） |
| `ws-test` | WebSocket 自测 | 任意 | 测试 WebSocket 消息处理（开发阶段） |
