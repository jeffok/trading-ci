-- Stage 3：notifier 落库 + 幂等 + 重试

CREATE TABLE IF NOT EXISTS notifications (
  notification_id TEXT PRIMARY KEY, -- 使用 event_id，天然幂等
  stream          TEXT NOT NULL,
  message_id      TEXT NOT NULL,
  schema          TEXT NOT NULL,
  severity        TEXT NOT NULL,
  text            TEXT NOT NULL,
  status          TEXT NOT NULL, -- PENDING/SENT/FAILED
  attempts        INT NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ,
  last_error      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at         TIMESTAMPTZ,
  meta            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_notifications_status_next
  ON notifications(status, next_attempt_at ASC);

CREATE INDEX IF NOT EXISTS idx_notifications_created
  ON notifications(created_at DESC);
