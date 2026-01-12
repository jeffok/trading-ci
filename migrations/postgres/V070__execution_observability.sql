-- Stage 4：执行复盘增强 + 资金/仓位快照 + 关键路径指标
-- 原则：不改变策略与执行规则，仅增强可观测性与运维排障能力。

-- 1) execution_traces：执行流程关键步骤的结构化日志（可用于复盘、排障、统计滑点/延迟等）
CREATE TABLE IF NOT EXISTS execution_traces (
  trace_row_id   TEXT PRIMARY KEY,
  trace_id       TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  ts_ms          BIGINT NOT NULL,
  stage          TEXT NOT NULL, -- START/ENTRY_PLACED/SL_SET/TP1_PLACED/TP2_PLACED/DONE/ERROR/RECONCILE...
  detail         JSONB NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_execution_traces_idem_time
  ON execution_traces(idempotency_key, ts_ms DESC);

CREATE INDEX IF NOT EXISTS idx_execution_traces_trace
  ON execution_traces(trace_id, ts_ms ASC);

-- 2) account_snapshots：资金/仓位快照（live 从交易所抓取；paper/backtest 可写入派生快照）
CREATE TABLE IF NOT EXISTS account_snapshots (
  snapshot_id     TEXT PRIMARY KEY,
  ts_ms           BIGINT NOT NULL,
  trade_date      DATE NOT NULL,
  mode            TEXT NOT NULL, -- LIVE/PAPER/BACKTEST
  balance_usdt    DOUBLE PRECISION,
  equity_usdt     DOUBLE PRECISION,
  available_usdt  DOUBLE PRECISION,
  unrealized_pnl  DOUBLE PRECISION,
  position_count  INT NOT NULL DEFAULT 0,
  payload         JSONB NOT NULL, -- 原始响应/派生字段
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_account_snapshots_date_time
  ON account_snapshots(trade_date, ts_ms DESC);
