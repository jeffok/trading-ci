# Bybit USDT 永续自动交易系统｜技术开发需求文档（合并版）
**版本**：v1.3-merged+enhanced
**日期**：2026-01-11  
**范围**：需求、架构、模块、接口与数据结构、事件契约、开发阶段与 Issue 列表（不包含代码实现）

---

## 1. 项目概述
本项目为 **Bybit USDT 永续合约自动交易系统**，采用容器化多服务架构，围绕 “行情收盘驱动 → 策略信号与交易计划 → 执行与风控 → 通知与查询接口” 的闭环设计。

### 1.1 技术栈
- 语言：Python
- 数据库：Postgres
- 缓存/消息：Redis（Streams + consumer groups）
- 部署形态：docker-compose（仅业务服务），运行时连接外部 Postgres/Redis（compose 不启动 DB/Redis）

### 1.2 服务划分（五服务）
- marketdata-service：行情接入、K 线收盘确认、bars 落库、发布 bar_close
- strategy-service：指标计算、形态/背离/三段结构识别、共振判断、生成 signal/trade_plan
- execution-service：风控校验、仓位与订单、对账、止盈止损、次日退出、发布 execution_report/risk_event
- notifier-service：Telegram 通知与告警
- api-service：查询接口与运行状态输出

### 1.3 周期与运行模式
- 自动下单周期：1h / 4h / 1d
- 仅监控周期：15m / 30m / 8h（仅输出 signal，不产生 trade_plan）

---

## 2. 策略规则（硬规则）
### 2.1 核心结构：MACD 柱形图三段顶/底背离
- 三段顶背离（做空）：三段上涨；MACD 柱逐段缩短；价格创新高但 MACD 未创新高
- 三段底背离（做多）：三段下跌；MACD 柱逐段缩短；价格创新低但 MACD 未创新低

### 2.2 入场与退出
- 入场：收盘确认（bar_close）后触发入场（确认柱完成时）
- 止损：第三极值止损（Primary SL）
- 次日规则：入场后下一根周期收盘 K 线若未继续缩短，立即退出并撤销所有 TP 单（Secondary SL Exit）

### 2.3 共振门槛（过滤条件）
- 必须满足：Vegas 同向强门槛（Bullish/Bearish）
- 确认数门槛：min_confirmations=2，候选项：Engulfing / RSI-div / OBV-div / FVG-proximity

---

## 3. 风控与交易执行规则
### 3.1 仓位与风险
- risk_pct：默认 0.5%
- 最大同时持仓数：默认 3（可配置 1~10）
- 同币种同向互斥；冷却机制；账户级熔断（可开关）

### 3.2 止盈与出场
- TP1：+1R，40%
- TP2：+2R，40%
- 剩余 20%：跟随止损（ATR 或 Pivot）
- TP 单必须为 reduce-only

---

## 4. 数据流与事件流（Redis Streams）
### 4.1 Streams
- `stream:bar_close`
- `stream:signal`
- `stream:trade_plan`
- `stream:execution_report`
- `stream:risk_event`

### 4.2 事件驱动主链路（闭环）
1) marketdata 发布 `bar_close`  
2) strategy 消费 bar_close → 计算 → 发布 `signal`（监控周期与自动周期）  
3) 自动周期满足条件时，strategy 发布 `trade_plan`  
4) execution 消费 trade_plan → 风控 → 下单/管理 → 发布 `execution_report` 与 `risk_event`  
5) notifier 消费 signal/execution_report/risk_event → 发送 Telegram  
6) api 通过 Postgres 查询输出信号、计划、订单、持仓、风险事件

---

## 5. 简化目录规划（仓库结构）
> 目录结构以“5 个服务 + 共享 libs + migrations + configs”为主，避免过度分层。

```text
repo/
  README.md
  docker-compose.yml
  .env.example
  configs/
    logging.yaml
    app.yaml
  migrations/
    postgres/
      V001__init.sql
      V002__tables.sql
      V003__indexes.sql
  libs/
    common/
      config.py
      logging.py
      time.py
      id.py
    db/
      pg.py
      models.md
    mq/
      redis_streams.py
      schema_validator.py
    bybit/
      rest.py
      ws.py
      types.md
    schemas/
      common/
        event-envelope.json
        timeframe.json
      streams/
        bar-close.json
        signal.json
        trade-plan.json
        execution-report.json
        risk-event.json
  services/
    marketdata/
      README.md
      main.py
      handlers/
    strategy/
      README.md
      main.py
      handlers/
    execution/
      README.md
      main.py
      handlers/
    notifier/
      README.md
      main.py
      handlers/
    api/
      README.md
      main.py
      routes/
  scripts/
    init_streams.py
    healthcheck.sh
  docs/
    adr/
```

### 5.1 目录设计约束
- `services/*` 内仅放本服务入口、handlers、与本服务强耦合的逻辑
- 公共能力（配置、日志、DB、Redis Streams、Bybit 客户端、Schema 校验）统一放入 `libs/*`
- 事件契约（JSON Schema）存放在 `libs/schemas/*`，作为联调唯一依据
- 数据库变更只通过 `migrations/postgres/*` 管理

---

## 6. 配置与运行参数（概要）
### 6.1 必备连接参数
- `DATABASE_URL`：外部 Postgres 连接
- `REDIS_URL`：外部 Redis 连接
- `REDIS_STREAM_GROUP`、`REDIS_STREAM_CONSUMER`：consumer group/consumer 名称

### 6.2 交易与风控参数（核心）
- `risk_pct`
- `max_open_positions_default`
- `ACCOUNT_KILL_SWITCH_ENABLED`
- `DAILY_LOSS_LIMIT_PCT`
- `min_confirmations`（固定 2）
- `AUTO_TIMEFRAMES`：1h/4h/1d
- `MONITOR_TIMEFRAMES`：15m/30m/8h

---

## 7. 数据库表（概要）
> 表字段以规范为准；本章节给出最小集合与用途边界。

- bars：存储 K 线收盘数据
- indicator_snapshots：每根收盘 K 的指标快照（MACD/EMA/ATR/RSI/OBV/FVG 等）
- pivot_points：pivotHigh/Low 与指标 pivot 点
- divergence_signals：背离检测产物与证据链
- three_segment_setups：三段结构识别产物
- entry_triggers：入场触发记录（收盘确认时）
- trade_plans：交易计划（plan_id, idempotency_key, entry/sl/tp/追踪止损等）
- orders / fills / positions：订单与成交、持仓
- risk_events：风险/拒绝/熔断/回连/缺口事件
- notifications：通知发送记录与重试状态

---

## 8. 事件契约（JSON Schema）
> 本章节为契约优先联调标准。所有服务的 publish/consume 必须以此为唯一依据。

### 8.1 通用 Envelope
```json
{
  "$id": "https://schemas.local/common/event-envelope.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EventEnvelope",
  "type": "object",
  "required": [
    "event_id",
    "ts_ms",
    "env",
    "service"
  ],
  "properties": {
    "event_id": {
      "type": "string",
      "minLength": 8
    },
    "ts_ms": {
      "type": "integer",
      "minimum": 0
    },
    "env": {
      "type": "string",
      "enum": [
        "dev",
        "staging",
        "prod"
      ]
    },
    "service": {
      "type": "string",
      "enum": [
        "marketdata-service",
        "strategy-service",
        "execution-service",
        "notifier-service",
        "api-service"
      ]
    },
    "trace_id": {
      "type": "string"
    },
    "schema_version": {
      "type": "integer",
      "minimum": 1
    },
    "meta": {
      "type": "object",
      "description": "可选元信息：路由、版本、来源、延迟等"
    },
    "payload": {
      "type": "object"
    },
    "ext": {
      "type": "object",
      "description": "可选扩展字段容器：前向兼容"
    }
  },
  "additionalProperties": false
}
```

### 8.2 Timeframe
```json
{
  "$id": "https://schemas.local/common/timeframe.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Timeframe",
  "type": "string",
  "enum": [
    "15m",
    "30m",
    "1h",
    "4h",
    "8h",
    "1d"
  ]
}
```

### 8.3 stream:bar_close
```json
{
  "$id": "https://schemas.local/streams/bar-close.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "BarCloseEvent",
  "allOf": [
    {
      "$ref": "https://schemas.local/common/event-envelope.json"
    }
  ],
  "required": [
    "event_id",
    "ts_ms",
    "env",
    "service",
    "payload"
  ],
  "properties": {
    "payload": {
      "type": "object",
      "required": [
        "symbol",
        "timeframe",
        "close_time_ms"
      ],
      "properties": {
        "symbol": {
          "type": "string",
          "pattern": "^[A-Z0-9]{3,12}USDT$"
        },
        "timeframe": {
          "$ref": "https://schemas.local/common/timeframe.json"
        },
        "close_time_ms": {
          "type": "integer",
          "minimum": 0
        },
        "is_final": {
          "type": "boolean"
        },
        "source": {
          "type": "string",
          "enum": [
            "bybit_ws",
            "bybit_rest"
          ]
        },
        "ohlcv": {
          "type": "object",
          "properties": {
            "open": {
              "type": "number"
            },
            "high": {
              "type": "number"
            },
            "low": {
              "type": "number"
            },
            "close": {
              "type": "number"
            },
            "volume": {
              "type": "number",
              "minimum": 0
            }
          },
          "additionalProperties": false
        },
        "ext": {
          "type": "object"
        }
      },
      "additionalProperties": false
    }
  }
}
```

### 8.4 stream:signal
```json
{
  "$id": "https://schemas.local/streams/signal.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SignalEvent",
  "allOf": [
    {
      "$ref": "https://schemas.local/common/event-envelope.json"
    }
  ],
  "properties": {
    "payload": {
      "type": "object",
      "required": [
        "symbol",
        "timeframe",
        "close_time_ms",
        "bias",
        "vegas_state",
        "confirmations"
      ],
      "properties": {
        "symbol": {
          "type": "string",
          "pattern": "^[A-Z0-9]{3,12}USDT$"
        },
        "timeframe": {
          "$ref": "https://schemas.local/common/timeframe.json"
        },
        "close_time_ms": {
          "type": "integer",
          "minimum": 0
        },
        "setup_id": {
          "type": "string"
        },
        "trigger_id": {
          "type": "string"
        },
        "bias": {
          "type": "string",
          "enum": [
            "LONG",
            "SHORT"
          ]
        },
        "vegas_state": {
          "type": "string",
          "enum": [
            "Bullish",
            "Bearish",
            "Neutral"
          ]
        },
        "confirmations": {
          "type": "object",
          "required": [
            "min_required",
            "hit_count",
            "hits"
          ],
          "properties": {
            "min_required": {
              "type": "integer",
              "enum": [
                2
              ]
            },
            "hit_count": {
              "type": "integer",
              "minimum": 0
            },
            "hits": {
              "type": "array",
              "items": {
                "type": "string",
                "enum": [
                  "ENGULFING",
                  "RSI_DIV",
                  "OBV_DIV",
                  "FVG_PROXIMITY"
                ]
              }
            }
          },
          "additionalProperties": false
        },
        "lifecycle": {
          "type": "object",
          "properties": {
            "status": {
              "type": "string",
              "enum": [
                "PENDING_CONFIRM",
                "CONFIRMED",
                "PLANNED",
                "EXECUTED",
                "EXPIRED",
                "CANCELLED"
              ]
            },
            "valid_from_ms": {
              "type": "integer",
              "minimum": 0
            },
            "expires_at_ms": {
              "type": "integer",
              "minimum": 0
            }
          },
          "additionalProperties": false
        },
        "signal_score": {
          "type": "integer",
          "minimum": 0,
          "maximum": 100
        },
        "divergence_strength": {
          "type": "integer",
          "minimum": 0,
          "maximum": 100
        },
        "market_state": {
          "type": "string",
          "enum": [
            "NORMAL",
            "HIGH_VOL",
            "NEWS_WINDOW"
          ]
        },
        "ext": {
          "type": "object"
        }
      },
      "additionalProperties": false
    }
  }
}
```

### 8.5 stream:trade_plan
```json
{
  "$id": "https://schemas.local/streams/trade-plan.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "TradePlanEvent",
  "allOf": [
    {
      "$ref": "https://schemas.local/common/event-envelope.json"
    }
  ],
  "properties": {
    "payload": {
      "type": "object",
      "required": [
        "plan_id",
        "idempotency_key",
        "symbol",
        "timeframe",
        "side",
        "entry_price",
        "primary_sl_price",
        "tp_rules",
        "secondary_sl_rule",
        "traceability"
      ],
      "properties": {
        "plan_id": {
          "type": "string"
        },
        "idempotency_key": {
          "type": "string",
          "minLength": 8
        },
        "symbol": {
          "type": "string",
          "pattern": "^[A-Z0-9]{3,12}USDT$"
        },
        "timeframe": {
          "$ref": "https://schemas.local/common/timeframe.json"
        },
        "side": {
          "type": "string",
          "enum": [
            "BUY",
            "SELL"
          ]
        },
        "entry_price": {
          "type": "number",
          "exclusiveMinimum": 0
        },
        "primary_sl_price": {
          "type": "number",
          "exclusiveMinimum": 0
        },
        "tp_rules": {
          "type": "object",
          "required": [
            "tp1",
            "tp2",
            "tp3_trail"
          ],
          "properties": {
            "tp1": {
              "type": "object",
              "required": [
                "r",
                "pct"
              ],
              "properties": {
                "r": {
                  "type": "number",
                  "enum": [
                    1.0
                  ]
                },
                "pct": {
                  "type": "number",
                  "enum": [
                    0.4
                  ]
                }
              },
              "additionalProperties": false
            },
            "tp2": {
              "type": "object",
              "required": [
                "r",
                "pct"
              ],
              "properties": {
                "r": {
                  "type": "number",
                  "enum": [
                    2.0
                  ]
                },
                "pct": {
                  "type": "number",
                  "enum": [
                    0.4
                  ]
                }
              },
              "additionalProperties": false
            },
            "tp3_trail": {
              "type": "object",
              "required": [
                "pct",
                "mode"
              ],
              "properties": {
                "pct": {
                  "type": "number",
                  "enum": [
                    0.2
                  ]
                },
                "mode": {
                  "type": "string",
                  "enum": [
                    "ATR",
                    "PIVOT"
                  ]
                }
              },
              "additionalProperties": false
            },
            "reduce_only": {
              "type": "boolean",
              "enum": [
                true
              ]
            }
          },
          "additionalProperties": false
        },
        "secondary_sl_rule": {
          "type": "object",
          "required": [
            "type"
          ],
          "properties": {
            "type": {
              "type": "string",
              "enum": [
                "NEXT_BAR_NOT_SHORTEN_EXIT"
              ]
            }
          },
          "additionalProperties": true
        },
        "risk_params": {
          "type": "object",
          "properties": {
            "risk_pct": {
              "type": "number",
              "minimum": 0,
              "maximum": 1
            },
            "max_open_positions_default": {
              "type": "integer",
              "minimum": 1,
              "maximum": 10
            },
            "risk_multiplier": {
              "type": "number",
              "minimum": 0,
              "description": "可选：基于评分/波动率的风险系数"
            }
          },
          "additionalProperties": true
        },
        "confluence": {
          "type": "object",
          "properties": {
            "vegas_state": {
              "type": "string",
              "enum": [
                "Bullish",
                "Bearish",
                "Neutral"
              ]
            },
            "confirmations": {
              "$ref": "https://schemas.local/streams/signal.json#/properties/payload/properties/confirmations"
            },
            "signal_score": {
              "type": "integer",
              "minimum": 0,
              "maximum": 100
            }
          },
          "additionalProperties": true
        },
        "traceability": {
          "type": "object",
          "required": [
            "setup_id",
            "trigger_id"
          ],
          "properties": {
            "setup_id": {
              "type": "string"
            },
            "trigger_id": {
              "type": "string"
            }
          },
          "additionalProperties": false
        },
        "ext": {
          "type": "object"
        }
      },
      "additionalProperties": false
    }
  }
}
```

### 8.6 stream:execution_report
```json
{
  "$id": "https://schemas.local/streams/execution-report.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ExecutionReportEvent",
  "allOf": [
    {
      "$ref": "https://schemas.local/common/event-envelope.json"
    }
  ],
  "properties": {
    "payload": {
      "type": "object",
      "required": [
        "plan_id",
        "status"
      ],
      "properties": {
        "plan_id": {
          "type": "string"
        },
        "order_id": {
          "type": "string"
        },
        "status": {
          "type": "string",
          "enum": [
            "ORDER_SUBMITTED",
            "ORDER_REJECTED",
            "PARTIAL_FILLED",
            "FILLED",
            "TP_HIT",
            "PRIMARY_SL_HIT",
            "SECONDARY_SL_EXIT",
            "POSITION_CLOSED"
          ]
        },
        "reason": {
          "type": "string"
        },
        "filled_qty": {
          "type": "number",
          "minimum": 0
        },
        "avg_price": {
          "type": "number",
          "minimum": 0
        },
        "symbol": {
          "type": "string"
        },
        "timeframe": {
          "$ref": "https://schemas.local/common/timeframe.json"
        },
        "latency_ms": {
          "type": "integer",
          "minimum": 0
        },
        "slippage_bps": {
          "type": "number"
        },
        "retry_count": {
          "type": "integer",
          "minimum": 0
        },
        "ext": {
          "type": "object"
        }
      },
      "additionalProperties": false
    }
  }
}
```

### 8.7 stream:risk_event
```json
{
  "$id": "https://schemas.local/streams/risk-event.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RiskEvent",
  "allOf": [
    {
      "$ref": "https://schemas.local/common/event-envelope.json"
    }
  ],
  "properties": {
    "payload": {
      "type": "object",
      "required": [
        "type",
        "detail"
      ],
      "properties": {
        "type": {
          "type": "string",
          "enum": [
            "RISK_REJECTED",
            "KILL_SWITCH_ON",
            "DATA_GAP",
            "DATA_LAG",
            "WS_RECONNECT",
            "RATE_LIMIT",
            "SIGNAL_CONFLICT",
            "IDEMPOTENCY_CONFLICT",
            "POSITION_MUTEX_BLOCKED",
            "COOLDOWN_BLOCKED",
            "MAX_POSITIONS_BLOCKED"
          ]
        },
        "severity": {
          "type": "string",
          "enum": [
            "CRITICAL",
            "IMPORTANT",
            "INFO"
          ]
        },
        "symbol": {
          "type": "string"
        },
        "retry_after_ms": {
          "type": "integer",
          "minimum": 0
        },
        "detail": {
          "type": "object"
        },
        "ext": {
          "type": "object"
        }
      },
      "additionalProperties": false
    }
  }
}
```

---

## 9. 开发阶段与 Issue 列表（按模块可分配）

> 本章节内容用于直接拆分任务并分配到开发人员。每条 Issue 均包含验收口径（AC）。

### 9.1 阶段 0：基础设施与骨架（INF）
**交付范围**：多服务目录、统一配置/日志/健康检查、PG schema、Redis Streams 与 consumer group 初始化、compose 仅业务服务外连 DB/Redis。

- **INF-001 仓库骨架与多服务目录落地**
  - AC：包含 `services/marketdata|strategy|execution|notifier|api`；公共库 `libs/`；各服务可独立启动（空跑可）。
- **INF-002 统一配置加载（ENV + 配置文件）**
  - AC：所有服务共享配置读取/校验；必填缺失启动失败并输出明确错误。
- **INF-003 统一日志规范（结构化日志 + trace_id）**
  - AC：所有服务输出统一字段：ts、level、service、event、trace_id（可选但保留字段）。
- **INF-004 健康检查与 readiness/liveness**
  - AC：每服务提供 `/health`，返回 env、service、version、依赖连通性（DB/Redis/Bybit）。
- **INF-005 docker-compose（仅业务服务，外部 DB/Redis）**
  - AC：compose 只包含 5 个业务服务；通过 `DATABASE_URL`、`REDIS_URL` 外连即可运行。
- **INF-006 Postgres Schema 初始化脚本（最小表集）**
  - AC：一键初始化；包含必要 PK/唯一键（`trade_plans.idempotency_key`）。
- **INF-007 Redis Streams & consumer group 初始化**
  - AC：启动时自动创建 stream（如不存在）与 group（幂等）。
- **INF-008 事件消息 Envelope 校验器（契约优先）**
  - AC：publish/consume 均进行 schema 校验；不合规消息进入 dead-letter（或落库+告警）。

### 9.2 阶段 1：行情闭环（marketdata-service，MD）
**交付范围**：Bybit K 线订阅与收盘确认、缺口补齐与回填、bars 落库、发布 `stream:bar_close`。

- **MD-001 Bybit 行情接入（WS + REST 客户端封装）**
  - AC：支持 linear USDT 永续；支持配置 base_url/ws_url。
- **MD-002 K 线订阅与收盘确认驱动**
  - AC：仅在 `bar.is_final=true` 时生成 `bar_close` 事件。
- **MD-003 bars 落库（bars 表）**
  - AC：同一 (symbol,timeframe,close_time_ms) 幂等 upsert。
- **MD-004 数据缺口检测 + 回填**
  - AC：检测 close_time_ms 不连续，用 REST 回补并补写 bars；按时间顺序补发 bar_close。
- **MD-005 发布事件：`stream:bar_close`**
  - AC：事件包含 Envelope + 业务字段（见事件契约）。
- **MD-006 异常事件：DATA_GAP / WS_RECONNECT**
  - AC：断线/缺口产生 `risk_event`（供 notifier 消费）。

### 9.3 阶段 2：策略引擎（strategy-service，ST）
**交付范围**：指标计算、pivot/背离/三段结构识别、Vegas 强门槛 + min_confirmations=2、落库 setup/trigger/plan、发布 `signal` 与 `trade_plan`。

- **ST-001 指标快照计算与落库（indicator_snapshots）**
  - AC：按 close_time_ms 生成快照；幂等。
- **ST-002 Pivot 检测（价格 pivotHigh/Low + 指标 pivot）**
  - AC：写入 pivot_points；left/right bars 可配置。
- **ST-003 背离检测（divergence_signals）**
  - AC：支持 MACD_HIST/RSI/OBV 背离产出；记录证据链 filters_jsonb。
- **ST-004 三段顶/底背离 Setup 识别（three_segment_setups）**
  - AC：识别三段结构并满足“两次缩短 + 段落分隔”。
- **ST-005 入场触发（entry_triggers）：收盘确认触发**
  - AC：仅在确认柱收盘时生成 trigger。
- **ST-006 共振门槛：Vegas 同向强门槛（必须满足）**
  - AC：计算 vegas_state 并写入事件/落库。
- **ST-007 共振门槛：确认数门槛（min_confirmations=2）**
  - AC：输出 confirmations 明细（命中项列表 + count）。
- **ST-008 发布事件：`stream:signal`（监控周期 & 自动周期）**
  - AC：监控周期（15m/30m/8h）只发 signal，不发 trade_plan。
- **ST-009 发布事件：`stream:trade_plan`（仅自动周期 1h/4h/1d）**
  - AC：生成 plan_id + idempotency_key；落库 trade_plans；可追溯 setup/trigger。

### 9.4 阶段 3：执行与风控（execution-service，EX）
**交付范围**：仓位计算、最大持仓、互斥、冷却、熔断、自动下单 entry+SL+TP、次日退出、对账、发布 execution_report/risk_event。

- **EX-001 账户权益/持仓/订单状态同步（WS+REST）**
  - AC：断线可恢复；订单→成交→持仓一致；状态落库。
- **EX-002 风控：risk_pct 定仓 + 交易所最小下单量/步进校验**
  - AC：不满足则拒单并发 `RISK_REJECTED`。
- **EX-003 风控：最大同时持仓数（默认 3，可配 1~10）**
  - AC：超限拒绝计划执行并产生风险事件。
- **EX-004 风控：同币种同向互斥 + 周期优先级（1d > 4h > 1h）**
  - AC：已有仓位则低优先级计划不下单，仅记录与告警。
- **EX-005 风控：冷却机制（止损后按周期 bars）**
  - AC：冷却期内同 symbol 禁止新开仓。
- **EX-006 幂等：plan 幂等锁（lock:plan:{idempotency_key}）**
  - AC：同一 plan 重复消费不重复下单。
- **EX-007 下单：entry + Primary SL + TP（规则化）**
  - AC：TP 拆分比例正确；reduce-only；追踪止损模式（ATR/PIVOT）。
- **EX-008 次日规则退出（SECONDARY_SL_EXIT）+ 撤销所有 TP 单**
  - AC：触发条件严格；退出后落库并发布 execution_report。
- **EX-009 账户级熔断（可开关）**
  - AC：熔断 ON 后禁止新开仓；发 `KILL_SWITCH_ON`。
- **EX-010 发布事件：execution_report / risk_event**
  - AC：覆盖下单/成交/止盈/止损/次日退出/风控拒绝/熔断等状态。

### 9.5 阶段 4：通知与 API（notifier-service / api-service）
**交付范围**：Telegram 告警全覆盖、通知落库与重试、HTTP 查询接口。

#### notifier-service（NT）
- **NT-001 Telegram 通道集成（机器人/群/私聊）**
  - AC：可配置 target；失败自动重试并落库 notifications。
- **NT-002 消息模板：覆盖全量事件**
  - AC：每种事件包含 symbol/timeframe（如适用）、关键价格/数量、plan_id、原因 reason。
- **NT-003 通知幂等与重试策略**
  - AC：同一 event_id 不重复发送；重试策略可配置；最终失败标记状态。

#### api-service（API）
- **API-001 HTTP API：最小接口集合**
  - AC：实现 `/health`、`/v1/signals`、`/v1/trade-plans`、`/v1/orders`、`/v1/positions`、`/v1/risk-events`、`/v1/config`。
- **API-002 运行配置读取脱敏**
  - AC：敏感字段脱敏；输出结构固定。

### 9.6 阶段 5（可选）：回放/回测与一致性验证
- **BT-001 从 bars 表回放并重放事件**
  - AC：可按 symbol/timeframe/time range 回放；输出一致性校验报表。

---

## 12. 数据质量与市场状态控制（不改变策略规则）
本章节定义**数据质量监控**与**市场状态过滤/标记**能力，用于提升信号可靠性与系统稳健性；默认行为不改变现有策略触发与执行路径，仅在启用对应开关时生效。

### 12.1 数据源与冗余
- 主数据源：Bybit 官方 API（WS/REST）
- 备用数据源（预留）：第三方行情源 A/B（仅用于对比校验与缺口回填兜底）
- 数据质量监控：实时检测 **延迟、缺口、异常跳变、重复 bar、成交量异常**，并形成 `stream:risk_event`（type=DATA_LAG/DATA_GAP 等）。

### 12.2 数据一致性校验（关键数据双机制）
- 账户余额/持仓：推送（WS）与轮询（REST）双机制确认；出现差异时记录 `risk_event` 并触发对账流程。
- 订单状态：推送 + 轮询；超时未更新进入重试/撤单处理（见 14.3）。

### 12.3 波动率/事件窗口标记（可配置）
- 波动率过滤（可配置启用）：当 ATR/波动率显著放大时，将市场状态标记为 `HIGH_VOL`；可用于暂停新开仓或降低 risk_pct。
- 新闻/事件窗口（可配置启用）：对接日历或人工配置时间窗，标记 `NEWS_WINDOW`（默认仅标记，不强制改变策略执行）。

---

## 13. 信号质量评分与生命周期管理（不改变策略规则）
本章节引入**质量评分**与**生命周期状态机**，用于排序、追溯与参数分析；默认不影响信号是否产生。执行端可按配置选择是否基于评分改变优先级或仓位系数。

### 13.1 分形点确认与三段结构稳健性（可选增强）
- 分形点确认：在 pivot_points 的极值检测中引入 Williams 分形（或同等局部转折确认）作为可选检测方法。
- 成交量确认（可选）：极值点附近成交量相对放大（阈值可配置）时，提高结构可靠性评分。
- 时间对称性检查（可选）：三段之间 bars 数量差异不超过阈值时，提高结构可靠性评分。

> 注：以上为“评分/标记”能力；若不启用过滤开关，则仅做记录不影响策略触发。

### 13.2 背离强度量化（评分组件）
输出 `divergence_strength`（0~100）或分项指标，包含但不限于：
- 价格幅度差异（第三段相对第二段的高低点差）
- MACD 柱缩短比例（如 ≥15% 计入强度加分）
- 价格与指标背离斜率差（线性回归斜率/角度）

### 13.3 信号质量评分（0~100）
- 输入：背离强度、共振命中数、Vegas 状态、市场状态（NORMAL/HIGH_VOL/NEWS_WINDOW 等）、时间框架一致性标记等
- 输出：`signal_score`（0~100）与 `score_breakdown`（可选）

### 13.4 信号生命周期
为每个 signal/trade_plan 建立状态与有效期字段：
- 状态：`PENDING_CONFIRM` → `CONFIRMED` → `PLANNED` → `EXECUTED` → `EXPIRED/CANCELLED`
- 有效期：`valid_from_ms` / `expires_at_ms`
- 冲突处理（规则层面不变）：同方向可合并记录，反方向以“互斥/取消计划”记录为主，并形成 `risk_event`（type=SIGNAL_CONFLICT）。

---

## 14. 订单执行质量与异常处理（不改变策略规则）
本章节增强执行端的**鲁棒性、滑点监控与重试策略**，不改变核心策略入场/出场定义。

### 14.1 执行质量指标
- `latency_ms`：trade_plan → 下单提交 → 成交确认延迟
- `slippage_bps`：成交均价相对计划价的偏差（bps）
- `fill_ratio`：计划数量与最终成交数量比例
上述指标写入 orders/fills 或随 `execution_report` 输出，便于复盘。

### 14.2 下单方式与拆单（预留）
- 依据盘口深度/流动性选择限价/市价/条件单（可配置）
- 大单拆分为小单（可配置启用），降低冲击成本
- iceberg/隐藏委托（若交易所支持）作为扩展能力（预留）

### 14.3 异常处理流程（必备）
- 订单超时未成交：自动撤销并按策略（重试/改价/降级市价）执行；所有动作形成 `execution_report` 与 `risk_event`。
- 部分成交：按计划剩余量处理（继续挂单/撤单/市价补齐），并记录 fill 明细。
- API 限频（Rate Limit）：进入退避重试（exponential backoff），同时发 `risk_event`（type=RATE_LIMIT，含 retry_after_ms）。

---

## 15. 监控与告警分级（可扩展）
当前实现以 Telegram 为主；本章节定义**分级字段与路由规则**，为后续短信/电话/邮件预留。

### 15.1 告警等级
- `CRITICAL`：系统故障、熔断触发、数据长期断流
- `IMPORTANT`：订单异常、数据延迟、信号冲突
- `INFO`：常规交易活动、状态变化

### 15.2 健康度指标（可观测性）
- 系统健康度：API 连通性、数据处理延迟、内存/CPU、consumer lag
- 策略健康度：信号命中率、盈亏分布、最大回撤（基于 execution_report 汇总）
- 账户健康度：资金利用率、杠杆、保证金比例（从账户同步模块获取）

---

## 16. 实施路径与测试矩阵（不改变策略规则）
### 16.1 里程碑阶段
- 阶段 0~1：基础框架 + 行情闭环（bars、bar_close、缺口回填）
- 阶段 2：策略引擎与信号/计划生成（含评分与生命周期字段）
- 阶段 3：执行与风控（幂等、互斥、冷却、熔断、次日退出）
- 阶段 4：通知与 API（告警全覆盖、查询接口）
- 阶段 5（可选）：回放/回测与一致性验证

### 16.2 测试矩阵（最小要求）
- 单元：指标计算、pivot/背离/三段识别、仓位计算、互斥/冷却、熔断逻辑
- 集成：bar_close→signal→trade_plan→execution_report→notifier 全链路
- 回放：从 bars 回放重放事件，对齐输出与落库一致性
- 压力：高频 symbol/多 timeframe 并发、Redis lag、API 限频与重连恢复
- 边界：缺口回填、重复消息、断线重连、部分成交、极端波动窗口（仅标记）

---

## 17. 风险与注意事项（工程与运营）
### 17.1 技术风险
- API 限频与并发：必须内置限流与退避重试；关键请求要有优先级。
- 网络延迟：跨地域部署会放大下单延迟；需监控 latency_ms。
- 外部依赖：第三方数据源为兜底用途；不可成为单点关键路径。

### 17.2 运营与安全
- API 密钥：最小权限、IP 白名单（如交易所支持）、密钥轮换流程。
- 访问控制：API 服务查询接口需鉴权（预留），配置输出需脱敏。
- 应急预案：熔断触发、数据断流、交易所故障的处置流程与演练记录。

### 17.3 市场风险
- 流动性：小市值币种滑点风险高；执行端需监控 slippage_bps 并可触发风控事件。
- 极端行情：黑天鹅期间允许仅标记 HIGH_VOL/NEWS_WINDOW；是否暂停交易由配置决定。


## 10. 非功能性要求（NFR）
- 幂等：trade_plan 消费必须幂等；同一 idempotency_key 不重复下单
- 可观测性：关键路径必须有结构化日志；风险/拒绝/熔断必须形成事件并可查询
- 可靠性：WS 断线自动重连；数据缺口自动回填；通知失败可重试并可追溯
- 安全：配置输出脱敏；密钥仅通过环境变量注入，不落库/不打印明文

---

## 11. 验收基线（Definition of Done）
- 五服务可通过 docker-compose 启动（外连外部 Postgres/Redis）
- bar_close → signal/trade_plan → execution_report/risk_event → Telegram 通知闭环打通
- API 查询可回溯：signals / trade_plans / orders / positions / risk_events
- 事件契约与表结构落地可被自动校验（schema 校验 + 迁移脚本）
