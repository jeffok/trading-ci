-- Stage 11: signals lifecycle columns (status + valid/expires + updated_at)
ALTER TABLE signals
  ADD COLUMN IF NOT EXISTS status TEXT,
  ADD COLUMN IF NOT EXISTS valid_from_ms BIGINT,
  ADD COLUMN IF NOT EXISTS expires_at_ms BIGINT,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_signals_status_time
  ON signals(status, close_time_ms DESC);

CREATE INDEX IF NOT EXISTS idx_signals_expires
  ON signals(expires_at_ms);
