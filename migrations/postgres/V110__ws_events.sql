-- Stage 7: WS audit table for private websocket events
CREATE TABLE IF NOT EXISTS ws_events (
  id           BIGSERIAL PRIMARY KEY,
  topic        TEXT NOT NULL,
  symbol       TEXT,
  received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload      JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ws_events_topic_time ON ws_events(topic, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_ws_events_symbol_time ON ws_events(symbol, received_at DESC);
