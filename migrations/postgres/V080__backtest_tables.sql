-- Stage 5：回测/模拟盘可观测性补齐（回测结果落库 + 复盘 API）
-- 原则：不改变策略规则，仅增强“可复现、可查询、可追溯”。

CREATE TABLE IF NOT EXISTS backtest_runs (
  run_id        TEXT PRIMARY KEY,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  symbol        TEXT NOT NULL,
  timeframe     TEXT NOT NULL,
  start_time_ms BIGINT,
  end_time_ms   BIGINT,
  params        JSONB NOT NULL,
  summary       JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_symbol_tf_created
  ON backtest_runs(symbol, timeframe, created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_trades (
  trade_id      TEXT PRIMARY KEY,
  run_id        TEXT NOT NULL,
  symbol        TEXT NOT NULL,
  timeframe     TEXT NOT NULL,
  entry_time_ms BIGINT NOT NULL,
  exit_time_ms  BIGINT NOT NULL,
  side          TEXT NOT NULL, -- LONG/SHORT
  entry_price   DOUBLE PRECISION NOT NULL,
  exit_price    DOUBLE PRECISION NOT NULL,
  pnl_r         DOUBLE PRECISION NOT NULL,
  reason        TEXT NOT NULL,
  legs          JSONB NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
  ON backtest_trades(run_id, entry_time_ms ASC);
