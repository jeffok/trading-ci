# Changelog

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
