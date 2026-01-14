# 交易系统测试工具使用指南

## 概述

`trading_test_tool.py` 是**统一的测试工具**，整合了所有实盘测试功能：
- ✅ 准备检查（配置、服务状态）
- ✅ 查看持仓
- ✅ 清理持仓
- ✅ 执行测试下单
- ✅ 查看订单

**所有测试功能都在这个工具中，无需使用其他分散的脚本。**

## 快速开始

```bash
# 在容器内运行（推荐）
docker compose exec execution python -m scripts.trading_test_tool --help

# 或本地运行
python scripts/trading_test_tool.py --help
```

## 可用命令

### 1. prepare - 准备检查

检查配置、服务状态、风险设置等。

```bash
docker compose exec execution python -m scripts.trading_test_tool prepare
```

**功能：**
- ✅ 检查 EXECUTION_MODE 是否为 LIVE
- ✅ 检查 Bybit API Key/Secret 是否配置
- ✅ 检查服务健康状态
- ✅ 显示当前风险配置

### 2. positions - 查看持仓

查看所有 OPEN 持仓的详细信息。

```bash
# 基本查看
docker compose exec execution python -m scripts.trading_test_tool positions

# 详细信息（包含来源类型）
docker compose exec execution python -m scripts.trading_test_tool positions --detailed
```

**功能：**
- 显示所有 OPEN 持仓
- 显示持仓统计（总数、PAPER 模式、测试注入）
- 可选显示详细信息（包含来源类型）

### 3. clean - 清理持仓

清理无效的 OPEN 持仓。

```bash
# 清理所有 OPEN 持仓（需要确认）
docker compose exec execution python -m scripts.trading_test_tool clean --all

# 清理所有 OPEN 持仓（跳过确认）
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes

# 清理指定持仓
docker compose exec execution python -m scripts.trading_test_tool clean <position_id>
```

**功能：**
- 清理所有 OPEN 持仓
- 清理指定持仓（通过 position_id）
- 验证清理结果

### 4. test - 执行测试下单

⚠️ **会真实下单！**

```bash
# 基本用法（会提示确认）
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000

# 跳过确认（谨慎使用）
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000 \
  --confirm

# 自定义时间框架和等待时间
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol ETHUSDT \
  --side SELL \
  --entry-price 2000 \
  --sl-price 2100 \
  --timeframe 1h \
  --wait-seconds 60
```

**参数说明：**
- `--symbol`: 交易对（如 BTCUSDT, ETHUSDT）
- `--side`: 方向（BUY 做多 或 SELL 做空）
- `--entry-price`: 入场价格（建议使用当前市场价格）
- `--sl-price`: 止损价格
- `--timeframe`: 时间框架（可选，默认 15m）
- `--wait-seconds`: 等待执行的时间（可选，默认 30 秒）
- `--confirm`: 跳过确认提示（谨慎使用）

**功能：**
- 检查执行模式和 API 配置
- 构建并发布 trade_plan
- 检查执行结果（execution_report、risk_event）
- 提供验证步骤

### 5. orders - 查看订单

查看订单列表。

```bash
# 查看最新订单
docker compose exec execution python -m scripts.trading_test_tool orders

# 查看指定 idempotency_key 的订单
docker compose exec execution python -m scripts.trading_test_tool orders \
  --idempotency-key idem-xxx

# 限制返回数量
docker compose exec execution python -m scripts.trading_test_tool orders --limit 20
```

**功能：**
- 查看最新订单列表
- 按 idempotency_key 过滤
- 可限制返回数量

## 完整测试流程示例

### 步骤1：准备检查

```bash
docker compose exec execution python -m scripts.trading_test_tool prepare
```

### 步骤2：检查持仓

```bash
docker compose exec execution python -m scripts.trading_test_tool positions
```

如果有无效持仓，清理：

```bash
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes
```

### 步骤3：启动日志监控（另一个终端）

```bash
docker compose logs -f execution
```

### 步骤4：执行测试下单

```bash
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT \
  --side BUY \
  --entry-price 30000 \
  --sl-price 29000
```

### 步骤5：验证结果

```bash
# 查看持仓
docker compose exec execution python -m scripts.trading_test_tool positions

# 查看订单
docker compose exec execution python -m scripts.trading_test_tool orders

# 在 Bybit 交易所验证（最重要！）
```

## 常用命令组合

```bash
# 一键准备和检查
docker compose exec execution python -m scripts.trading_test_tool prepare && \
docker compose exec execution python -m scripts.trading_test_tool positions

# 清理并准备测试
docker compose exec execution python -m scripts.trading_test_tool clean --all --yes && \
docker compose exec execution python -m scripts.trading_test_tool prepare

# 测试并查看结果
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT --side BUY --entry-price 30000 --sl-price 29000 && \
docker compose exec execution python -m scripts.trading_test_tool positions && \
docker compose exec execution python -m scripts.trading_test_tool orders
```

## 注意事项

1. ⚠️ **test 命令会真实下单**，请确保：
   - RISK_PCT ≤ 0.001（0.1%）
   - 实时监控执行服务日志
   - 在 Bybit 交易所验证订单

2. **所有命令都应在容器内运行**，确保环境一致：
   ```bash
   docker compose exec execution python -m scripts.trading_test_tool <command>
   ```

3. **清理持仓前请确认**，避免误删有效持仓。

4. **测试下单后务必验证**：
   - 查看数据库订单和持仓
   - 在 Bybit 交易所验证订单和持仓
   - 检查执行报告和风险事件

## 帮助信息

```bash
# 查看所有命令
docker compose exec execution python -m scripts.trading_test_tool --help

# 查看特定命令的帮助
docker compose exec execution python -m scripts.trading_test_tool test --help
docker compose exec execution python -m scripts.trading_test_tool clean --help
```
