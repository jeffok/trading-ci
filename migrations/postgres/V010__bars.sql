-- Phase 1：bars 表（最小可用）
-- 说明：用于存储各 timeframe 的 OHLCV（包含派生的 8h）。

CREATE TABLE IF NOT EXISTS bars (
  symbol           TEXT NOT NULL,
  timeframe        TEXT NOT NULL,          -- 15m/30m/1h/4h/8h/1d
  open_time_ms     BIGINT NOT NULL,
  close_time_ms    BIGINT NOT NULL,
  open             DOUBLE PRECISION NOT NULL,
  high             DOUBLE PRECISION NOT NULL,
  low              DOUBLE PRECISION NOT NULL,
  close            DOUBLE PRECISION NOT NULL,
  volume           DOUBLE PRECISION NOT NULL,
  turnover         DOUBLE PRECISION,
  source           TEXT NOT NULL,          -- bybit_ws / bybit_rest / derived_8h
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, timeframe, close_time_ms)
);
