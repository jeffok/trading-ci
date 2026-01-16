# 信号生成诊断指南

## 🔍 为什么没有信号生成？

信号生成需要满足以下**所有条件**：

### 1. 市场数据充足 ✅
- **要求**：至少需要 **120 根 K 线**
- **检查**：数据库中的 `bars` 表是否有足够的数据

### 2. 三段背离检测 ✅
- **要求**：MACD histogram 必须形成三段顶/底背离结构
- **说明**：这是信号生成的核心条件，必须满足

### 3. Vegas 状态匹配 ✅
- **要求**：
  - LONG 信号需要 Vegas 状态为 **Bullish**
  - SHORT 信号需要 Vegas 状态为 **Bearish**
- **说明**：Vegas 状态必须与信号方向一致

### 4. 确认项足够 ✅
- **要求**：至少命中 **MIN_CONFIRMATIONS** 个确认项（默认 2 个）
- **确认项类型**：
  - `ENGULFING`：吞没形态
  - `RSI_DIV`：RSI 背离
  - `OBV_DIV`：OBV 背离
  - `FVG_PROXIMITY`：FVG 接近

---

## 🛠️ 快速诊断

### 方法1：使用诊断工具（推荐）

```bash
# 诊断指定交易对和时间框架
docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
    --symbol BTCUSDT \
    --timeframe 1h
```

### 方法2：直接运行诊断脚本

```bash
docker compose exec execution python -m scripts.diagnose_signals \
    --symbol BTCUSDT \
    --timeframe 1h
```

---

## 📊 诊断工具检查项

诊断工具会检查以下内容：

1. **市场数据检查**
   - K 线数量是否足够（>= 120）
   - 最新 K 线时间和价格

2. **三段背离检测**
   - 是否检测到三段背离
   - 背离方向和关键点信息

3. **Vegas 状态检查**
   - 当前 Vegas 状态
   - 是否与信号方向匹配

4. **确认项检查**
   - 每个确认项的命中情况
   - 命中数量是否足够

5. **策略服务状态**
   - Redis 连接
   - bar_close 事件是否正常
   - 信号事件历史

6. **数据库信号检查**
   - 历史信号记录
   - 信号生成频率

7. **配置检查**
   - MIN_CONFIRMATIONS
   - AUTO_TIMEFRAMES
   - MONITOR_TIMEFRAMES

---

## 🔧 常见问题解决

### 问题1：K 线数量不足

**症状**：诊断显示 "K 线数量不足！需要至少 120 根"

**解决**：
```bash
# 检查数据库中的 K 线数量
docker compose exec execution python -c "
from libs.common.config import settings
from services.strategy.repo import get_bars
bars = get_bars(settings.database_url, symbol='BTCUSDT', timeframe='1h', limit=500)
print(f'K 线数量: {len(bars)}')
"

# 如果数量不足，检查市场数据服务
docker compose logs marketdata --tail 100

# 检查配置的交易对和时间框架
grep MARKETDATA_SYMBOLS .env
grep MARKETDATA_TIMEFRAMES .env
```

### 问题2：未检测到三段背离

**症状**：诊断显示 "未检测到三段背离"

**说明**：
- 三段背离是信号生成的前提条件
- 需要 MACD histogram 形成特定的三段结构
- 这是市场条件，不是系统问题

**建议**：
- 等待市场形成三段背离结构
- 检查其他交易对是否有信号
- 查看历史信号，了解信号生成频率

### 问题3：Vegas 状态不匹配

**症状**：诊断显示 "Vegas 状态不匹配"

**说明**：
- LONG 信号需要 Bullish
- SHORT 信号需要 Bearish
- 这是策略规则，确保信号与趋势一致

**建议**：
- 等待市场趋势与信号方向一致
- 检查其他时间框架的 Vegas 状态

### 问题4：确认项不足

**症状**：诊断显示 "确认项不足！需要至少 X 个，但只命中 Y 个"

**说明**：
- 需要至少命中 `MIN_CONFIRMATIONS` 个确认项（默认 2 个）
- 确认项包括：ENGULFING, RSI_DIV, OBV_DIV, FVG_PROXIMITY

**建议**：
- 等待更多确认项命中
- 如果经常不足，可以考虑降低 `MIN_CONFIRMATIONS`（不推荐）
- 检查策略逻辑是否正确

### 问题5：没有 bar_close 事件

**症状**：诊断显示 "没有 bar_close 事件！"

**解决**：
```bash
# 检查市场数据服务
docker compose logs marketdata --tail 100

# 检查服务是否运行
docker compose ps marketdata

# 检查配置
grep MARKETDATA_SYMBOLS .env
grep MARKETDATA_TIMEFRAMES .env

# 重启市场数据服务
docker compose restart marketdata
```

### 问题6：策略服务未运行

**症状**：所有条件都满足，但仍然没有信号

**解决**：
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

---

## 📈 检查信号生成历史

### 查看数据库中的信号

```bash
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

### 查看 Redis Streams 中的信号

```bash
docker compose exec execution python -c "
import redis
from libs.common.config import settings

r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
msgs = r.xrevrange('stream:signal', '+', '-', count=10)
print(f'最近 {len(msgs)} 个信号事件：')
for msg_id, fields in msgs:
    import json
    data = json.loads(fields.get('data', '{}'))
    payload = data.get('payload', {})
    print(f'  {payload.get(\"symbol\")} {payload.get(\"timeframe\")} {payload.get(\"bias\")} | hits={payload.get(\"confirmations\", {}).get(\"hit_count\", 0)}')
"
```

---

## ⚙️ 配置参数

### 关键配置

```bash
# 最小确认项数量（默认 2）
MIN_CONFIRMATIONS=2

# 自动下单时间框架（只有这些时间框架会生成 trade_plan）
AUTO_TIMEFRAMES=1h,4h,1d

# 监控时间框架（只生成 signal，不生成 trade_plan）
MONITOR_TIMEFRAMES=15m,30m,8h

# 市场数据配置
MARKETDATA_SYMBOLS=BTCUSDT,ETHUSDT,...
MARKETDATA_TIMEFRAMES=15m,30m,1h,4h,8h,1d
```

---

## 💡 最佳实践

1. **定期运行诊断**：每天运行一次诊断，了解系统状态
2. **监控信号生成频率**：了解信号生成的正常频率
3. **检查多个交易对**：不同交易对的信号生成频率可能不同
4. **检查多个时间框架**：不同时间框架的信号生成频率可能不同
5. **查看历史信号**：了解信号生成的历史模式

---

## 🆘 如果仍然没有信号

1. **运行完整诊断**：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool diagnose-signals \
       --symbol BTCUSDT \
       --timeframe 1h
   ```

2. **检查服务日志**：
   ```bash
   docker compose logs strategy --tail 200 | grep -i "error\|warning\|signal"
   docker compose logs marketdata --tail 200 | grep -i "error\|warning\|bar_close"
   ```

3. **检查数据库**：
   ```bash
   # 检查 K 线数据
   docker compose exec execution python -c "
   from libs.common.config import settings
   from services.strategy.repo import get_bars
   for symbol in ['BTCUSDT', 'ETHUSDT']:
       for tf in ['1h', '4h', '1d']:
           bars = get_bars(settings.database_url, symbol=symbol, timeframe=tf, limit=500)
           print(f'{symbol} {tf}: {len(bars)} bars')
   "
   ```

4. **联系支持**：提供完整的诊断结果和日志
