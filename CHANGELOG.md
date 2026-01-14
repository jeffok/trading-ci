# Changelog

## [2026-01-14] 修复与改进

### 修复：JSON Schema 验证问题
- **问题**：执行服务在处理 trade_plan 时出现 `Unresolvable: https://schemas.local/common/event-envelope.json` 错误
- **原因**：JSON Schema 验证器尝试从网络获取 schema 文件，但 `schemas.local` 域名无法解析
- **修复**：更新 `libs/mq/schema_validator.py`，使其能够：
  - 加载所有本地 schema 文件到内存
  - 创建自定义 RefResolver，将所有 `https://schemas.local/` 的引用映射到本地文件
  - 避免网络请求，完全使用本地 schema 文件
- **影响**：修复后需要重启执行服务：`docker compose restart execution`

### 修复：数据库表名不一致问题
- **问题**：数据库完整性检查报告缺少表 `three_segment_setups`、`entry_triggers`、`pivot_points`
- **原因**：检查脚本使用了错误的表名，实际表名是 `setups`、`triggers`、`pivots`
- **修复**：更新 `scripts/check_db_integrity.py` 和 `scripts/check_db_integrity.sh`，使用正确的表名
- **影响**：数据库完整性检查现在能正确识别所有表

### 改进：统一测试工具
- **新增**：`scripts/trading_test_tool.py` - 统一的测试工具，整合所有测试功能
  - `prepare` - 准备检查（配置、服务状态、风险设置）
  - `positions` - 查看持仓
  - `clean` - 清理无效持仓
  - `test` - 执行测试下单（⚠️ 会真实下单）
  - `orders` - 查看订单
- **删除**：移除了多个分散的测试脚本，统一使用 `trading_test_tool.py`
- **文档**：新增 `scripts/README_TEST_TOOL.md` 使用指南

### 文档：同币种同向互斥机制说明
- **功能**：系统实现了同币种同向互斥保护机制，防止同一交易对同时持有多个同方向仓位
- **优先级规则**：
  - 1d: 优先级 3（最高）
  - 4h: 优先级 2
  - 1h: 优先级 1
  - 15m/30m/8h: 优先级 0（最低）
- **行为**：
  - 如果 incoming 优先级 ≤ existing 优先级 → 阻止（BLOCK）
  - 如果 incoming 优先级 > existing 优先级 → 根据 `POSITION_MUTEX_UPGRADE_ACTION` 配置决定行为
- **配置**：`POSITION_MUTEX_UPGRADE_ACTION`（可选值：`BLOCK` / `CLOSE_LOWER_AND_OPEN`）

### 文档：无效持仓问题处理
- **问题**：数据库中的持仓状态与交易所实际状态不一致
- **原因**：
  - 持仓同步只在 LIVE 模式下运行
  - 之前使用 PAPER/BACKTEST 模式测试留下的模拟持仓
  - 手动在交易所平仓但数据库未同步
- **解决方案**：
  - 使用 `trading_test_tool.py clean` 命令清理无效持仓
  - 在 LIVE 模式下，持仓同步每 10 秒自动运行
- **预防**：切换执行模式前清理 OPEN 持仓

### 文档：交易未执行问题排查
- **排查步骤**：
  1. 检查执行服务日志
  2. 检查消费者状态（Redis Streams）
  3. 检查执行服务健康状态
  4. 检查数据库订单和执行报告
- **常见问题**：
  - 执行服务未启动或崩溃
  - 消费者未处理消息（pending 消息堆积）
  - 执行过程中出错（Schema 验证、API 调用、数据库连接）
  - Bybit API 配置错误
  - 风控规则阻止

### 改进：数据库连接兼容性
- **问题**：本地 `psql` 客户端版本过旧，不支持 SCRAM 认证
- **修复**：多个脚本增加了自动检测，当本地 `psql` 不支持 SCRAM 时，自动使用 Docker 容器内的 `psql`
- **影响**：提高了脚本在不同环境下的兼容性

## [2026-01-14] Stage 11：数据质量监控 + ATR/NEWS 市场状态 + Kill Switch + Signals 生命周期
- marketdata-service：接入 gapfill 幂等发布（bar_close_emits）并补齐 DATA_GAP 回填链路；新增 DATA_LAG/BAR_DUPLICATE/PRICE_JUMP/VOLUME_ANOMALY 数据质量告警
- marketdata-service：MarketStateTracker 升级为 ATR/close 判定 HIGH_VOL，并支持 NEWS_WINDOW_UTC 时间窗标记（仅告警，不影响策略）
- execution-service：新增 Kill Switch（ENV FORCE_ON + runtime_flags DB 开关）阻断新开仓，并发布 KILL_SWITCH_ON 风险事件（窗口去重）
- strategy-service：signals 表补齐 status/valid_from_ms/expires_at_ms/updated_at 生命周期字段（迁移 V151），写入 signal TTL
- migrations：新增 V150(runtime_flags) / V151(signals lifecycle)；schemas/risk-event.json enum 扩展 BAR_DUPLICATE/PRICE_JUMP/VOLUME_ANOMALY
- notifier-service：新增 DATA_LAG/DATA_GAP/BAR_DUPLICATE/PRICE_JUMP/VOLUME_ANOMALY/KILL_SWITCH_ON 的 TG 模板；新增 Stage11 自测脚本 scripts/e2e_stage11_selftest.py
- 配置：新增 DATA_QUALITY_* / MARKET_ATR_PERIOD / NEWS_WINDOW_UTC / SIGNAL_TTL_BARS / ACCOUNT_KILL_SWITCH_FORCE_ON 等配置项

## [2026-01-14] Stage 10：WS+REST 钱包一致性（wallet snapshots + drift 告警）+ execution 成交收敛增强
- execution-service：新增 wallet_snapshots 表（迁移 V140），同时记录 WS/REST 钱包快照（审计/对账）
- execution-service：private WS wallet topic 增加快照解析与落库（repo.upsert_wallet_snapshot_from_ws）
- snapshotter：REST wallet 快照落库，并与最新 WS 快照做漂移检测，超过阈值发布 risk_event: CONSISTENCY_DRIFT(scope=wallet)，带窗口去重
- WS execution：当 fills 聚合达到订单 qty 时，主动将订单收敛为 FILLED 并发布 execution_report（减少仅靠 order topic 的延迟/漏报）
- 配置：新增 WALLET_COMPARE_ENABLED / BYBIT_WALLET_COIN / WALLET_WS_MAX_AGE_MS / WALLET_DRIFT_THRESHOLD_PCT / WALLET_DRIFT_WINDOW_MS；.env.example 同步

## [2026-01-14] Stage 9：入场异常处理（14.3）+ fills 明细落库 + 告警闭环完善
- execution-service：新增 order_manager 对 ENTRY Limit 订单 timeout/partial-fill stall 的 cancel/retry/reprice/fallback（默认 Market 不改变行为）
- execution-service：orders 增加辅助列 submitted_at_ms/retry_count/filled_qty/avg_price/last_fill_at_ms（迁移 V130）
- execution-service：新增 fills 表落库（WS execution -> fills；并回写 orders 聚合字段，供对账/告警）
- execution-service：reconcile 集成 pending ENTRY 处理，形成 ORDER_TIMEOUT/ORDER_PARTIAL_FILL/ORDER_RETRY/ORDER_FALLBACK_MARKET 的告警闭环
- notifier-service：补齐 ORDER_RETRY/ORDER_FALLBACK_MARKET/ORDER_CANCELLED 模板
- schemas：risk_event 枚举扩展 + risk_normalize 映射扩展
- scripts：新增 scripts/e2e_stage9_order_manager_selftest.py（无外部依赖逻辑自测）
- 修复：配置文件合并残留导致的语法错误（libs/common/config.py）

## [2026-01-14] Stage 8：生命周期+指标+告警增强（不改变策略）
- strategy-service：trade_plan 增加生命周期字段（status/valid_from_ms/expires_at_ms），并落库到 trade_plans 新列（V121）
- execution-service：对已过期 trade_plan 直接 REJECTED 并发布 risk_event:SIGNAL_EXPIRED（避免“过期信号”误执行）
- execution-service：execution_report 支持 fill_ratio（V120 + schema + repo/publisher）
- marketdata-service：新增 MARKET_STATE（HIGH_VOL/NORMAL）标记（仅观测/告警，不参与策略），支持阈值与去重
- execution-service：reconcile 增加 ORDER_TIMEOUT / ORDER_PARTIAL_FILL 告警（基于 open_orders createdTime，窗口去重）
- notifier-service：新增 risk_event 模板：SIGNAL_EXPIRED / ORDER_TIMEOUT / ORDER_PARTIAL_FILL / MARKET_STATE
- 配置：新增 TRADE_PLAN_TTL_BARS / MARKET_STATE_* / ORDER_TIMEOUT_ALERT_WINDOW_MS；.env.example 同步


## Stage 6.1 + Stage 7.1 (Patch)

- Secondary Rule: 当策略未提供 hist_entry 时，execution 会从 bars 表推导 entry bar 的 MACD histogram，避免二级规则成为空操作（不改变策略，仅补齐执行所需指标）。
- Secondary Rule 开关：新增 SECONDARY_RULE_ENABLED，可在不改代码情况下开启/关闭二级规则检查。
- Runner trailing（Live）：TP2 成交后，Runner 的 stopLoss 可以持续更新（只更严格、不放松），并带最小更新间隔 RUNNER_LIVE_UPDATE_MIN_INTERVAL_MS。
- WS 优先 & 降低 private REST 压力：BYBIT_PRIVATE_WS_ENABLED=true 时，对 open_orders 轮询做间隔退避（RECONCILE_OPEN_ORDERS_POLL_INTERVAL_SEC），仍保留 REST 兜底。
- WS→DB 元数据闭环：WS order TP1/TP2 成交会写入 positions.meta.tp*_filled，WS position 快照会写入 positions.meta.ws_position（仅用于对账/漂移检测）。
- 一致性漂移告警：新增 risk_event 类型 CONSISTENCY_DRIFT，发现 WS size 与本地 qty_total 偏差超过阈值（默认 10%）时告警，并带窗口去重。


## [2026-01-13] Stage 5：10006 限频治理收口（全局/分桶 limiter + public-first + 更强降级闭环）
- 增强：Bybit REST 限频治理按 endpoint 维度更细分桶：PRIVATE_CRITICAL / PRIVATE_ORDER_QUERY / PRIVATE_ACCOUNT_QUERY
- 增强：全局 + 分交易对 token-bucket；并基于 Bybit 头部（X-Bapi-Limit-Status/X-Bapi-Limit/X-Bapi-Limit-Reset-Timestamp/Retry-After）自适应降频与冷却
- 优化：observability public-first —— 当 DB 无 OPEN positions 时，快照跳过 /v5/position/list（避免无效 private 压力）
- 修复：repo.list_open_positions 增加 limit 参数（供 snapshotter/backtest 使用），并添加 ORDER BY/LIMIT
- 更新：scripts/ratelimit_selftest.py 覆盖新的分桶模型与统计输出
- 更新：.env.example 补齐 Stage 5 限频配置项

## [2026-01-13] Stage 4：更完整的 10006 限频治理（全局/分交易对）+ endpoint 分桶 + 自适应冷却 + 降级告警闭环
- 新增：`libs/bybit/ratelimit.py` 进程内 rate limiter（单实例）
  - 私有接口按 *关键交易* vs *查询类* 分桶，防止查询把下单/止损饿死
  - 全局 + 分交易对（per-symbol）双层令牌桶
  - 根据 Bybit header（X-Bapi-Limit-Status / X-Bapi-Limit-Reset-Timestamp / Retry-After）自适应冷却
- 增强：`TradeRestV5Client` 私有/公有请求统一注入 limiter，并把 headers/wait_ms 注入错误 raw 供告警使用
- 新增：私有查询接口 TTL cache（wallet_balance / position_list / open_orders），并在预测等待过长时返回“陈旧但可用”的降级数据（携带 _degraded/_stale_ms/_predicted_wait_ms）
- 增强：execution 侧（risk_monitor / snapshotter / position_sync / reconcile）遇到降级数据会发布 risk_event: RATE_LIMIT（形成告警闭环）
- 新增：`scripts/ratelimit_selftest.py` 本地自测脚本（不调用交易所）

## [2026-01-12] Stage 2：Telegram 交易详情 + 盈亏/连亏统计 + Bybit 10006 限频告警
- 新增：Telegram 模板（开仓/平仓/TP/SL/拒单/限频），平仓消息包含数量、开/平仓均价、PnL(USDT)、连续亏损次数。
- 新增：paper/backtest 平仓盈亏计算 pnl_usdt 与平仓均价 exit_avg_price，并写入 execution_report.payload.ext。
- 新增：risk_state.meta.consecutive_loss_count 统计（盈利/打平归零，亏损+1）仅用于通知/观测，不改变策略。
- 增强：Bybit 私有 REST 遇到 10006/429 时优先按 retry_after_ms 退避重试，并发布 risk_event: RATE_LIMIT（包含 endpoint 与“优先使用 public API”建议）。
- 修复：paper_sim 解析 bar_close.ohlcv 同时兼容 dict 与 legacy list。

## [2026-01-12] Stage 1：事件契约对齐 + Notifier 基础渲染（execution_report / risk_event）
- 兼容：execution_report 保持旧调用签名，但发布新的 schema payload（plan_id/status/timeframe/filled_qty/avg_price/reason），并把 legacy 字段写入 payload.ext。
- 新增：risk_event type/severity 归一化（严格映射到 schema enum），并保留 legacy_type/legacy_severity 到 detail。
- 新增：execution_reports/risk_events 表新增 schema 对齐列（迁移 V090__schema_align_execution_reports_and_risk_events.sql），API 查询可返回 plan_id/status 等。
- 新增：notifier 对 execution_report/risk_event 的基础模板渲染（Stage 1 minimal），并兼容 CRITICAL/IMPORTANT 推送。
- 增强：execution_report 发布时自动落库（失败不阻塞交易主链路）。

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

## [2026-01-13] Stage 6：执行闸门补齐（最大持仓/互斥升级/冷却落地/TP 撤销闭环）
- 新增：trade_plan 执行前闸门（冷却/最大同时持仓数/同币种同向互斥 + 周期优先级 1d>4h>1h）
- 行为：当高优先级周期信号到来且存在低优先级同向仓位时，best-effort 先市价退出低优先级仓位（mutex_upgrade）
- 新增：paper/backtest 在 PRIMARY_SL_HIT 时写入 cooldowns（按 timeframe bars），并在闸门侧阻断冷却期再入场
- 新增：规则退出/强制退出/互斥升级时，best-effort 撤销 TP1/TP2（live 先撤单，paper/backtest 直接落库为 CANCELED）
- 更新：notifier 对 COOLDOWN_BLOCKED / MAX_POSITIONS_BLOCKED / POSITION_MUTEX_BLOCKED 提供更友好的 Telegram 文本
- 新增：迁移 V100__stage6_cooldowns_and_position_close_cols.sql（cooldowns 表 + positions 补充字段）

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

## [2026-01-14] Stage 9 (14.3 Abnormal handling + fills persistence)
- 新增：`migrations/postgres/V130__fills_and_order_stats.sql`：增加 `fills` 表与 orders 辅助字段（submitted_at_ms/retry_count/filled_qty/avg_price/last_fill_at_ms）
- 新增：`services/execution/order_manager.py`：ENTRY 限价单超时/部分成交停滞的撤单→重试→（可选）降级市价闭环，并发送 risk_event 告警
- 增强：`services/execution/reconcile.py` 调用 order_manager，在 LIVE 模式下对 pending ENTRY 限价单做治理
- 增强：`services/execution/ws_private_ingest.py` 将 execution fills 规范化写入 `orders.payload.fills` + `fills` 表，并更新 orders 聚合字段
- 增强：`services/execution/repo.py` 支持 fills 写入、按状态查询订单、WS 状态写入 cumExecQty/avgPrice
- 更新：`libs/schemas/streams/risk-event.json` 增加 ORDER_RETRY / ORDER_FALLBACK_MARKET / ORDER_CANCELLED
- 更新：`services/notifier/templates.py` 增加上述告警类型的 Telegram 文本模板
- 更新：`.env.example` 增加 Stage9 配置项（默认不改变策略：Market entry）
