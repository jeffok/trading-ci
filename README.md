# trading-ci（Bybit USDT 永续自动交易系统）

本仓库为 **契约优先**、**事件驱动** 的自动交易系统实现。

- 技术栈：Python + Postgres + Redis（Streams）
- 架构：容器化多服务（marketdata / strategy / execution / notifier / api）
- 运行：docker-compose 仅启动业务服务；**外部**提供 Postgres/Redis（compose 不启动 DB/Redis）

> 数据库名称：`trading-ci`  
> 注意：Postgres 中包含 `-` 的数据库名需要用双引号创建，例如：`CREATE DATABASE "trading-ci";`

## 1. 快速开始（开发环境）

### 1.1 准备外部依赖
- Postgres：提供 `DATABASE_URL`（指向 `trading-ci`）
- Redis：提供 `REDIS_URL`（用于 Redis Streams）

### 1.2 配置
```bash
cp .env.example .env
```

### 1.3 初始化 Redis Streams（幂等）
```bash
python scripts/init_streams.py
```

### 1.4 启动
```bash
docker compose up --build
```

## 2. Phase 1：行情闭环（marketdata-service）

Phase 1 目标：从 Bybit 公共 WS 订阅 K 线，**只在 candle 收盘(confirm=true)时**：
1) upsert 到 Postgres `bars` 表
2) 发布 `bar_close` 事件到 Redis Streams `stream:bar_close`

### 2.1 marketdata 配置
在 `.env` 中设置：
- `MARKETDATA_SYMBOLS=BTCUSDT,ETHUSDT`
- `MARKETDATA_TIMEFRAMES=15m,30m,1h,4h,8h,1d`

说明：
- Bybit 原生 interval 不提供 `8h`（480 分钟），本项目 Phase 1 **用 1h candle 聚合生成 8h candle**（仅补齐监控周期，不改变策略规则）。

## 3. 目录结构（简化）
```text
repo/
  docker-compose.yml
  Dockerfile
  requirements.txt
  .env.example
  CHANGELOG.md
  migrations/postgres/
  libs/
    common/   # 配置/日志/ID/时间
    mq/       # Redis Streams + Schema 校验
    db/       # Postgres 访问与 SQL
    bybit/    # Bybit REST/WS 客户端
    schemas/  # JSON Schema（事件契约）
  services/
    marketdata/
    strategy/
    execution/
    notifier/
    api/
  scripts/
```

## 4. 版本与变更
详见：`CHANGELOG.md`


## 3. Phase 2：策略引擎（strategy-service）
- 消费 bar_close，检测三段背离 + 共振门槛，产出 signal 与 trade_plan（仅 1h/4h/1d 自动周期）
