-- Stage 10: wallet snapshots (WS + REST) for drift detection

CREATE TABLE IF NOT EXISTS wallet_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  ts_ms BIGINT NOT NULL,
  source TEXT NOT NULL, -- WS / REST
  balance_usdt NUMERIC,
  equity_usdt NUMERIC,
  available_usdt NUMERIC,
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wallet_snapshots_ts_ms
  ON wallet_snapshots(ts_ms DESC);

CREATE INDEX IF NOT EXISTS idx_wallet_snapshots_source_ts_ms
  ON wallet_snapshots(source, ts_ms DESC);
