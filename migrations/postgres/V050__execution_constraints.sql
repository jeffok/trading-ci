-- Stage 1：执行层约束（max positions / cooldown / mutex）

-- 1) cooldowns：止损后冷却（按 timeframe bars 计算 until_ts_ms）
CREATE TABLE IF NOT EXISTS cooldowns (
  cooldown_id   TEXT PRIMARY KEY,
  symbol        TEXT NOT NULL,
  side          TEXT NOT NULL, -- BUY/SELL
  timeframe     TEXT NOT NULL, -- 1h/4h/1d
  reason        TEXT NOT NULL, -- STOP_LOSS / MANUAL / OTHER
  until_ts_ms   BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  meta          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_cooldowns_symbol_side_tf_until
  ON cooldowns(symbol, side, timeframe, until_ts_ms DESC);

-- 2) positions 上增加 closed_at_ms / exit_reason（如果已存在则跳过）
ALTER TABLE positions ADD COLUMN IF NOT EXISTS closed_at_ms BIGINT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS exit_reason TEXT;
