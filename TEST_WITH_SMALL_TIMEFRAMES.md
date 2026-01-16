# 使用小时间框架测试指南

## 🎯 测试目标

使用 1分钟、5分钟等小时间框架快速验证系统是否正常运行。

## ⚙️ 配置修改

### 方法1：只测试信号生成（推荐，安全）

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

### 方法2：完整测试（包括下单，需谨慎）

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

## 📋 配置说明

### 时间框架配置说明

1. **MARKETDATA_TIMEFRAMES**：
   - 市场数据服务订阅的时间框架
   - 必须包含所有需要的时间框架

2. **MONITOR_TIMEFRAMES**：
   - 只生成 `signal`，不生成 `trade_plan`
   - 用于监控和测试信号生成

3. **AUTO_TIMEFRAMES**：
   - 生成 `signal` 和 `trade_plan`
   - 只有这些时间框架会触发真实下单

### 支持的时间框架格式

- `1m`：1分钟
- `5m`：5分钟
- `15m`：15分钟
- `30m`：30分钟
- `1h`：1小时
- `4h`：4小时
- `8h`：8小时
- `1d`：1天

## 🚀 测试步骤

### 步骤1：修改配置

```bash
# 编辑 .env 文件
vim .env

# 或者使用 sed 快速修改
sed -i 's/^MARKETDATA_TIMEFRAMES=.*/MARKETDATA_TIMEFRAMES=1m,5m,15m,30m,1h,4h,8h,1d/' .env
sed -i 's/^MONITOR_TIMEFRAMES=.*/MONITOR_TIMEFRAMES=1m,5m,15m,30m,8h/' .env
```

### 步骤2：重启服务

```bash
# 重启市场数据服务（加载新的时间框架配置）
docker compose restart marketdata

# 重启策略服务（加载新的时间框架配置）
docker compose restart strategy

# 查看服务状态
docker compose ps
```

### 步骤3：监控日志

```bash
# 监控市场数据服务（查看是否正常接收 1m、5m K 线）
docker compose logs -f marketdata | grep -i "1m\|5m\|bar_close"

# 监控策略服务（查看是否生成信号）
docker compose logs -f strategy | grep -i "signal\|divergence"

# 监控执行服务（如果添加到 AUTO_TIMEFRAMES，查看是否下单）
docker compose logs -f execution | grep -i "trade_plan\|order"
```

### 步骤4：诊断信号生成

```bash
# 诊断 1分钟时间框架
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1m

# 诊断 5分钟时间框架
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 5m
```

### 步骤5：检查信号和交易计划

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
            WHERE timeframe IN ('1m', '5m')
            ORDER BY created_at DESC
            LIMIT 20
        ''')
        rows = cur.fetchall()
        print(f'最近 {len(rows)} 个 1m/5m 信号：')
        for row in rows:
            print(f'  {row[0]} {row[1]} {row[2]} | hits={row[3]} | {row[5]} | {row[6]}')
"
```

```bash
# 查看交易计划（如果添加到 AUTO_TIMEFRAMES）
docker compose exec execution python -c "
from libs.common.config import settings
from libs.db.pg import get_conn

with get_conn(settings.database_url) as conn:
    with conn.cursor() as cur:
        cur.execute('''
            SELECT plan_id, symbol, timeframe, side, status, created_at
            FROM trade_plans
            WHERE timeframe IN ('1m', '5m')
            ORDER BY created_at DESC
            LIMIT 20
        ''')
        rows = cur.fetchall()
        print(f'最近 {len(rows)} 个 1m/5m 交易计划：')
        for row in rows:
            print(f'  {row[0]} {row[1]} {row[2]} {row[3]} {row[4]} | {row[5]}')
"
```

## 📊 预期结果

### 正常情况

1. **市场数据服务**：
   - 正常接收 1m、5m K 线数据
   - 正常发布 `bar_close` 事件

2. **策略服务**：
   - 正常处理 `bar_close` 事件
   - 当满足条件时生成 `signal`
   - 如果添加到 `AUTO_TIMEFRAMES`，还会生成 `trade_plan`

3. **执行服务**（如果添加到 AUTO_TIMEFRAMES）：
   - 正常接收 `trade_plan`
   - 执行下单流程

### 小时间框架的优势

- ✅ **更快的事件频率**：1分钟 = 每小时 60 个 bar_close 事件
- ✅ **更容易形成三段背离**：小时间框架更容易满足条件
- ✅ **快速验证系统**：可以在短时间内验证整个流程

### 注意事项

- ⚠️ **信号质量**：小时间框架的信号可能不如大时间框架稳定
- ⚠️ **交易频率**：如果添加到 `AUTO_TIMEFRAMES`，会产生更多订单
- ⚠️ **测试目的**：建议只用于测试，实盘交易建议使用大时间框架（1h、4h、1d）

## 🔧 故障排查

### 问题1：没有接收到 1m、5m K 线

**检查**：
```bash
# 检查市场数据服务日志
docker compose logs marketdata --tail 100 | grep -i "1m\|5m\|error"

# 检查配置是否正确加载
docker compose exec marketdata python -c "
from services.marketdata.config import get_marketdata_settings
settings = get_marketdata_settings()
print('Timeframes:', settings.timeframes)
"
```

### 问题2：没有生成信号

**检查**：
```bash
# 运行诊断工具
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1m

# 检查策略服务日志
docker compose logs strategy --tail 100 | grep -i "error\|warning"
```

### 问题3：信号生成但没下单

**检查**：
```bash
# 确认是否添加到 AUTO_TIMEFRAMES
grep AUTO_TIMEFRAMES .env

# 检查执行服务日志
docker compose logs execution --tail 100 | grep -i "trade_plan\|rejected"
```

## 📝 测试完成后

测试完成后，建议恢复生产配置：

```bash
# 恢复生产配置
MARKETDATA_TIMEFRAMES=15m,30m,1h,4h,8h,1d
MONITOR_TIMEFRAMES=15m,30m,8h
AUTO_TIMEFRAMES=1h,4h,1d

# 重启服务
docker compose restart marketdata strategy execution
```

## 💡 建议

1. **先测试信号生成**：只添加到 `MONITOR_TIMEFRAMES`，验证信号生成正常
2. **再测试下单**：确认信号生成正常后，再考虑添加到 `AUTO_TIMEFRAMES`
3. **使用小金额**：如果测试下单，使用非常小的 `RISK_PCT`（如 0.001）
4. **监控日志**：实时监控各服务日志，及时发现问题
5. **及时恢复**：测试完成后及时恢复生产配置
