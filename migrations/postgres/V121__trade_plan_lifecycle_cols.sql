-- Stage 8: trade_plan lifecycle columns (for querying/expiry checks)
ALTER TABLE trade_plans
  ADD COLUMN IF NOT EXISTS status TEXT,
  ADD COLUMN IF NOT EXISTS valid_from_ms BIGINT,
  ADD COLUMN IF NOT EXISTS expires_at_ms BIGINT;

CREATE INDEX IF NOT EXISTS idx_trade_plans_status_time
  ON trade_plans(status, close_time_ms DESC);

CREATE INDEX IF NOT EXISTS idx_trade_plans_expires
  ON trade_plans(expires_at_ms);
