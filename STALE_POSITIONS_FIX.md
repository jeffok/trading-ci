# 无效持仓问题说明和解决方案

## 🔍 问题描述

你在 Bybit 交易所中没有看到持仓，但系统却检测到了持仓并阻止了新订单。这是因为：

**数据库中的持仓状态与交易所实际状态不一致**

## 📋 原因分析

### 1. 持仓同步只在 LIVE 模式下运行

查看代码 `services/execution/position_sync.py`：

```python
def sync_positions(database_url: str, redis_url: str) -> None:
    if settings.execution_mode != "live":  # ⚠️ 关键：只在 LIVE 模式运行
        return
    # ... 同步逻辑
```

**这意味着**：
- 如果你之前使用 `PAPER` 或 `BACKTEST` 模式测试
- 数据库中可能留下了 `status='OPEN'` 的持仓记录
- 这些持仓在交易所中实际不存在（因为是模拟交易）

### 2. 持仓同步的工作原理

持仓同步每 10 秒运行一次（`services/execution/worker.py`）：

```python
async def run_position_sync_loop() -> None:
    while True:
        try:
            sync_positions(settings.database_url, settings.redis_url)
        except Exception as e:
            logger.warning(f"position_sync_failed: {e}")
        await asyncio.sleep(10.0)
```

同步逻辑：
1. 查询数据库中所有 `status='OPEN'` 的持仓
2. 调用 Bybit API 查询交易所实际持仓
3. 如果交易所中 `size=0`（已关闭），更新数据库为 `CLOSED`

### 3. 为什么会出现不一致

可能的原因：
- ✅ 之前使用 PAPER/BACKTEST 模式测试，留下了模拟持仓
- ✅ 手动在交易所平仓，但数据库未同步
- ✅ 持仓同步失败（API 错误、网络问题等）
- ✅ 执行模式切换（从 PAPER 切换到 LIVE）时未清理

## 🔧 解决方案

### 方案1：使用 Shell 脚本（推荐，最简单）

我已经创建了 Shell 脚本版本，不需要 Python 依赖：

```bash
# 1. 查看数据库中的 OPEN 持仓（不修改）
./scripts/fix_stale_positions_simple.sh --dry-run

# 2. 清理所有 OPEN 持仓（谨慎使用）
./scripts/fix_stale_positions_simple.sh --force

# 3. 只清理特定交易对的持仓
./scripts/fix_stale_positions_simple.sh --symbol BTCUSDT

# 在 Docker 容器中运行：
docker compose exec execution bash scripts/fix_stale_positions_simple.sh --dry-run
```

### 方案2：使用 SQL 脚本（直接操作数据库）

```bash
# 1. 查看 OPEN 持仓
psql -U postgres -d trading-ci -f scripts/fix_stale_positions.sql

# 2. 清理所有 OPEN 持仓
psql -U postgres -d trading-ci -c "
UPDATE positions 
SET status='CLOSED', 
    updated_at=now(), 
    closed_at_ms=extract(epoch from now())::bigint * 1000,
    exit_reason='MANUAL_CLEANUP' 
WHERE status='OPEN';"

# 3. 只清理特定交易对
psql -U postgres -d trading-ci -c "
UPDATE positions 
SET status='CLOSED', 
    updated_at=now(), 
    closed_at_ms=extract(epoch from now())::bigint * 1000,
    exit_reason='MANUAL_CLEANUP' 
WHERE status='OPEN' AND symbol='BTCUSDT';"
```

### 方案3：使用 Python 脚本（在 Docker 容器中）

```bash
# 在 Docker 容器中运行（推荐）
docker compose exec execution python -m scripts.fix_stale_positions --dry-run
docker compose exec execution python -m scripts.fix_stale_positions --force

# 或本地运行（需要安装依赖）
pip install -r requirements.txt
python -m scripts.fix_stale_positions --dry-run
```

### 方案2：手动查询和清理

#### 步骤1：查询数据库中的 OPEN 持仓

```bash
# 使用 API
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool

# 或直接查询数据库
psql -U postgres -d trading-ci -c "
SELECT position_id, symbol, timeframe, side, qty_total, status, created_at 
FROM positions 
WHERE status='OPEN' 
ORDER BY created_at DESC;"
```

#### 步骤2：检查 Bybit 实际持仓

在 Bybit 交易所界面或使用 API 检查实际持仓。

#### 步骤3：手动清理无效持仓

```sql
-- 查看要清理的持仓
SELECT position_id, symbol, timeframe, side, idempotency_key
FROM positions 
WHERE status='OPEN';

-- 清理特定持仓（替换 position_id）
UPDATE positions 
SET status='CLOSED', 
    updated_at=now(), 
    closed_at_ms=extract(epoch from now())::bigint * 1000,
    exit_reason='MANUAL_CLEANUP'
WHERE position_id='your_position_id';

-- 或清理所有 OPEN 持仓（谨慎使用）
UPDATE positions 
SET status='CLOSED', 
    updated_at=now(), 
    closed_at_ms=extract(epoch from now())::bigint * 1000,
    exit_reason='STALE_CLEANUP'
WHERE status='OPEN';
```

### 方案3：等待自动同步（如果使用 LIVE 模式）

如果你现在使用的是 LIVE 模式，持仓同步会自动运行：

```bash
# 查看持仓同步日志
docker compose logs execution | grep -i "position_sync"

# 应该能看到类似这样的日志：
# position_sync: checking BTCUSDT...
# position_sync: exchange closed, updating DB...
```

**注意**：自动同步每 10 秒运行一次，可能需要等待。

## 🚀 快速修复步骤

### 如果当前是 LIVE 模式

```bash
# 1. 运行修复脚本检查并清理
python -m scripts.fix_stale_positions --check-bybit

# 2. 验证清理结果
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool
```

### 如果当前是 PAPER/BACKTEST 模式

```bash
# 1. 查看无效持仓
python -m scripts.fix_stale_positions --dry-run

# 2. 强制清理（因为无法检查交易所）
python -m scripts.fix_stale_positions --force

# 3. 验证清理结果
curl "http://localhost:8000/v1/positions?limit=10" | python3 -m json.tool
```

## 📊 验证修复

修复后，验证：

```bash
# 1. 检查数据库中没有 OPEN 持仓
psql -U postgres -d trading-ci -c "
SELECT COUNT(*) as open_count 
FROM positions 
WHERE status='OPEN';"

# 应该返回 0

# 2. 重新测试下单
python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 20

# 3. 应该不再出现 position_mutex_blocked 错误
```

## 🔍 预防措施

### 1. 切换模式前清理

在从 PAPER/BACKTEST 切换到 LIVE 前：

```bash
# 清理所有 OPEN 持仓
python -m scripts.fix_stale_positions --force
```

### 2. 定期检查

```bash
# 定期运行检查脚本
python -m scripts.fix_stale_positions --check-bybit --dry-run
```

### 3. 监控持仓同步

```bash
# 查看持仓同步是否正常工作
docker compose logs execution | grep -i "position_sync\|POSITION_SYNC"
```

## 📝 相关配置

持仓同步相关配置（`.env`）：

```bash
# 执行模式（影响持仓同步是否运行）
EXECUTION_MODE=LIVE  # 或 PAPER/BACKTEST

# Bybit API（持仓同步需要）
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret
BYBIT_REST_BASE_URL=https://api.bybit.com
BYBIT_CATEGORY=linear
```

## ⚠️ 注意事项

1. **强制清理要谨慎**：`--force` 会清理所有 OPEN 持仓，包括可能有效的持仓
2. **LIVE 模式优先**：如果使用 LIVE 模式，优先使用 `--check-bybit` 检查交易所
3. **备份数据**：清理前可以备份数据库
4. **检查日志**：清理后检查执行服务日志，确认没有异常

## 🆘 如果仍有问题

如果清理后仍有问题：

1. **检查执行模式**：
   ```bash
   curl http://localhost:8000/v1/config | python3 -m json.tool | grep EXECUTION_MODE
   ```

2. **检查持仓同步日志**：
   ```bash
   docker compose logs execution | grep -i "position_sync" | tail -20
   ```

3. **手动查询数据库**：
   ```bash
   psql -U postgres -d trading-ci -c "SELECT * FROM positions WHERE status='OPEN';"
   ```

---

**总结**：这是数据库与交易所状态不一致导致的。使用修复脚本可以快速清理无效持仓，恢复正常的交易流程。
