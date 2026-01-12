-- Phase 3/4：执行层落库（orders / positions / execution_reports）

CREATE TABLE IF NOT EXISTS orders (
  order_id          TEXT PRIMARY KEY,
  idempotency_key   TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  purpose           TEXT NOT NULL,     -- ENTRY / TP1 / TP2 / EXIT / SL_ADJUST
  side              TEXT NOT NULL,     -- BUY/SELL
  order_type        TEXT NOT NULL,     -- Market/Limit
  qty               DOUBLE PRECISION NOT NULL,
  price             DOUBLE PRECISION,
  reduce_only       BOOLEAN NOT NULL DEFAULT FALSE,
  status            TEXT NOT NULL,     -- NEW/SUBMITTED/FILLED/CANCELED/FAILED
  bybit_order_id    TEXT,
  bybit_order_link_id TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload           JSONB NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_idem_purpose
  ON orders(idempotency_key, purpose);

CREATE TABLE IF NOT EXISTS positions (
  position_id       TEXT PRIMARY KEY,
  idempotency_key   TEXT NOT NULL UNIQUE,
  symbol            TEXT NOT NULL,
  timeframe         TEXT NOT NULL,
  side              TEXT NOT NULL,    -- BUY/SELL
  bias              TEXT NOT NULL,    -- LONG/SHORT
  qty_total         DOUBLE PRECISION NOT NULL,
  qty_runner        DOUBLE PRECISION NOT NULL,
  entry_price       DOUBLE PRECISION NOT NULL,
  primary_sl_price  DOUBLE PRECISION NOT NULL,
  runner_stop_price DOUBLE PRECISION,
  status            TEXT NOT NULL,    -- OPEN/CLOSING/CLOSED/FAILED
  entry_close_time_ms BIGINT NOT NULL,
  opened_at_ms      BIGINT NOT NULL,
  secondary_rule_checked BOOLEAN NOT NULL DEFAULT FALSE,
  hist_entry        DOUBLE PRECISION,
  meta              JSONB NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_positions_symbol_status
  ON positions(symbol, status);

CREATE TABLE IF NOT EXISTS execution_reports (
  report_id       TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL,
  symbol          TEXT NOT NULL,
  type            TEXT NOT NULL,   -- ENTRY_FILLED / TP_FILLED / EXITED / SL_UPDATE / ERROR
  severity        TEXT NOT NULL,   -- INFO/IMPORTANT/EMERGENCY
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload         JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exec_reports_symbol_time
  ON execution_reports(symbol, created_at DESC);
