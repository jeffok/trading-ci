# Changelog

本项目采用“追加记录”的方式维护变更日志，按日期倒序。

## [2026-01-11] 初始化骨架（Phase 0）
- 初始化仓库结构：5 服务 + libs + migrations + configs
- 新增：统一配置加载、结构化日志（JSON）、Redis Streams 初始化与消费骨架
- 新增：事件契约（JSON Schema）落地到 `libs/schemas`
- 新增：docker-compose（仅业务服务，外部 DB/Redis）与示例 `.env.example`
