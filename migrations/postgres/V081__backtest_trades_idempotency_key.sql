-- Stage 6：REPLAY 回测闭环对比需要：把 idempotency_key 写入 backtest_trades 便于联调核对
ALTER TABLE backtest_trades
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_idem
  ON backtest_trades(run_id, idempotency_key);
