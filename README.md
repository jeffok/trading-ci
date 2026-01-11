# Bybit USDT 永续自动交易系统（容器化多服务）

本仓库为**契约优先**、**事件驱动**的自动交易系统实现骨架。

- 技术栈：Python + Postgres + Redis（Streams）
- 服务：marketdata / strategy / execution / notifier / api
- 运行：docker-compose 仅启动业务服务；**外部**提供 Postgres/Redis（compose 不启动 DB/Redis）

## 快速开始
1) 准备外部依赖：Postgres（DATABASE_URL）、Redis（REDIS_URL）  
2) 配置：`cp .env.example .env` 并填写连接信息  
3) 启动：`docker compose up --build`

## 目录结构（简化）
```text
repo/
  docker-compose.yml
  Dockerfile
  requirements.txt
  .env.example
  CHANGELOG.md
  configs/
  migrations/postgres/
  libs/
    common/
    mq/
    db/
    bybit/
    schemas/
  services/
    marketdata/
    strategy/
    execution/
    notifier/
    api/
  scripts/
```
