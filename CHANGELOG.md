# Changelog

## [2026-01-11] Phase 2：策略引擎（strategy-service）
- 新增：策略最小实现（消费 stream:bar_close，产出 stream:signal / stream:trade_plan）
- 新增：MACD/EMA/RSI/OBV 指标计算模块（纯 Python，注释详尽）
- 新增：分形 pivot 检测 + MACD histogram 三段顶/底背离识别（输出第三极值用于止损）
- 新增：Vegas 同向强门槛（EMA144/EMA169）+ confirmations（ENGULFING/RSI_DIV/OBV_DIV/FVG_PROXIMITY）
- 新增：signals / trade_plans 最小落库表迁移（JSONB 存储事件，便于复盘与 API 查询）
- 新增：毒消息保护：处理失败会发布 risk_event，并 ack 以避免阻塞（Phase 2 简化策略）

## [2026-01-11] 修复：兼容在部分系统上 `python` 指向 Python2 的情况
- scripts/init_streams.py 增加 shebang 与 UTF-8 编码声明，避免非 ASCII 注释导致的 SyntaxError
- 提示：建议统一使用 `python3` 运行本项目的本地脚本

## [2026-01-11] Phase 1：行情闭环（marketdata-service）
- 项目更名：trading-ci（并在 README/.env.example 中同步数据库名称为 trading-ci）
- 新增：Bybit Public WS Kline 订阅与心跳（ping 每 20s），仅 candle 收盘(confirm=true)触发处理
- 新增：bars 表迁移 `migrations/postgres/V010__bars.sql`（含派生 8h）
- 新增：REST 回填（写库不发布事件）用于启动 warmup（可开关）
- 新增：8h 派生器（由 1h 聚合生成），并发布对应的 bar_close（不改变策略，仅补齐监控周期）
- 事件投递：Redis Streams 统一采用字段 data=JSON(envelope)（新增 libs/mq/events.py）
- 依赖更新：新增 websockets/httpx（requirements.txt）

本项目采用“追加记录”的方式维护变更日志，按日期倒序。

## [2026-01-11] 初始化骨架（Phase 0）
- 初始化仓库结构：5 服务 + libs + migrations + configs
- 新增：统一配置加载、结构化日志（JSON）、Redis Streams 初始化与消费骨架
- 新增：事件契约（JSON Schema）落地到 `libs/schemas`
- 新增：docker-compose（仅业务服务，外部 DB/Redis）与示例 `.env.example`
