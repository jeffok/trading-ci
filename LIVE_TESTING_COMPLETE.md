# 实盘交易完整测试指南

## ⚠️ 重要安全提示

**实盘交易涉及真实资金，请务必谨慎操作！**

1. ✅ **先清理无效持仓**：确保数据库状态与交易所一致
2. ✅ **使用小金额测试**：设置较小的 `RISK_PCT`（如 0.001 = 0.1%）
3. ✅ **启用所有风控**：确保所有保护机制已启用
4. ✅ **准备紧急停止方案**：知道如何快速停止交易
5. ✅ **监控日志**：实时监控执行服务日志
6. ✅ **在交易所验证**：所有操作后必须在 Bybit 交易所验证

---

## 📋 测试前准备清单

### ✅ 步骤1：环境检查

```bash
# 1.1 检查所有服务是否运行
docker compose ps

# 应该看到所有服务状态为 "Up"
# - api-service (8000)
# - marketdata-service (8001)
# - strategy-service (8002)
# - execution-service (8003)
# - notifier-service (8004)
```

### ✅ 步骤2：配置检查

```bash
# 2.1 运行准备检查工具
docker compose exec execution python -m scripts.trading_test_tool prepare

# 应该看到：
# ✅ EXECUTION_MODE=LIVE
# ✅ Bybit API Key/Secret 已配置
# ✅ 执行服务健康检查通过
# ✅ 当前风险配置显示
```

**关键配置检查项：**
- [ ] `EXECUTION_MODE=LIVE`
- [ ] `BYBIT_API_KEY` 和 `BYBIT_API_SECRET` 已配置
- [ ] `RISK_PCT ≤ 0.001`（0.1%）
- [ ] `MAX_OPEN_POSITIONS=1`（建议）
- [ ] `ACCOUNT_KILL_SWITCH_ENABLED=true`
- [ ] `RISK_CIRCUIT_ENABLED=true`

### ✅ 步骤3：清理无效持仓

```bash
# 3.1 查看当前持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 3.2 如果有无效持仓，清理它们
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes

# 3.3 验证清理结果
docker compose exec execution python -m scripts.trading_test_tool positions
# 应该显示：没有找到 OPEN 持仓
```

### ✅ 步骤4：服务健康检查

```bash
# 4.1 检查所有服务健康状态
for port in 8000 8001 8002 8003 8004; do
  echo "=== 端口 $port ==="
  curl -s http://localhost:$port/health | python3 -m json.tool || echo "❌ 失败"
  echo ""
done

# 4.2 特别检查执行服务
curl http://localhost:8003/health | python3 -m json.tool
# 应该看到：{"env": "prod", "service": "execution-service", "execution_mode": "LIVE", ...}
```

### ✅ 步骤5：启动日志监控

**在另一个终端窗口**启动日志监控（重要！）：

```bash
# 5.1 监控执行服务日志（最重要）
docker compose logs -f execution

# 5.2 可选：同时监控其他服务
docker compose logs -f strategy
docker compose logs -f marketdata
```

---

## 🚀 完整测试流程

### 阶段1：准备阶段（Pre-Flight）

#### 1.1 环境验证

```bash
# 检查配置
docker compose exec execution python -m scripts.trading_test_tool prepare

# 检查持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 检查服务状态
docker compose ps
curl http://localhost:8003/health | python3 -m json.tool
```

**预期结果：**
- ✅ 所有检查通过
- ✅ 没有无效持仓
- ✅ 所有服务正常运行

#### 1.2 获取当前市场价格

```bash
# 方式1：通过 Bybit API（需要配置）
# 访问 https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT

# 方式2：查看 Bybit 交易所界面
# 登录 Bybit，查看 BTCUSDT 当前价格

# 方式3：查看数据库最新 bar
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
            print('未找到数据')
"
```

### 阶段2：执行测试下单

#### 2.1 执行测试下单

```bash
# 替换为实际的市场价格
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

#### 2.2 观察执行过程

在日志监控窗口中，你应该看到：

```
[INFO] 收到 trade_plan: plan_id=live-test-xxx
[INFO] 风险检查通过
[INFO] 创建订单: symbol=BTCUSDT, side=Buy, qty=0.003
[INFO] 订单创建成功: bybit_order_id=xxx
[INFO] 发布 execution_report: status=ORDER_FILLED
```

### 阶段3：验证结果

#### 3.1 查看订单

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

#### 3.2 查看持仓

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

#### 3.3 查看执行报告

```bash
# 通过 API 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=10" | python3 -m json.tool

# 查看指定 idempotency_key 的执行报告
# （需要从数据库查询或通过 API 过滤）
```

**验证项：**
- [ ] execution_report 已生成
- [ ] 报告状态正确（ORDER_FILLED/POSITION_OPENED 等）
- [ ] 报告包含正确的 plan_id 和 idempotency_key

#### 3.4 查看风险事件

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

#### 3.5 在 Bybit 交易所验证（最重要！）

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

### 阶段4：后续验证

#### 4.1 监控订单执行

```bash
# 持续监控订单状态
watch -n 5 'docker compose exec execution python -m scripts.trading_test_tool orders --limit 5'

# 或通过 API
watch -n 5 'curl -s "http://localhost:8000/v1/orders?limit=5" | python3 -m json.tool'
```

#### 4.2 监控持仓变化

```bash
# 持续监控持仓
watch -n 10 'docker compose exec execution python -m scripts.trading_test_tool positions'
```

#### 4.3 查看执行轨迹（可选）

```bash
# 获取 idempotency_key（从 test 命令输出中）
IDEM_KEY="idem-xxx"

# 查看执行轨迹
curl "http://localhost:8000/v1/execution-traces?idempotency_key=${IDEM_KEY}&limit=50" | python3 -m json.tool
```

#### 4.4 查看账户快照（可选）

```bash
# 获取今天的日期
TRADE_DATE=$(date +%Y-%m-%d)

# 查看账户快照
curl "http://localhost:8000/v1/account-snapshots?trade_date=${TRADE_DATE}&limit=10" | python3 -m json.tool
```

---

## 📊 测试检查清单

### 基础功能测试

- [ ] 所有服务正常启动
- [ ] 配置检查通过
- [ ] 没有无效持仓
- [ ] 服务健康检查通过

### 下单流程测试

- [ ] trade_plan 成功发布到 Redis Streams
- [ ] 执行服务成功消费 trade_plan
- [ ] 订单在 Bybit 交易所真实创建
- [ ] 订单状态正确更新
- [ ] 持仓在 Bybit 交易所真实创建
- [ ] 止损单在 Bybit 交易所正确设置
- [ ] 止盈单在 Bybit 交易所正确设置

### 数据一致性测试

- [ ] 数据库订单与交易所订单一致
- [ ] 数据库持仓与交易所持仓一致
- [ ] execution_report 正确生成
- [ ] 风险事件正确记录（如有）

### 风控功能测试

- [ ] 风险检查正常工作
- [ ] 如果触发风控，订单被正确拒绝
- [ ] 风险事件正确记录

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
交易对: [BTCUSDT]
方向: [BUY/SELL]
入场价格: [价格]
止损价格: [价格]
风险百分比: [RISK_PCT]

准备阶段:
- [ ] 环境检查通过
- [ ] 配置检查通过
- [ ] 无效持仓已清理
- [ ] 服务健康检查通过

执行阶段:
- [ ] trade_plan 成功发布
- [ ] 执行服务成功消费
- [ ] 订单在交易所创建
- [ ] 持仓在交易所创建
- [ ] 止损/止盈单已设置

验证阶段:
- [ ] 数据库订单正确
- [ ] 数据库持仓正确
- [ ] 交易所订单正确
- [ ] 交易所持仓正确
- [ ] execution_report 正确
- [ ] 无异常风险事件

问题记录:
[记录任何问题或异常]

备注:
[其他备注]
```

---

## 🎯 测试成功标准

1. ✅ **订单成功创建**：在 Bybit 交易所中能看到订单
2. ✅ **持仓成功创建**：在 Bybit 交易所中能看到持仓
3. ✅ **止损/止盈正确设置**：在 Bybit 交易所中能看到条件单
4. ✅ **数据一致性**：数据库记录与交易所状态一致
5. ✅ **无异常错误**：执行服务日志无错误，无异常风险事件

---

## 💡 最佳实践

1. **小金额测试**：首次测试使用最小金额（RISK_PCT=0.001）
2. **逐步增加**：确认系统正常后，再逐步增加金额
3. **实时监控**：测试过程中始终保持日志监控
4. **及时验证**：每个步骤后立即验证结果
5. **记录问题**：遇到问题及时记录，便于后续排查
6. **定期检查**：定期检查持仓状态和风险状态

---

## 📚 相关文档

- `scripts/README_TEST_TOOL.md` - 测试工具使用指南
- `LIVE_TRADING_GUIDE.md` - 实盘交易指南
- `TROUBLESHOOTING.md` - 问题排查指南
- `CHANGELOG.md` - 变更日志
