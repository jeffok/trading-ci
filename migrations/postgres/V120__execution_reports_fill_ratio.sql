-- Stage 8: execution quality metrics (fill_ratio)
ALTER TABLE execution_reports
  ADD COLUMN IF NOT EXISTS fill_ratio DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_exec_reports_fill_ratio
  ON execution_reports(fill_ratio);
