-- Phase 6：账户级风控状态机（不改变策略，只限制执行）

CREATE TABLE IF NOT EXISTS risk_state (
  trade_date        DATE PRIMARY KEY,
  mode              TEXT NOT NULL, -- live/paper
  starting_equity   DOUBLE PRECISION,
  current_equity    DOUBLE PRECISION,
  min_equity        DOUBLE PRECISION,
  max_equity        DOUBLE PRECISION,
  drawdown_pct      DOUBLE PRECISION,
  soft_halt         BOOLEAN NOT NULL DEFAULT FALSE,
  hard_halt         BOOLEAN NOT NULL DEFAULT FALSE,
  kill_switch       BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  meta              JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS risk_events (
  event_id      TEXT PRIMARY KEY,
  trade_date    DATE NOT NULL,
  ts_ms         BIGINT NOT NULL,
  type          TEXT NOT NULL,
  severity      TEXT NOT NULL,
  detail        JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_risk_events_date_time
  ON risk_events(trade_date, ts_ms DESC);
