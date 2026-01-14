-- Stage 1：事件契约对齐（execution_report / risk_event）
--
-- 说明：为了保持向后兼容，本迁移不删除旧列（type/severity/idempotency_key 等），
-- 仅新增 schema 定义中的关键字段，供 API 查询与 notifier 渲染使用。

-- execution_reports: add schema-aligned columns
ALTER TABLE execution_reports
  ADD COLUMN IF NOT EXISTS plan_id TEXT,
  ADD COLUMN IF NOT EXISTS status TEXT,
  ADD COLUMN IF NOT EXISTS timeframe TEXT,
  ADD COLUMN IF NOT EXISTS filled_qty DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS avg_price DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS reason TEXT,
  ADD COLUMN IF NOT EXISTS retry_count INTEGER,
  ADD COLUMN IF NOT EXISTS latency_ms INTEGER,
  ADD COLUMN IF NOT EXISTS slippage_bps DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS ext JSONB;

CREATE INDEX IF NOT EXISTS idx_exec_reports_plan_time
  ON execution_reports(plan_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_exec_reports_status_time
  ON execution_reports(status, created_at DESC);

-- risk_events: add optional fields for better observability
ALTER TABLE risk_events
  ADD COLUMN IF NOT EXISTS symbol TEXT,
  ADD COLUMN IF NOT EXISTS retry_after_ms INTEGER,
  ADD COLUMN IF NOT EXISTS ext JSONB;

CREATE INDEX IF NOT EXISTS idx_risk_events_symbol_time
  ON risk_events(symbol, ts_ms DESC);
