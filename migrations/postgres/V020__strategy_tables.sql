-- Phase 2：strategy-service 最小落库表（用于复盘/查询）
-- 说明：为了保持迭代速度与代码量可控，Phase 2 采用 JSONB 存储事件 payload，
-- 后续如需做复杂查询再做字段拆分与索引优化。

CREATE TABLE IF NOT EXISTS signals (
  signal_id        TEXT PRIMARY KEY,
  idempotency_key  TEXT NOT NULL UNIQUE,
  symbol           TEXT NOT NULL,
  timeframe        TEXT NOT NULL,
  close_time_ms    BIGINT NOT NULL,
  bias             TEXT NOT NULL,          -- LONG/SHORT
  vegas_state      TEXT NOT NULL,          -- Bullish/Bearish/Neutral
  hit_count        INT NOT NULL,
  hits             JSONB NOT NULL,
  signal_score     INT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload          JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_tf_time
  ON signals(symbol, timeframe, close_time_ms DESC);

CREATE TABLE IF NOT EXISTS trade_plans (
  plan_id          TEXT PRIMARY KEY,
  idempotency_key  TEXT NOT NULL UNIQUE,
  symbol           TEXT NOT NULL,
  timeframe        TEXT NOT NULL,
  close_time_ms    BIGINT NOT NULL,
  side             TEXT NOT NULL,          -- BUY/SELL
  entry_price      DOUBLE PRECISION NOT NULL,
  primary_sl_price DOUBLE PRECISION NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload          JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trade_plans_symbol_tf_time
  ON trade_plans(symbol, timeframe, close_time_ms DESC);
