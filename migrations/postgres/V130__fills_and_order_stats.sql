-- Stage 9: Fills table + order stats for execution quality and abnormal handling
-- Adds a dedicated fills table to persist execution details for 14.3
-- and a few helper columns on orders to support timeout/partial-fill handling.

BEGIN;

-- Orders helper columns (keeps backward compatibility; payload remains the source of truth)
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS submitted_at_ms BIGINT,
  ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS filled_qty DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS avg_price DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS last_fill_at_ms BIGINT;

CREATE TABLE IF NOT EXISTS fills (
  fill_id           TEXT PRIMARY KEY,
  order_id          TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  idempotency_key   TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  purpose           TEXT NOT NULL,
  side              TEXT NOT NULL,
  exec_qty          DOUBLE PRECISION NOT NULL,
  exec_price        DOUBLE PRECISION NOT NULL,
  exec_fee          DOUBLE PRECISION,
  exec_time_ms      BIGINT,
  bybit_exec_id     TEXT,
  bybit_order_id    TEXT,
  bybit_order_link_id TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload           JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fills_symbol_time ON fills(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fills_idem_time ON fills(idempotency_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fills_order_time ON fills(order_id, created_at DESC);

COMMIT;
