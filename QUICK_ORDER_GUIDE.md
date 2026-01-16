# 快速下单测试指南

## 🚀 快速测试下单（推荐）

### 方法1：使用测试工具（最简单）

```bash
# 在 Docker 容器中执行
docker compose exec execution python -m scripts.trading_test_tool test \
    --symbol BTCUSDT \
    --side BUY \
    --timeframe 1h \
    --sl-distance-pct 0.02 \
    --auto-diagnose \
    --confirm \
    --wait-seconds 30
```

### 方法2：使用快速脚本

```bash
# 使用默认参数（BTCUSDT BUY）
./scripts/quick_test_order.sh

# 指定交易对和方向
./scripts/quick_test_order.sh ETHUSDT SELL
```

---

## 🔍 为什么没有订单？快速诊断

### 1. 检查配置和执行模式

```bash
# 检查配置
docker compose exec execution python -m scripts.trading_test_tool prepare

# 诊断下单失败原因
docker compose exec execution python -m scripts.trading_test_tool diagnose \
    --symbol BTCUSDT \
    --side BUY
```

### 2. 检查可能阻止下单的原因

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
from services.execution.kill_switch import is_kill_switch_on
print('Kill Switch:', is_kill_switch_on(settings.redis_url))
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
# 检查是否有信号生成
docker compose logs strategy | grep -i signal | tail -20

# 检查是否有交易计划
docker compose logs strategy | grep -i "trade_plan\|trade-plan" | tail -20

# 检查 Redis Streams 中的交易计划
docker compose exec execution python -c "
import redis
from libs.common.config import settings
r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
msgs = r.xrevrange('stream:trade_plan', '+', '-', count=5)
print('最近的交易计划:', len(msgs))
for msg in msgs:
    print('  -', msg[0])
"
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

# 如果订单价值太小或太大，会被拒绝
```

---

## 📊 检查系统状态

### 检查所有服务是否正常运行

```bash
# 检查服务状态
docker compose ps

# 检查各服务日志
docker compose logs marketdata --tail 50
docker compose logs strategy --tail 50
docker compose logs execution --tail 50
```

### 检查是否有信号生成

```bash
# 查看策略服务日志
docker compose logs strategy | grep -i "signal\|divergence\|vegas" | tail -30

# 检查数据库中的信号
docker compose exec execution python -c "
from libs.db.pg import get_conn
from libs.common.config import settings
conn = get_conn(settings.database_url)
rows = conn.execute('SELECT symbol, timeframe, bias, hit_count, created_at FROM signals ORDER BY created_at DESC LIMIT 10').fetchall()
print('最近的信号:')
for row in rows:
    print(f'  {row[0]} {row[1]} {row[2]} hits={row[3]} {row[4]}')
"
```

### 检查是否有交易计划生成

```bash
# 查看策略服务日志中的交易计划
docker compose logs strategy | grep -i "trade.*plan\|publish.*trade" | tail -30

# 检查数据库中的交易计划
docker compose exec execution python -c "
from libs.db.pg import get_conn
from libs.common.config import settings
conn = get_conn(settings.database_url)
rows = conn.execute('SELECT plan_id, symbol, timeframe, side, status, created_at FROM trade_plans ORDER BY created_at DESC LIMIT 10').fetchall()
print('最近的交易计划:')
for row in rows:
    print(f'  {row[0]} {row[1]} {row[2]} {row[3]} {row[4]} {row[5]}')
"
```

### 检查执行报告

```bash
# 查看执行报告（了解为什么被拒绝）
docker compose exec execution python -m scripts.trading_test_tool orders --limit 20

# 查看执行服务日志
docker compose logs execution | grep -i "rejected\|blocked\|cooldown\|max.*position" | tail -30
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

# 4. 风控配置
RISK_PCT=0.001  # 风险百分比
MAX_OPEN_POSITIONS=1  # 最大持仓数
ACCOUNT_KILL_SWITCH_ENABLED=true
RISK_CIRCUIT_ENABLED=true

# 5. 订单价值限制
MIN_ORDER_VALUE_USDT=50.0
MAX_ORDER_VALUE_USDT=1000.0
LEVERAGE=10
MARGIN_MODE=isolated

# 6. 冷却期（如果启用，止损后需要等待）
COOLDOWN_ENABLED=true
COOLDOWN_BARS_1H=2
COOLDOWN_BARS_4H=1
COOLDOWN_BARS_1D=1
```

---

## 🎯 快速测试下单步骤

### 步骤1：诊断问题

```bash
docker compose exec execution python -m scripts.trading_test_tool diagnose \
    --symbol BTCUSDT \
    --side BUY
```

### 步骤2：如果诊断通过，执行测试下单

```bash
docker compose exec execution python -m scripts.trading_test_tool test \
    --symbol BTCUSDT \
    --side BUY \
    --timeframe 1h \
    --auto-diagnose \
    --confirm \
    --wait-seconds 30
```

### 步骤3：验证订单

```bash
# 查看订单
docker compose exec execution python -m scripts.trading_test_tool orders

# 查看持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 查看执行日志
docker compose logs execution --tail 50
```

---

## 🔧 常见问题解决

### 问题1：诊断显示 "Kill Switch 已开启"

**解决**：
```bash
# 检查 kill switch 状态
docker compose exec execution python -c "
from libs.common.config import settings
from services.execution.kill_switch import is_kill_switch_on
r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
print('Kill Switch:', r.get('KILL_SWITCH'))
"

# 如果已开启，需要手动关闭（通过 API 或直接操作 Redis）
```

### 问题2：诊断显示 "达到最大持仓数"

**解决**：
```bash
# 查看当前持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 如果不需要，可以清理
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes
```

### 问题3：诊断显示 "在冷却期"

**解决**：
```bash
# 等待冷却期结束，或临时禁用冷却期
# 在 .env 中设置：
COOLDOWN_ENABLED=false

# 然后重启执行服务
docker compose restart execution
```

### 问题4：没有信号生成

**解决**：
```bash
# 检查策略服务是否正常运行
docker compose logs strategy --tail 50

# 检查市场数据是否正常
docker compose logs marketdata --tail 50

# 检查配置的交易对和时间框架
grep MARKETDATA_SYMBOLS .env
grep AUTO_TIMEFRAMES .env
```

---

## 📝 注意事项

1. **⚠️ 测试下单会真实下单**：确保金额设置合理（`RISK_PCT` 很小）
2. **⚠️ 检查执行模式**：确保 `EXECUTION_MODE=LIVE` 才会真实下单
3. **⚠️ 检查风控设置**：确保所有风控都已正确配置
4. **⚠️ 监控日志**：下单后立即查看日志确认结果

---

## 🆘 如果还是无法下单

1. **查看完整执行日志**：
   ```bash
   docker compose logs execution --tail 200 | grep -i "error\|reject\|block\|fail"
   ```

2. **检查数据库中的执行报告**：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool orders --limit 50
   ```

3. **检查 Redis Streams 中的事件**：
   ```bash
   # 检查交易计划是否被发布
   docker compose exec execution python -c "
   import redis
   from libs.common.config import settings
   r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
   msgs = r.xrevrange('stream:trade_plan', '+', '-', count=10)
   for msg_id, fields in msgs:
       print(f'Message ID: {msg_id}')
       print(f'  Symbol: {fields.get(\"payload\", {}).get(\"symbol\", \"N/A\")}')
   "
   ```

4. **联系支持**：提供完整的日志和诊断信息
