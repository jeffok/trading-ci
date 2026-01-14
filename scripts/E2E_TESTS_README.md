# E2E 集成测试说明

## 📋 保留的集成测试文件

### 1. e2e_stage2_close_test.py - 平仓测试

**用途**：测试平仓流程和通知消息（包含 PnL 和连续亏损统计）

**运行方式**：
```bash
# 在 PAPER/BACKTEST 模式下运行
docker compose exec execution python -m scripts.e2e_stage2_close_test

# 自定义参数
docker compose exec execution python -m scripts.e2e_stage2_close_test \
  --wait-before-close 5 \
  --wait-after-close 3 \
  --close-price 623.7579
```

**功能**：
- 注入 trade_plan
- 等待持仓创建
- 强制平仓（PAPER/BACKTEST 模式）
- 验证平仓消息包含 PnL 和连续亏损统计

**何时使用**：
- 验证平仓流程是否正常
- 验证通知消息格式是否正确
- 在实盘测试前验证平仓功能

### 2. e2e_stage6_gates_test.py - 风控闸门测试

**用途**：集成测试风控功能（MAX_POSITIONS_BLOCKED、mutex upgrade、cooldown）

**运行方式**：
```bash
# 在 PAPER/BACKTEST 模式下运行
docker compose exec execution python -m scripts.e2e_stage6_gates_test

# 重置数据库后测试
docker compose exec execution python -m scripts.e2e_stage6_gates_test --reset-db
```

**功能**：
- 测试最大持仓数限制（MAX_POSITIONS_BLOCKED）
- 测试同币种同向互斥升级（mutex upgrade）
- 测试冷却期功能（cooldown）

**何时使用**：
- **实盘测试前必须运行**，验证风控功能是否正常
- 验证风控规则是否正确执行
- 验证风险事件是否正确生成

## 🎯 使用建议

### 实盘测试前的完整流程

```bash
# 1. 运行风控闸门测试（重要！）
docker compose exec execution python -m scripts.e2e_stage6_gates_test --reset-db

# 2. 运行平仓测试（可选）
docker compose exec execution python -m scripts.e2e_stage2_close_test

# 3. 使用统一测试工具进行实盘测试
docker compose exec execution python -m scripts.trading_test_tool prepare
docker compose exec execution python -m scripts.trading_test_tool test \
  --symbol BTCUSDT --side BUY --entry-price 30000 --sl-price 29000
```

## 📝 为什么保留这些文件？

1. **e2e_stage2_close_test.py**：
   - 测试特定的平仓流程
   - 验证通知消息格式
   - 不适合合并到通用测试工具（太特定）

2. **e2e_stage6_gates_test.py**：
   - 测试多个风控功能
   - 需要重置数据库
   - 是重要的集成测试，应该在实盘前运行

## 🔄 与 trading_test_tool.py 的关系

- **trading_test_tool.py**：用于实盘测试的日常操作
- **e2e_stage2_close_test.py**：用于验证平仓功能
- **e2e_stage6_gates_test.py**：用于验证风控功能

这些文件各有用途，互补但不重复。
