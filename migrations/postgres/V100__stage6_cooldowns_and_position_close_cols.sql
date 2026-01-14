-- Stage 6：执行闸门（最大持仓/互斥/冷却）所需表结构

-- 1) positions 补充“关闭信息”（不影响现有写入逻辑；旧代码忽略这些列即可）
ALTER TABLE IF EXISTS positions
  ADD COLUMN IF NOT EXISTS closed_at_ms BIGINT,
  ADD COLUMN IF NOT EXISTS exit_reason TEXT;

-- 2) cooldowns：止损后冷却记录（按 symbol+side+timeframe）
CREATE TABLE IF NOT EXISTS cooldowns (
  cooldown_id  TEXT PRIMARY KEY,
  symbol       TEXT NOT NULL,
  side         TEXT NOT NULL,
  timeframe    TEXT NOT NULL,
  reason       TEXT NOT NULL,
  until_ts_ms  BIGINT NOT NULL,
  meta         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cooldowns_symbol_side_tf_until
  ON cooldowns(symbol, side, timeframe, until_ts_ms DESC);
