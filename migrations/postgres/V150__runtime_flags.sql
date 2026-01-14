-- Stage 11: runtime flags (simple key/value toggles, e.g., KILL_SWITCH)
CREATE TABLE IF NOT EXISTS runtime_flags (
  name        TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runtime_flags_updated_at
  ON runtime_flags(updated_at DESC);
