# -*- coding: utf-8 -*-
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

### 1.3 初始化（已自动化）
> 从 Stage7 开始，容器启动时会自动执行初始化（幂等）：
> - Postgres migrations（可用 `SKIP_DB_MIGRATIONS=1` 关闭）
> - Redis Streams + consumer group（可用 `SKIP_REDIS_STREAMS_INIT=1` 关闭）

如需手动执行（例如本地调试），推荐：
```bash
python -m scripts.init_streams
python -m scripts.init_db
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


## 5. Phase 4：持仓生命周期管理（execution-service + notifier + api）
- execution-service：消费 trade_plan，下单/挂 TP/设置 SL；并消费 bar_close 更新 Runner 跟随止损 & 检查次日规则（事件化）
- notifier-service：消费 execution_report/risk_event，日志 + 可选 Telegram 推送
- api-service：提供只读查询 signals/trade_plans/orders/positions/execution-reports


## 6. Phase 5：离线回测 + 信号评分（不改变策略）
### 6.1 回测（读取 Postgres bars）
```bash
python3 scripts/backtest.py --symbol BTCUSDT --timeframe 1h --limit 5000 --trail ATR
```

### 6.2 信号评分（仅用于复盘）
- strategy-service 会在 signal/trade_plan 的 payload.ext.scoring 中带上：
  - signal_quality_score（0~100）
  - divergence_strength（0~60）
  - confluence_strength（0~40）
- 注意：执行层默认**不依赖**该分数，不会改变交易行为。


## 6. Phase 6：实盘安全与稳定性（Retry / DLQ / 账户级熔断）
- Bybit REST：增加可重试错误判定与指数退避重试（提升 429/5xx/短暂异常的稳定性）
- DLQ：对解析失败/校验失败/处理异常的消息写入 `stream:dlq`，避免丢失与便于排障
- 账户级熔断：基于当日权益回撤触发 soft/hard（软：停新仓；硬：强制平仓）
- API：增加 /risk-state 与 /risk-events 查询接口


## Stage 1：执行层约束闭环（max positions / mutex / cooldown / lock / kill-switch）
新增能力（默认安全策略）：
- `MAX_OPEN_POSITIONS`：最大同时持仓数，超限拒绝新开仓
- `COOLDOWN_*`：止损后冷却 bars（由 position_sync 识别 exchange closed + 未触发 TP1 的情况）
- `PRIORITY_REPLACE_ENABLED=false`：默认不替换已有仓位，仅拒绝新开仓；开启后，高周期信号可平掉低周期同向仓位
- `lock:plan:{idempotency_key}`：Redis 幂等锁，避免并发重复下单
- 熔断可开关：`RISK_CIRCUIT_ENABLED`
- 运维接口：`POST /v1/admin/kill-switch`（Header: X-Admin-Token）


## Stage 2：行情缺口检测与回填（Gapfill）
- 缺口检测：对比上一根 close_time_ms 与当前 bar open_time_ms，发现断档则触发 `DATA_GAP`
- REST 回填：拉取缺口范围 bars 写库
- 顺序补发：按时间顺序补发缺口 bars 的 `stream:bar_close`（通过 bar_close_emits 幂等）
- WS 重连：发布 `WS_RECONNECT` 质量事件
- 回填完成：发布 `BACKFILL_DONE` 质量事件


## Stage 3：复盘与运维能力补齐（快照落库 / Notifier 幂等重试 / API v1 / 配置脱敏 / DLQ 查询）
新增能力：
- strategy-service：落库指标快照 `indicator_snapshots`、结构 `setups`、确认 `triggers`、三段 pivot `pivots`
- notifier-service：通知落库 `notifications`（幂等：event_id 作为主键）、失败重试（指数退避）、状态可追溯
- api-service：新增 `/v1/*` 规范接口，并提供：
  - `/v1/config`：脱敏配置输出（不含密钥）
  - `/v1/dlq`：DLQ 最近 N 条查询（需 `X-Admin-Token`）
  - `/v1/indicator-snapshots`、`/v1/notifications` 等复盘查询接口


## Stage 4：执行复盘增强 + 资金/仓位快照 + 关键路径指标（告警阈值）
新增能力：
- execution-service：执行流程关键步骤落库 `execution_traces`（START/ERROR/DONE 等），便于复盘与排障
- execution-service：资金/仓位快照 `account_snapshots`（LIVE 拉交易所；PAPER/BACKTEST 派生快照）
- 关键路径延迟告警：
  - trade_plan 消费延迟（> ALERT_TRADE_PLAN_LAG_MS）发布 `risk_event: PROCESSING_LAG`
  - bar_close 消费延迟（> ALERT_BAR_CLOSE_LAG_MS）发布 `risk_event: PROCESSING_LAG`
- api-service：新增复盘查询接口
  - `/v1/execution-traces?idempotency_key=...`
  - `/v1/account-snapshots?trade_date=YYYY-MM-DD`


## Stage 5：回测/模拟盘可观测性补齐（回测落库 + API 查询 + DLQ 统一）
新增能力：
- 回测结果落库：新增表 `backtest_runs` / `backtest_trades`
- 回测脚本增强：`scripts/backtest.py` 支持 `--write_db` 将 run & trades 写入 DB（便于 API 查询与对比）
- API：新增回测查询
  - `/v1/backtest-runs?symbol=...&timeframe=...`
  - `/v1/backtest-trades?run_id=...`
- DLQ 闭环补齐：strategy/marketdata 消费异常时写入 `stream:dlq`（便于 /v1/dlq 查询）


## 回测 & 模拟盘（闭环增强：Stage 6）

本项目有两条“回测路径”：

1) **ENGINE 回测（脚本级）**：`scripts/backtest.py` 直接在本地计算信号/交易结果，并可写入 `backtest_runs/backtest_trades`（Stage 5）。
2) **REPLAY 回放回测（服务级）**：`scripts/replay_backtest.py` 逐根发布 `stream:bar_close`，让 **strategy / execution / notifier / api** 跑完整链路（Stage 6）。
   - 适合联调、排障、验证“线上链路一致性”
   - 需要 `EXECUTION_MODE=paper/backtest` 开启执行层撮合模拟（TP/SL/Runner）

### REPLAY 快速开始

> 强烈建议在独立 Redis / 独立 DB 中运行回放，避免影响 live。

1) 启动服务（示例：docker compose）
- `EXECUTION_MODE=backtest`（或 `paper`）
- 数据库中需有 `bars`（可用 marketdata 服务写入，或回放脚本 `--fetch` 临时补一段）

2) 回放最近 N 根 bars：
```bash
python scripts/replay_backtest.py --symbol BTCUSDT --timeframe 60 --limit 2000
```

3) 用 API 检查闭环进度（run_id 来自脚本输出）：
```bash
curl "http://localhost:8000/v1/backtest-compare?run_id=<RUN_ID>&limit_trades=50"
```

### bar 内成交顺序（重要）

在同一根 K 线上既可能触发 TP 又可能触发 SL 时，paper/backtest 需要确定性规则避免歧义：
- 若 `close >= open`：假设价格路径 `open -> high -> low -> close`
- 若 `close < open`：假设价格路径 `open -> low -> high -> close`

该规则仅用于 **执行层撮合模拟**，不改变策略本身。


## Stage 7：一键回放 + 等待链路空闲 + 自动生成回测报告（CI/回放收口）
新增能力：
- 脚本：`scripts/run_replay_and_report.py`
  - 自动调用 `replay_backtest.py` 发布 bar_close（含 run_id）
  - 等待关键 streams 的 pending 清零 + positions_open(run_id)=0
  - 直接查 Postgres 汇总统计并生成报告：
    - `reports/replay_<run_id>.md`
    - `reports/replay_<run_id>.json`
  - 可选：提供 `--api-url` 拉取 `/v1/backtest-compare` 作为补充核对信息

- API：新增 `/v1/backtest-compare?run_id=...`
- 修复：RedisStreamsClient 补齐 ensure_group/pending/lag 等运维接口（支持 init_streams 与 CI 等待逻辑）

### Backtest/Paper 资金基数
- `BACKTEST_EQUITY`（或 `PAPER_EQUITY`）：用于 paper/backtest 的仓位计算（默认 10000）。
  示例：
  ```bash
  export BACKTEST_EQUITY=20000
  ```
