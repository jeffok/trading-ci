# E2E 测试文件分析报告

## 📊 文件分类

### 1. 集成测试（需要保留）

#### e2e_smoke_test.py ✅ **保留但可优化**
- **功能**：健康检查、Redis Streams 检查、注入 trade_plan
- **用途**：快速验证系统是否正常工作
- **状态**：
  - 健康检查功能：**有用**（trading_test_tool.py 没有完整的健康检查）
  - trade_plan 注入：**已被 trading_test_tool.py test 命令覆盖**
- **建议**：保留，但可以将健康检查功能合并到 trading_test_tool.py

#### e2e_stage2_close_test.py ✅ **保留**
- **功能**：注入 trade_plan，强制平仓，测试 PnL 和连续亏损统计
- **用途**：测试平仓流程和通知消息
- **状态**：**特定功能测试，实盘测试中有用**
- **建议**：保留，这是测试平仓流程的重要工具

#### e2e_stage6_gates_test.py ✅ **保留**
- **功能**：测试 MAX_POSITIONS_BLOCKED、mutex upgrade、cooldown 等风控功能
- **用途**：集成测试风控闸门
- **状态**：**重要的集成测试，实盘测试前应该运行**
- **建议**：保留，这是验证风控功能的重要工具

### 2. 单元测试/自测（开发阶段有用，实盘测试不需要）

#### e2e_stage8_test.py ⚠️ **可选保留**
- **功能**：检查 schema、模板、MarketStateTracker（纯逻辑，无外部依赖）
- **用途**：开发阶段的单元测试
- **状态**：开发阶段有用，实盘测试不需要
- **建议**：保留（开发阶段有用），但不合并到测试工具

#### e2e_stage9_order_manager_selftest.py ⚠️ **可选保留**
- **功能**：测试重试价格计算、风险类型归一化（纯逻辑）
- **用途**：开发阶段的单元测试
- **状态**：开发阶段有用，实盘测试不需要
- **建议**：保留（开发阶段有用），但不合并到测试工具

#### e2e_stage10_wallet_drift_selftest.py ⚠️ **可选保留**
- **功能**：测试钱包解析和漂移计算（纯逻辑）
- **用途**：开发阶段的单元测试
- **状态**：开发阶段有用，实盘测试不需要
- **建议**：保留（开发阶段有用），但不合并到测试工具

#### e2e_stage11_selftest.py ⚠️ **可选保留**
- **功能**：测试风险类型、NEWS_WINDOW、ATR、模板（纯逻辑）
- **用途**：开发阶段的单元测试
- **状态**：开发阶段有用，实盘测试不需要
- **建议**：保留（开发阶段有用），但不合并到测试工具

#### e2e_stage61_stage71_patch_test.py ⚠️ **可选保留**
- **功能**：测试 CONSISTENCY_DRIFT schema、hist_entry 推断
- **用途**：补丁验证
- **状态**：开发阶段有用，实盘测试不需要
- **建议**：保留（开发阶段有用），但不合并到测试工具

## 🎯 处理建议

### 方案1：保留所有，但分类管理（推荐）

**保留的文件：**
- ✅ `e2e_smoke_test.py` - 健康检查功能有用
- ✅ `e2e_stage2_close_test.py` - 平仓测试有用
- ✅ `e2e_stage6_gates_test.py` - 风控测试有用
- ⚠️ `e2e_stage8_test.py` - 开发阶段有用
- ⚠️ `e2e_stage9_order_manager_selftest.py` - 开发阶段有用
- ⚠️ `e2e_stage10_wallet_drift_selftest.py` - 开发阶段有用
- ⚠️ `e2e_stage11_selftest.py` - 开发阶段有用
- ⚠️ `e2e_stage61_stage71_patch_test.py` - 开发阶段有用

**理由：**
- 集成测试（smoke、stage2、stage6）对实盘测试有用
- 单元测试对开发阶段有用，保留但不合并

### 方案2：删除单元测试，只保留集成测试

**删除的文件：**
- ❌ `e2e_stage8_test.py` - 纯逻辑测试，开发阶段运行即可
- ❌ `e2e_stage9_order_manager_selftest.py` - 纯逻辑测试
- ❌ `e2e_stage10_wallet_drift_selftest.py` - 纯逻辑测试
- ❌ `e2e_stage11_selftest.py` - 纯逻辑测试
- ❌ `e2e_stage61_stage71_patch_test.py` - 补丁测试

**保留的文件：**
- ✅ `e2e_smoke_test.py` - 健康检查
- ✅ `e2e_stage2_close_test.py` - 平仓测试
- ✅ `e2e_stage6_gates_test.py` - 风控测试

## 💡 合并到测试工具的建议

### 可以合并的功能：

1. **健康检查**（来自 e2e_smoke_test.py）
   - 检查所有服务的健康状态
   - 检查 Redis Streams 状态
   - 可以添加到 `trading_test_tool.py` 的 `prepare` 命令中

2. **平仓测试**（来自 e2e_stage2_close_test.py）
   - 可以添加为 `trading_test_tool.py` 的新命令：`close-test`
   - 用于测试平仓流程

3. **风控测试**（来自 e2e_stage6_gates_test.py）
   - 可以添加为 `trading_test_tool.py` 的新命令：`test-gates`
   - 用于验证风控功能

### 不建议合并的功能：

- 单元测试（stage8/9/10/11/61）是开发阶段的测试，不适合合并到实盘测试工具

## 📝 最终建议

**推荐方案：方案1（保留所有，但分类管理）**

1. **保留所有 e2e 测试文件**（它们各有用途）
2. **增强 trading_test_tool.py**：
   - 添加 `health` 命令（合并 e2e_smoke_test.py 的健康检查）
   - 添加 `close-test` 命令（合并 e2e_stage2_close_test.py 的功能）
   - 添加 `test-gates` 命令（合并 e2e_stage6_gates_test.py 的功能）
3. **文档说明**：
   - 在 README 中说明哪些是集成测试（实盘测试用）
   - 哪些是单元测试（开发阶段用）
