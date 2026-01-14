# 问题排查指南

## 问题1：trade_plan 注入后没有生成 execution_report

### 症状
- trade_plan 成功注入到 Redis Streams
- 等待后没有生成 execution_report
- API 查询返回空结果或错误

### 排查步骤

#### 1. 检查执行服务日志

```bash
# 查看执行服务最新日志
docker compose logs execution --tail 100

# 查看是否有错误
docker compose logs execution | grep -i "error\|exception\|traceback" | tail -20

# 实时监控日志
docker compose logs -f execution
```

#### 2. 检查执行模式

```bash
# 检查当前执行模式
curl http://localhost:8000/v1/config | python3 -m json.tool | grep EXECUTION_MODE

# 如果是 LIVE 模式，需要配置 Bybit API
# 建议：先使用 PAPER 模式测试
```

**重要**：如果执行模式是 `LIVE`，但没有配置 `BYBIT_API_KEY` 和 `BYBIT_API_SECRET`，执行会失败。

#### 3. 检查 Redis Streams 消费者状态

```bash
# 检查 trade_plan 消费者组状态
redis-cli XINFO GROUPS stream:trade_plan

# 检查是否有 pending 消息
redis-cli XPENDING stream:trade_plan bot-group

# 查看消费者列表
redis-cli XINFO CONSUMERS stream:trade_plan bot-group
```

如果看到大量 pending 消息，说明消费者可能没有正常处理。

#### 4. 检查执行服务是否正常运行

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

#### 5. 手动测试执行流程

```bash
# 1. 注入 trade_plan
python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 20

# 2. 同时监控执行服务日志
docker compose logs -f execution

# 3. 检查 Redis Streams
redis-cli XREVRANGE stream:execution_report + - COUNT 5
redis-cli XREVRANGE stream:risk_event + - COUNT 5
```

### 常见原因和解决方案

#### 原因1：执行模式是 LIVE 但没有配置 API Key

**解决方案**：
```bash
# 修改 .env 文件
EXECUTION_MODE=PAPER
BACKTEST_EQUITY=10000

# 重启服务
docker compose restart execution
```

#### 原因2：执行服务消费者线程崩溃

**解决方案**：
```bash
# 查看详细错误日志
docker compose logs execution | grep -A 20 "traceback\|Traceback"

# 重启执行服务
docker compose restart execution

# 检查服务是否正常启动
docker compose ps execution
```

#### 原因3：数据库连接失败

**解决方案**：
```bash
# 检查数据库连接
psql -U postgres -d trading-ci -c "SELECT 1;"

# 检查环境变量
docker compose exec execution env | grep DATABASE_URL

# 如果连接失败，检查 .env 文件中的 DATABASE_URL
```

#### 原因4：Redis 连接失败

**解决方案**：
```bash
# 检查 Redis 连接
redis-cli ping

# 检查环境变量
docker compose exec execution env | grep REDIS_URL

# 如果连接失败，检查 .env 文件中的 REDIS_URL
```

---

## 问题2：API 返回 "Not Found"

### 症状
- API 请求返回 `{"detail": "Not Found"}`
- 而不是预期的 `{"items": [...]}`

### 排查步骤

#### 1. 检查 API 路由

```bash
# 测试健康检查接口（应该总是可用）
curl http://localhost:8000/health

# 测试配置接口
curl http://localhost:8000/v1/config

# 测试带参数的接口（注意 URL 编码）
curl "http://localhost:8000/v1/trade-plans?limit=10"
```

#### 2. 检查数据库连接

API 返回 "Not Found" 可能是因为数据库查询失败。检查：

```bash
# 检查数据库连接
psql -U postgres -d trading-ci -c "SELECT COUNT(*) FROM trade_plans;"

# 如果表不存在，运行迁移
python -m scripts.init_db
```

#### 3. 检查 API 服务日志

```bash
# 查看 API 服务日志
docker compose logs api --tail 50

# 查看错误日志
docker compose logs api | grep -i "error\|exception" | tail -20
```

### 常见原因和解决方案

#### 原因1：数据库表不存在

**解决方案**：
```bash
# 运行数据库迁移
python -m scripts.init_db

# 或使用 Docker（会自动运行迁移）
docker compose up --build
```

#### 原因2：数据库连接配置错误

**解决方案**：
```bash
# 检查 .env 文件中的 DATABASE_URL
cat .env | grep DATABASE_URL

# 确保格式正确：
# DATABASE_URL=postgresql://用户名:密码@主机:端口/数据库名
```

#### 原因3：API 服务未正常启动

**解决方案**：
```bash
# 检查服务状态
docker compose ps api

# 重启 API 服务
docker compose restart api

# 查看启动日志
docker compose logs api | tail -50
```

---

## 问题3：replay_backtest.py 报错 "No module named 'libs'"

### 症状
```bash
python scripts/replay_backtest.py --symbol BTCUSDT --timeframe 60 --limit 500
# 报错：ModuleNotFoundError: No module named 'libs'
```

### 原因
脚本需要在项目根目录运行，且 Python 路径需要包含项目根目录。

### 解决方案

#### 方法1：使用 Python 模块方式运行（推荐）

```bash
# 在项目根目录运行
cd /path/to/trading-ci
python -m scripts.replay_backtest --symbol BTCUSDT --timeframe 60 --limit 500
```

#### 方法2：设置 PYTHONPATH

```bash
# 设置 PYTHONPATH
export PYTHONPATH=/path/to/trading-ci:$PYTHONPATH
python scripts/replay_backtest.py --symbol BTCUSDT --timeframe 60 --limit 500
```

#### 方法3：在 Docker 容器中运行

```bash
# 在容器中运行（推荐，环境一致）
docker compose exec execution python -m scripts.replay_backtest \
  --symbol BTCUSDT \
  --timeframe 60 \
  --limit 500 \
  --sleep-ms 10
```

---

## 问题4：jq 命令不存在

### 症状
```bash
curl http://localhost:8000/v1/trade-plans | jq
# 报错：-bash: jq: command not found
```

### 解决方案

#### 方法1：安装 jq

```bash
# CentOS/RHEL
yum install -y jq

# Ubuntu/Debian
apt-get install -y jq

# macOS
brew install jq
```

#### 方法2：使用 Python 代替 jq

```bash
# 使用 Python 格式化 JSON
curl http://localhost:8000/v1/trade-plans | python3 -m json.tool

# 或使用 Python 提取特定字段
curl -s http://localhost:8000/v1/trade-plans | \
  python3 -c "import sys, json; data=json.load(sys.stdin); print(json.dumps(data, indent=2))"
```

#### 方法3：直接查看原始 JSON

```bash
# 不使用 jq，直接查看
curl http://localhost:8000/v1/trade-plans
```

---

## 完整排查流程

### 步骤1：运行诊断脚本

```bash
# 运行诊断脚本（如果已创建）
docker compose exec execution python -m scripts.trading_test_tool diagnose --symbol BTCUSDT --side BUY
```

### 步骤2：检查服务状态

```bash
# 检查所有服务健康状态
for port in 8000 8001 8002 8003 8004; do
  echo "检查端口 $port:"
  curl -s http://localhost:$port/health | python3 -m json.tool || echo "失败"
  echo ""
done
```

### 步骤3：检查 Redis Streams

```bash
# 检查所有关键 Streams
for stream in bar_close signal trade_plan execution_report risk_event dlq; do
  echo "=== stream:$stream ==="
  redis-cli XREVRANGE stream:$stream + - COUNT 3
  echo ""
done
```

### 步骤4：检查数据库

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

### 步骤5：查看服务日志

```bash
# 查看所有服务的错误日志
for service in api marketdata strategy execution notifier; do
  echo "=== $service 服务错误 ==="
  docker compose logs $service | grep -i "error\|exception" | tail -5
  echo ""
done
```

---

## 快速修复检查清单

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

## 获取帮助

如果以上步骤都无法解决问题，请提供以下信息：

1. **服务日志**：
   ```bash
   docker compose logs > logs.txt
   ```

2. **配置信息**（脱敏后）：
   ```bash
   curl http://localhost:8000/v1/config > config.json
   ```

3. **Redis Streams 状态**：
   ```bash
   redis-cli XINFO GROUPS stream:trade_plan > redis_groups.txt
   ```

4. **数据库表结构**：
   ```bash
   psql -U postgres -d trading-ci -c "\d trade_plans" > schema.txt
   ```

5. **执行的具体命令和输出**
