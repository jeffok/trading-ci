-- Stage 2：bar_close 事件幂等发射记录（避免重复补发/重放）

CREATE TABLE IF NOT EXISTS bar_close_emits (
  symbol        TEXT NOT NULL,
  timeframe     TEXT NOT NULL,
  close_time_ms BIGINT NOT NULL,
  event_id      TEXT NOT NULL,
  source        TEXT NOT NULL,
  emitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(symbol, timeframe, close_time_ms)
);

CREATE INDEX IF NOT EXISTS idx_bar_close_emits_time
  ON bar_close_emits(emitted_at DESC);
