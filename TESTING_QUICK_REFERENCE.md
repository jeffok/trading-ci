# 测试快速参考

## 🚀 快速测试流程

### 1. 系统测试（5分钟）

```bash
# 1.1 检查服务状态
docker compose ps

# 1.2 初始化数据库和 Redis Streams
docker compose exec execution python -m scripts.init_db
docker compose exec execution python -m scripts.init_streams

# 1.3 运行准备检查
docker compose exec execution python -m scripts.trading_test_tool prepare

# 1.4 数据库完整性检查
docker compose exec execution python -m scripts.check_db_integrity
```

### 2. 功能测试（10分钟）

```bash
# 2.1 切换到 PAPER 模式
# 编辑 .env: EXECUTION_MODE=PAPER
docker compose restart execution

# 2.2 运行风控闸门测试（必须！）
docker compose exec execution python -m scripts.e2e_stage6_gates_test --reset-db

# 2.3 运行平仓测试
docker compose exec execution python -m scripts.e2e_stage2_close_test

# 2.4 测试下单（PAPER 模式）
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT --side BUY --entry-price 30000 --sl-price 29000
```

### 3. 实盘测试（15分钟）

```bash
# 3.1 切换到 LIVE 模式
# 编辑 .env: EXECUTION_MODE=LIVE, BYBIT_API_KEY=xxx, BYBIT_API_SECRET=xxx
docker compose restart execution

# 3.2 准备检查
docker compose exec execution python -m scripts.trading_test_tool prepare

# 3.3 清理无效持仓
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes

# 3.4 启动日志监控（另一个终端）
docker compose logs -f execution

# 3.5 执行测试下单
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT --side BUY --entry-price 30000 --sl-price 29000

# 3.6 验证结果
docker compose exec execution python -m scripts.trading_test_tool positions
docker compose exec execution python -m scripts.trading_test_tool orders

# 3.7 在 Bybit 交易所验证（必须！）
# 登录 Bybit → 查看订单和持仓
```

---

## 📋 常用命令

### 查看状态

```bash
# 查看持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 查看订单
docker compose exec execution python -m scripts.trading_test_tool orders

# 查看服务健康
docker compose exec execution python -m scripts.trading_test_tool prepare
```

### 清理操作

```bash
# 清理所有无效持仓
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes

# 清理指定持仓
docker compose exec execution python -m scripts.trading_test_tool clean <position_id>
```

### API 查询

```bash
# 查看订单
curl "http://localhost:8000/v1/orders?limit=10" | python3 -m json.tool

# 查看持仓
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool

# 查看执行报告
curl "http://localhost:8000/v1/execution-reports?limit=10" | python3 -m json.tool

# 查看风险事件
TRADE_DATE=$(date +%Y-%m-%d)
curl "http://localhost:8000/v1/risk-events?trade_date=${TRADE_DATE}&limit=20" | python3 -m json.tool
```

---

## ⚠️ 重要提醒

1. **实盘测试前必须完成功能测试**
2. **使用小金额测试**：RISK_PCT ≤ 0.001（0.1%）
3. **实时监控日志**：`docker compose logs -f execution`
4. **在交易所验证**：所有操作后必须在 Bybit 验证
5. **准备紧急停止方案**：知道如何快速停止

---

## 🛑 紧急停止

```bash
# 1. 停止执行服务
docker compose stop execution

# 2. 在 Bybit 交易所手动平仓

# 3. 清理数据库状态
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes
```

---

详细文档：`COMPLETE_TESTING_GUIDE.md`
