# 交易系统测试完整指南

本指南整合了所有测试相关的文档和工具，提供完整的测试流程和故障排查方法。

---

## 📋 目录

1. [快速测试下单](#快速测试下单)
2. [信号生成诊断](#信号生成诊断)
3. [小时间框架测试](#小时间框架测试)
4. [系统状态检查](#系统状态检查)
5. [常见问题解决](#常见问题解决)
6. [配置检查清单](#配置检查清单)

---

## 🚀 快速测试下单

### 方法1：快速测试命令（推荐，最简单）

```bash
# 使用默认参数（BTCUSDT BUY 1h）
docker compose exec execution python -m scripts.trading_test_tool quick-test

# 指定交易对和方向
docker compose exec execution python -m scripts.trading_test_tool quick-test \
    --symbol ETHUSDT \
    --side SELL

# 指定时间框架
docker compose exec execution python -m scripts.trading_test_tool quick-test \
    --symbol BTCUSDT \
    --side BUY \
    --timeframe 1h
```

**特点**：
- ✅ 自动诊断（下单前检查）
- ✅ 自动确认（跳过手动确认）
- ✅ 自动获取市场价格
- ✅ 自动计算止损价格

### 方法2：完整测试命令（更多控制）

```bash
# 完整参数控制
docker compose exec execution python -m scripts.trading_test_tool test \
    --symbol BTCUSDT \
    --side BUY \
    --timeframe 1h \
    --sl-distance-pct 0.02 \
    --auto-diagnose \
    --confirm \
    --wait-seconds 30
```

### 方法3：手动指定价格

```bash
# 手动指定入场价和止损价
docker compose exec execution python -m scripts.trading_test_tool test \
    --symbol BTCUSDT \
    --side BUY \
    --entry-price 50000 \
    --sl-price 49000 \
    --timeframe 1h
```

---

## 🔍 信号生成诊断

### 为什么没有信号生成？

信号生成需要满足以下**所有条件**：

1. **市场数据充足**：至少需要 **120 根 K 线**
2. **三段背离检测**：MACD histogram 必须形成三段顶/底背离结构
3. **Vegas 状态匹配**：
   - LONG 信号需要 Vegas 状态为 **Bullish**
   - SHORT 信号需要 Vegas 状态为 **Bearish**
4. **确认项足够**：至少命中 **MIN_CONFIRMATIONS** 个确认项（默认 2 个）
   - `ENGULFING`：吞没形态
   - `RSI_DIV`：RSI 背离
   - `OBV_DIV`：OBV 背离
   - `FVG_PROXIMITY`：FVG 接近

### 快速诊断

```bash
# 诊断指定交易对和时间框架
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1h

# 诊断其他时间框架
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1m

docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 5m
```

### 诊断工具检查项

诊断工具会检查：
1. 市场数据是否充足（>= 120 根 K 线）
2. 是否检测到三段背离
3. Vegas 状态是否匹配
4. 确认项是否足够
5. 策略服务状态
6. 历史信号记录
7. 配置参数

---

## ⚡ 小时间框架测试

使用 1分钟、5分钟等小时间框架可以更快验证系统是否正常运行。

### 配置修改

#### 方法1：只测试信号生成（推荐，安全）

只生成 `signal`，不生成 `trade_plan`（不会真实下单）：

```bash
# 在 .env 文件中修改：

# 1. 添加小时间框架到市场数据订阅
MARKETDATA_TIMEFRAMES=1m,5m,15m,30m,1h,4h,8h,1d

# 2. 添加到监控时间框架（只生成 signal，不生成 trade_plan）
MONITOR_TIMEFRAMES=1m,5m,15m,30m,8h

# 3. AUTO_TIMEFRAMES 保持不变（只有这些会生成 trade_plan）
AUTO_TIMEFRAMES=1h,4h,1d
```

#### 方法2：完整测试（包括下单，需谨慎）

如果也想测试下单流程，可以临时添加到 AUTO_TIMEFRAMES：

```bash
# 在 .env 文件中修改：

# 1. 添加小时间框架到市场数据订阅
MARKETDATA_TIMEFRAMES=1m,5m,15m,30m,1h,4h,8h,1d

# 2. 添加到监控时间框架
MONITOR_TIMEFRAMES=1m,5m,15m,30m,8h

# 3. 临时添加到自动下单时间框架（⚠️ 会真实下单！）
AUTO_TIMEFRAMES=1m,5m,1h,4h,1d
```

**⚠️ 警告**：如果添加到 `AUTO_TIMEFRAMES`，系统会在满足条件时真实下单！请确保：
- 使用小金额测试（`RISK_PCT=0.001`）
- 设置合理的 `MIN_ORDER_VALUE_USDT` 和 `MAX_ORDER_VALUE_USDT`
- 启用所有风控（Kill Switch、Risk Circuit 等）

### 测试步骤

```bash
# 1. 修改配置后重启服务
docker compose restart marketdata strategy

# 2. 诊断小时间框架
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1m

# 3. 监控日志
docker compose logs -f strategy | grep -i "signal"
```

### 小时间框架的优势

- ✅ **更快的事件频率**：1分钟 = 每小时 60 个 bar_close 事件
- ✅ **更容易形成三段背离**：小时间框架更容易满足条件
- ✅ **快速验证系统**：可以在短时间内验证整个流程

### 注意事项

- ⚠️ **信号质量**：小时间框架的信号可能不如大时间框架稳定
- ⚠️ **交易频率**：如果添加到 `AUTO_TIMEFRAMES`，会产生更多订单
- ⚠️ **测试目的**：建议只用于测试，实盘交易建议使用大时间框架（1h、4h、1d）

---

## 📊 系统状态检查

### 检查所有服务状态

```bash
# 检查服务状态
docker compose ps

# 检查各服务日志
docker compose logs marketdata --tail 50
docker compose logs strategy --tail 50
docker compose logs execution --tail 50
```

### 检查配置和执行模式

```bash
# 检查配置
docker compose exec execution python -m scripts.trading_test_tool prepare

# 诊断下单失败原因
docker compose exec execution python -m scripts.trading_test_tool diagnose \
    --symbol BTCUSDT \
    --side BUY
```

### 检查信号和交易计划

```bash
# 查看数据库中的信号
docker compose exec execution python -c "
from libs.common.config import settings
from libs.db.pg import get_conn

with get_conn(settings.database_url) as conn:
    with conn.cursor() as cur:
        cur.execute('''
            SELECT symbol, timeframe, bias, hit_count, hits, vegas_state, created_at
            FROM signals
            ORDER BY created_at DESC
            LIMIT 20
        ''')
        rows = cur.fetchall()
        print(f'最近 {len(rows)} 个信号：')
        for row in rows:
            print(f'  {row[0]} {row[1]} {row[2]} | hits={row[3]} | {row[5]} | {row[6]}')
"
```

```bash
# 查看交易计划
docker compose exec execution python -c "
from libs.common.config import settings
from libs.db.pg import get_conn

with get_conn(settings.database_url) as conn:
    with conn.cursor() as cur:
        cur.execute('''
            SELECT plan_id, symbol, timeframe, side, status, created_at
            FROM trade_plans
            ORDER BY created_at DESC
            LIMIT 20
        ''')
        rows = cur.fetchall()
        print(f'最近 {len(rows)} 个交易计划：')
        for row in rows:
            print(f'  {row[0]} {row[1]} {row[2]} {row[3]} {row[4]} | {row[5]}')
"
```

### 检查订单和持仓

```bash
# 查看订单
docker compose exec execution python -m scripts.trading_test_tool orders --limit 20

# 查看持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 查看执行报告
docker compose logs execution | grep -i "rejected\|blocked\|cooldown\|max.*position" | tail -30
```

---

## 🔧 常见问题解决

### 问题1：为什么没有订单？

#### 原因1：执行模式不是 LIVE
```bash
# 检查 .env 文件
grep EXECUTION_MODE .env

# 应该设置为：
EXECUTION_MODE=LIVE
```

#### 原因2：Kill Switch 已开启
```bash
# 检查 kill switch 状态
docker compose exec execution python -c "
from libs.common.config import settings
import redis
r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
print('Kill Switch:', r.get('KILL_SWITCH'))
"
```

#### 原因3：达到最大持仓数
```bash
# 检查当前持仓数
docker compose exec execution python -m scripts.trading_test_tool positions

# 检查配置
grep MAX_OPEN_POSITIONS .env
```

#### 原因4：在冷却期（Cooldown）
```bash
# 检查冷却期状态
docker compose exec execution python -c "
from libs.common.config import settings
from services.execution.repo import get_active_cooldown
from libs.common.time import now_ms
cd = get_active_cooldown(settings.database_url, 'BTCUSDT', 'BUY', '1h', now_ms())
print('Cooldown:', cd)
"
```

#### 原因5：没有生成信号或交易计划
```bash
# 运行信号诊断
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1h

# 检查策略服务日志
docker compose logs strategy | grep -i "signal\|trade_plan" | tail -30
```

#### 原因6：风控电路触发
```bash
# 检查风控状态
docker compose logs execution | grep -i "risk_circuit\|drawdown" | tail -20
```

#### 原因7：订单价值超出限制
```bash
# 检查订单价值限制
grep -E "MIN_ORDER_VALUE_USDT|MAX_ORDER_VALUE_USDT" .env
```

### 问题2：为什么没有信号生成？

#### 原因1：K 线数量不足
```bash
# 运行诊断工具
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1h

# 检查市场数据服务
docker compose logs marketdata --tail 100
```

#### 原因2：未检测到三段背离
这是市场条件，不是系统问题。建议：
- 等待市场形成三段背离结构
- 检查其他交易对是否有信号
- 使用小时间框架（1m、5m）更容易形成背离

#### 原因3：Vegas 状态不匹配
- LONG 信号需要 Bullish
- SHORT 信号需要 Bearish
- 等待市场趋势与信号方向一致

#### 原因4：确认项不足
- 需要至少命中 `MIN_CONFIRMATIONS` 个确认项（默认 2 个）
- 等待更多确认项命中

### 问题3：策略服务未运行

```bash
# 检查策略服务状态
docker compose ps strategy

# 查看策略服务日志
docker compose logs strategy --tail 100

# 检查是否有错误
docker compose logs strategy | grep -i error

# 重启策略服务
docker compose restart strategy
```

### 问题4：市场数据服务未运行

```bash
# 检查市场数据服务状态
docker compose ps marketdata

# 查看市场数据服务日志
docker compose logs marketdata --tail 100

# 检查配置
grep MARKETDATA_SYMBOLS .env
grep MARKETDATA_TIMEFRAMES .env

# 重启市场数据服务
docker compose restart marketdata
```

---

## ⚙️ 配置检查清单

确保以下配置正确：

```bash
# 1. 执行模式
EXECUTION_MODE=LIVE

# 2. Bybit API 配置
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret
BYBIT_REST_BASE_URL=https://api.bybit.com

# 3. 自动下单时间框架（只有这些时间框架会生成 trade_plan）
AUTO_TIMEFRAMES=1h,4h,1d

# 4. 监控时间框架（只生成 signal，不生成 trade_plan）
MONITOR_TIMEFRAMES=15m,30m,8h

# 5. 市场数据配置
MARKETDATA_SYMBOLS=BTCUSDT,ETHUSDT,...
MARKETDATA_TIMEFRAMES=15m,30m,1h,4h,8h,1d

# 6. 风控配置
RISK_PCT=0.001  # 风险百分比
MAX_OPEN_POSITIONS=1  # 最大持仓数
ACCOUNT_KILL_SWITCH_ENABLED=true
RISK_CIRCUIT_ENABLED=true

# 7. 订单价值限制
MIN_ORDER_VALUE_USDT=50.0
MAX_ORDER_VALUE_USDT=1000.0
LEVERAGE=10
MARGIN_MODE=isolated

# 8. 冷却期（如果启用，止损后需要等待）
COOLDOWN_ENABLED=true
COOLDOWN_BARS_1H=2
COOLDOWN_BARS_4H=1
COOLDOWN_BARS_1D=1

# 9. 最小确认项数量
MIN_CONFIRMATIONS=2

# 10. 数据质量检查配置
DATA_QUALITY_ENABLED=true  # 启用数据质量检查（默认：true）
DATA_QUALITY_BAR_DUPLICATE_ENABLED=false  # Bar 修订/重复告警（默认：false，因为这是 Bybit 的正常行为）
DATA_QUALITY_LAG_MS=180000  # 数据延迟告警阈值（毫秒）
DATA_QUALITY_PRICE_JUMP_PCT=0.08  # 价格跳变告警阈值（8%）
DATA_QUALITY_VOLUME_SPIKE_MULTIPLE=10.0  # 成交量异常告警倍数（10倍）
```

---

## 🛠️ 所有可用命令

### 基础检查命令

```bash
# 准备检查（检查配置、服务状态等）
docker compose exec execution python -m scripts.trading_test_tool prepare

# 查看持仓
docker compose exec execution python -m scripts.trading_test_tool positions
docker compose exec execution python -m scripts.trading_test_tool positions --detailed

# 查看订单
docker compose exec execution python -m scripts.trading_test_tool orders
docker compose exec execution python -m scripts.trading_test_tool orders --limit 20
```

### 测试命令

```bash
# 快速测试下单（推荐）
docker compose exec execution python -m scripts.trading_test_tool quick-test
docker compose exec execution python -m scripts.trading_test_tool quick-test --symbol ETHUSDT --side SELL

# 完整测试下单
docker compose exec execution python -m scripts.trading_test_tool test \
    --symbol BTCUSDT \
    --side BUY \
    --timeframe 1h \
    --auto-diagnose \
    --confirm
```

### 诊断命令

```bash
# 诊断下单失败原因
docker compose exec execution python -m scripts.trading_test_tool diagnose \
    --symbol BTCUSDT \
    --side BUY

# 诊断信号生成问题
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1h
```

### 维护命令

```bash
# 同步数据库持仓与交易所持仓
docker compose exec execution python -m scripts.trading_test_tool sync
docker compose exec execution python -m scripts.trading_test_tool sync --dry-run

# 清理持仓
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes

# 数据库完整性检查
docker compose exec execution python -m scripts.trading_test_tool db-check
```

### 回测命令

```bash
# 离线回测
docker compose exec execution python -m scripts.trading_test_tool backtest \
    --symbol BTCUSDT \
    --timeframe 60 \
    --limit 5000

# 回放回测 + 报告生成
docker compose exec execution python -m scripts.trading_test_tool replay-report \
    --symbol BTCUSDT \
    --timeframe 60 \
    --limit 2000
```

### 初始化命令

```bash
# 数据库迁移初始化
docker compose exec execution python -m scripts.trading_test_tool init-db

# Redis Streams 初始化
docker compose exec execution python -m scripts.trading_test_tool init-streams
```

---

## 📝 注意事项

1. **⚠️ 测试下单会真实下单**：确保金额设置合理（`RISK_PCT` 很小）
2. **⚠️ 检查执行模式**：确保 `EXECUTION_MODE=LIVE` 才会真实下单
3. **⚠️ 检查风控设置**：确保所有风控都已正确配置
4. **⚠️ 监控日志**：下单后立即查看日志确认结果
5. **⚠️ 小时间框架测试**：建议只用于测试，实盘交易建议使用大时间框架

---

## 🆘 如果还是无法解决问题

1. **查看完整日志**：
   ```bash
   docker compose logs execution --tail 200 | grep -i "error\|reject\|block\|fail"
   docker compose logs strategy --tail 200 | grep -i "error\|warning"
   docker compose logs marketdata --tail 200 | grep -i "error\|warning"
   ```

2. **检查数据库中的执行报告**：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool orders --limit 50
   ```

3. **检查 Redis Streams 中的事件**：
   ```bash
   docker compose exec execution python -c "
   import redis
   from libs.common.config import settings
   r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
   msgs = r.xrevrange('stream:trade_plan', '+', '-', count=10)
   print(f'最近的交易计划: {len(msgs)}')
   "
   ```

4. **运行完整诊断**：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool prepare
   docker compose exec execution python -m scripts.trading_test_tool diagnose \
       --symbol BTCUSDT \
       --side BUY
   docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
       --symbol BTCUSDT \
       --timeframe 1h
   ```

---

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

### 🛑 紧急停止

如果发现异常，立即执行：

#### 1. 停止执行服务

```bash
docker compose stop execution
```

#### 2. 在 Bybit 交易所手动平仓

- 登录 Bybit
- 找到持仓
- 手动平仓

#### 3. 清理数据库状态

```bash
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes
```

#### 4. 使用 Kill Switch（如果配置）

```bash
# 启用 Kill Switch
curl -X POST "http://localhost:8000/v1/admin/kill-switch?action=on" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"

# 检查状态
curl "http://localhost:8000/v1/admin/kill-switch" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

---

## 🔄 订单与持仓同步机制

系统采用**多层次的同步机制**，确保数据库状态与交易所状态保持一致：

1. **WebSocket 实时同步**（主要机制）
2. **REST API 轮询兜底**（备用机制）
3. **定期对账检查**（一致性验证）
4. **手动同步工具**（紧急修复）

### WebSocket 实时同步

**触发条件**：
- `BYBIT_PRIVATE_WS_ENABLED=true`
- `EXECUTION_MODE=LIVE`
- 已配置 `BYBIT_API_KEY` 和 `BYBIT_API_SECRET`

**工作原理**：
- 订阅 Bybit private WebSocket：`order`, `execution`, `position`
- 实时接收订单状态更新（Filled, Cancelled, PartiallyFilled 等）
- 自动更新 `orders` 表的 `status` 字段
- 记录成交详情到 `fills` 表
- 发布 `execution_report` 事件到 Redis Streams

**优势**：
- 实时性强（毫秒级延迟）
- 减少 REST API 调用
- 自动处理订单状态变化

### REST API 轮询兜底

**触发条件**：
- 每 5 秒运行一次（`reconcile_open_orders_poll_interval_sec`）
- 仅在 LIVE 模式下运行
- 如果启用了 WS，会减少轮询频率（避免重复）

**工作原理**：
- 调用 `open_orders` API 查询所有订单状态
- 检查 TP1/TP2 是否成交
- 检测订单超时和部分成交
- 更新订单状态到数据库

### 定期持仓同步

**触发条件**：
- 每 10 秒运行一次
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

### 手动同步工具

**使用方法：**
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

### 一致性漂移检测

**触发条件**：
- `CONSISTENCY_DRIFT_ENABLED=true`（默认启用）
- 每 5 秒运行一次

**工作原理**：
- 比较 WebSocket 持仓快照 (`meta.ws_position.size`) 与数据库持仓 (`qty_total`)
- 如果漂移超过阈值（`consistency_drift_threshold_pct`，默认 10%），则：
  - 发布 `CONSISTENCY_DRIFT` 风险事件
  - 记录到 `risk_events` 表
  - 在窗口期内（`consistency_drift_window_ms`，默认 5 分钟）只报警一次

---

## 🔍 问题排查

### 问题1：trade_plan 注入后没有生成 execution_report

#### 症状
- trade_plan 成功注入到 Redis Streams
- 等待后没有生成 execution_report
- API 查询返回空结果或错误

#### 排查步骤

**1. 检查执行服务日志**

```bash
# 查看执行服务最新日志
docker compose logs execution --tail 100

# 查看是否有错误
docker compose logs execution | grep -i "error\|exception\|traceback" | tail -20

# 实时监控日志
docker compose logs -f execution
```

**2. 检查执行模式**

```bash
# 检查当前执行模式
curl http://localhost:8000/v1/config | python3 -m json.tool | grep EXECUTION_MODE

# 如果是 LIVE 模式，需要配置 Bybit API
# 建议：先使用 PAPER 模式测试
```

**重要**：如果执行模式是 `LIVE`，但没有配置 `BYBIT_API_KEY` 和 `BYBIT_API_SECRET`，执行会失败。

**3. 检查 Redis Streams 消费者状态**

```bash
# 检查 trade_plan 消费者组状态
redis-cli XINFO GROUPS stream:trade_plan

# 检查是否有 pending 消息
redis-cli XPENDING stream:trade_plan bot-group

# 查看消费者列表
redis-cli XINFO CONSUMERS stream:trade_plan bot-group
```

如果看到大量 pending 消息，说明消费者可能没有正常处理。

**4. 检查执行服务是否正常运行**

```bash
# 检查健康状态
curl http://localhost:8003/health

# 应该返回：
# {
#   "env": "prod",
#   "service": "execution-service",
#   "redis_ok": true,
#   "db_url_present": true,
#   "execution_mode": "LIVE" 或 "PAPER"
# }
```

### 问题2：API 返回 "Not Found"

#### 症状
- API 请求返回 `{"detail": "Not Found"}`
- 而不是预期的 `{"items": [...]}`

#### 排查步骤

**1. 检查 API 路由**

```bash
# 测试健康检查接口（应该总是可用）
curl http://localhost:8000/health

# 测试配置接口
curl http://localhost:8000/v1/config

# 测试带参数的接口（注意 URL 编码）
curl "http://localhost:8000/v1/trade-plans?limit=10"
```

**2. 检查数据库连接**

API 返回 "Not Found" 可能是因为数据库查询失败。检查：

```bash
# 检查数据库连接
psql -U postgres -d trading-ci -c "SELECT COUNT(*) FROM trade_plans;"

# 如果表不存在，运行迁移
python -m scripts.init_db
```

**3. 检查 API 服务日志**

```bash
# 查看 API 服务日志
docker compose logs api --tail 50

# 查看错误日志
docker compose logs api | grep -i "error\|exception" | tail -20
```

### 问题3：订单未创建

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

### 问题4：订单被拒绝

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

### 问题5：数据库与交易所不一致

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

### 完整排查流程

**步骤1：运行诊断脚本**

```bash
docker compose exec execution python -m scripts.trading_test_tool diagnose --symbol BTCUSDT --side BUY
```

**步骤2：检查服务状态**

```bash
# 检查所有服务健康状态
for port in 8000 8001 8002 8003 8004; do
  echo "检查端口 $port:"
  curl -s http://localhost:$port/health | python3 -m json.tool || echo "失败"
  echo ""
done
```

**步骤3：检查 Redis Streams**

```bash
# 检查所有关键 Streams
for stream in bar_close signal trade_plan execution_report risk_event dlq; do
  echo "=== stream:$stream ==="
  redis-cli XREVRANGE stream:$stream + - COUNT 3
  echo ""
done
```

**步骤4：检查数据库**

```bash
# 检查关键表的数据量
psql -U postgres -d trading-ci <<EOF
SELECT 
  'trade_plans' as table_name, COUNT(*) as count FROM trade_plans
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'positions', COUNT(*) FROM positions
UNION ALL
SELECT 'execution_reports', COUNT(*) FROM execution_reports;
EOF
```

**步骤5：查看服务日志**

```bash
# 查看所有服务的错误日志
for service in api marketdata strategy execution notifier; do
  echo "=== $service 服务错误 ==="
  docker compose logs $service | grep -i "error\|exception" | tail -5
  echo ""
done
```

### 快速修复检查清单

- [ ] 所有服务正常运行（`docker compose ps`）
- [ ] 数据库连接正常（`psql -U postgres -d trading-ci -c "SELECT 1;"`）
- [ ] Redis 连接正常（`redis-cli ping`）
- [ ] 执行模式设置为 PAPER（测试时）
- [ ] 数据库迁移已运行（`python -m scripts.init_db`）
- [ ] Redis Streams 已初始化（`python -m scripts.init_streams`）
- [ ] 执行服务日志中没有错误
- [ ] trade_plan 成功注入到 Redis Streams
- [ ] 消费者组正常消费消息

---

## 📚 相关文档

- `scripts/trading_test_tool.py` - 统一测试工具（所有测试功能）
- `CHANGELOG.md` - 变更日志
