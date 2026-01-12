# -*- coding: utf-8 -*-
# Changelog

## [2026-01-12] Stage 7：一键回放 + 等待链路空闲 + 自动生成回测报告（CI/回放收口）
- 新增：scripts/run_replay_and_report.py（回放 + 等待 + 报告）
- 新增：API /v1/backtest-compare（按 run_id 汇总链路产物与提示）
- 修复：RedisStreamsClient 增加 ensure_group/pending_count/group_lag
- 增强：run_id 在 strategy(signal/trade_plan) 与 execution(orders/positions.meta) 中贯穿，便于核对与过滤
- 修复：execution-service worker 补齐 bar_close 消费与 paper_sim 调用，完成 TP/SL/Runner 出场闭环

## [2026-01-12] Stage 6 - Backtest & Paper 闭环完成（REPLAY 回放 + OHLC 撮合模拟 + /v1/backtest-compare）

### 新增
- `services/execution/paper_sim.py`：paper/backtest 模式下，基于 bar_close 的 OHLC 模拟 TP1/TP2/SL/Runner 触发，写 execution_report + execution_traces + backtest_trades。
- `scripts/replay_backtest.py`：回放 bars -> 发布 `stream:bar_close`（带 `run_id/seq`），用于链路级回测。
- `migrations/postgres/V081__backtest_trades_idempotency_key.sql`：为 `backtest_trades` 增加 `idempotency_key`（便于联调核对）。
- API：`GET /v1/backtest-compare?run_id=...`：统计 signals/trade_plans/orders/positions/reports/backtest_trades 并返回最近 trades。

### 变更
- `services/strategy/worker.py`：从 bar_close 的 `payload.ext.run_id` 透传到 signal/trade_plan 的 `payload.ext.run_id`。
- `services/execution/worker.py`：消费 bar_close 时，先调用 `process_paper_bar_close()` 完成 paper/backtest 撮合模拟，再做 runner/secondary 规则检查。
- `services/execution/executor.py`：trade_plan 透传 `run_id`；paper/backtest 平仓不再调用交易所，改为落库并写 backtest_trades。
- `libs/backtest/repo.py`：`insert_backtest_trade()` 支持写入 `idempotency_key`；新增 `list_backtest_trades()`。



## [2026-01-12] Stage 5：回测/模拟盘可观测性补齐（回测落库 + API 查询 + DLQ 统一）
- 新增：回测落库表 backtest_runs/backtest_trades（迁移 V080__backtest_tables.sql）
- 新增：scripts/backtest.py 支持 --write_db / --run_id 将回测结果落库
- 新增：API /v1/backtest-runs 与 /v1/backtest-trades
- 增强：strategy/marketdata 消费异常统一写入 DLQ（stream:dlq），方便 API 查询闭环

## [2026-01-12] Stage 4：执行复盘增强 + 资金/仓位快照 + 关键路径指标与告警阈值
- 新增：执行 trace 落库 execution_traces（不影响执行，仅用于复盘/排障）
- 新增：资金/仓位快照 account_snapshots（LIVE 抓取；PAPER/BACKTEST 派生）
- 新增：关键路径延迟告警（trade_plan / bar_close）-> risk_event: PROCESSING_LAG
- 新增：API 查询 /v1/execution-traces 与 /v1/account-snapshots
- 新增：迁移 V070__execution_observability.sql

## [2026-01-12] Stage 3：复盘与运维能力补齐（快照落库 / Notifier 幂等重试 / API v1 / 配置脱敏 / DLQ 查询）
- 新增：strategy 中间产物落库（indicator_snapshots / setups / triggers / pivots）用于复盘追溯（不参与决策）
- 新增：notifier 通知落库 notifications（幂等）+ 失败重试（指数退避）+ 状态可查
- 新增：API /v1 规范化接口；新增 /v1/config（脱敏）与 /v1/dlq（管理员口令）
- 新增：迁移 V060__strategy_observability.sql、V061__notifier_notifications.sql

## [2026-01-12] Stage 2：行情缺口检测 + 回填 + 顺序补发 bar_close（数据质量事件闭环）
- 新增：缺口检测（DATA_GAP）与 REST 回补缺口 bars
- 新增：回补 bars 后按时间顺序补发 `stream:bar_close`（幂等：bar_close_emits）
- 新增：WS 重连事件（WS_RECONNECT）与回补完成事件（BACKFILL_DONE），并落库到 risk_events
- 新增：迁移 V051__bar_close_emits.sql

## [2026-01-12] Stage 1：执行层约束闭环（max positions / mutex / cooldown / lock / kill-switch）
- 新增：Redis 幂等锁 `lock:plan:{idempotency_key}`，避免并发/重复投递导致的重复下单窗口
- 新增：最大同时持仓数拦截（MAX_OPEN_POSITIONS）
- 新增：同币种同向互斥 + 周期优先级（可选替换：PRIORITY_REPLACE_ENABLED）
- 新增：止损后冷却（cooldowns 表 + position_sync 识别交易所侧已平仓并写入冷却）
- 新增：kill-switch 运维接口（/v1/admin/kill-switch）与 RISK_CIRCUIT_ENABLED 开关
- 新增：迁移 V050__execution_constraints.sql（cooldowns 表 + positions 补充字段）

## [2026-01-12] Phase 6：实盘安全与稳定性增强（Retry / DLQ / 账户级熔断）
- Bybit REST：新增错误分类与指数退避重试（429/5xx/系统繁忙/超时等）
- 新增：DLQ（stream:dlq）用于坏消息/异常消息沉淀与排障
- 新增：账户级日内回撤熔断（soft/hard），硬熔断自动触发 reduce-only 市价强制平仓
- 新增：risk_state / risk_events 表（V040）与 api 查询接口（/risk-state, /risk-events）
- 更新：execution-service 增加风险监控循环；入场前读取 risk_state 判定是否允许新开仓

## [2026-01-12] Phase 5：回测与复盘能力增强（scoring/backtest）
- strategy-service：新增信号质量评分（0~100）与特征字段，写入 signal/trade_plan 的 payload.ext.scoring（不参与决策）
- 新增：libs/strategy/scoring.py（背离强度/共振强度/总分）
- 新增：离线回测脚本 scripts/backtest.py（读取 Postgres bars，模拟执行：TP1/TP2/Runner trailing + 次日规则）
- 新增：libs/backtest（engine/report）
- 更新：README.md 增加 Phase 5 使用说明

## [2026-01-12] Phase 4：持仓生命周期管理与可观察性（execution/notifier/api）
- execution-service：实现 trade_plan ->（paper/live）下单闭环；挂 TP1/TP2（reduce-only）；设置 primary SL
- execution-service：新增 bar_close 消费者，用于 Runner 跟随止损（ATR/PIVOT）与“次日未继续缩短”规则检查（并自动触发 reduce-only 市价退出）
- 新增：live 模式对账循环（reconcile），识别 TP1/TP2 成交并按规则更新止损（TP1 后保本，TP2 后启用 Runner trailing）
- 新增：Bybit V5 REST 鉴权与最小客户端封装（wallet-balance / instruments-info / order/create / order/realtime / position/list / position/trading-stop）
- 新增：执行层落库 orders / positions / execution_reports（V030）
- notifier-service：消费 execution_report/risk_event，可选 Telegram 推送
- api-service：新增只读查询接口（signals/trade-plans/orders/positions/execution-reports）
- 更新：.env.example 补齐 execution/notifier 配置项

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