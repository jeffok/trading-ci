-- Stage 3：复盘与可观测性（strategy 中间产物落库）
-- 原则：不改变策略决策，仅把“中间计算结果/结构”持久化，便于追溯与复盘。

-- 1) indicator_snapshots：每次 bar_close 处理时写入一条（可按需关闭或降采样）
CREATE TABLE IF NOT EXISTS indicator_snapshots (
  snapshot_id    TEXT PRIMARY KEY,
  symbol         TEXT NOT NULL,
  timeframe      TEXT NOT NULL,
  close_time_ms  BIGINT NOT NULL,
  kind           TEXT NOT NULL, -- e.g. INDICATORS
  payload        JSONB NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_indicator_snapshots_symbol_tf_time
  ON indicator_snapshots(symbol, timeframe, close_time_ms DESC);

-- 2) setups：结构识别的“setup”（此处：三段背离结构）
CREATE TABLE IF NOT EXISTS setups (
  setup_id        TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  symbol          TEXT NOT NULL,
  timeframe       TEXT NOT NULL,
  close_time_ms   BIGINT NOT NULL,
  bias            TEXT NOT NULL, -- LONG/SHORT
  setup_type      TEXT NOT NULL, -- MACD_3SEG_DIVERGENCE
  payload         JSONB NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_setups_symbol_tf_time
  ON setups(symbol, timeframe, close_time_ms DESC);

-- 3) triggers：确认层“触发”（如 confirmations 命中）
CREATE TABLE IF NOT EXISTS triggers (
  trigger_id      TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  setup_id        TEXT NOT NULL,
  symbol          TEXT NOT NULL,
  timeframe       TEXT NOT NULL,
  close_time_ms   BIGINT NOT NULL,
  bias            TEXT NOT NULL,
  hits            JSONB NOT NULL,
  payload         JSONB NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_triggers_symbol_tf_time
  ON triggers(symbol, timeframe, close_time_ms DESC);

-- 4) pivots：分形 pivot（至少持久化三段背离的 3 个极值点）
CREATE TABLE IF NOT EXISTS pivots (
  pivot_id       TEXT PRIMARY KEY,
  setup_id       TEXT NOT NULL,
  symbol         TEXT NOT NULL,
  timeframe      TEXT NOT NULL,
  pivot_time_ms  BIGINT NOT NULL,
  pivot_price    DOUBLE PRECISION NOT NULL,
  pivot_type     TEXT NOT NULL, -- HIGH/LOW
  segment_no     INT NOT NULL,  -- 1/2/3（三段结构中的序号）
  meta           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pivots_symbol_tf_time
  ON pivots(symbol, timeframe, pivot_time_ms DESC);

CREATE INDEX IF NOT EXISTS idx_pivots_setup
  ON pivots(setup_id);
