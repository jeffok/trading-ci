# marketdata-service

## Phase 1 功能
- 连接 Bybit 公共 WS（linear）订阅 Kline
- 仅当 candle 收盘（confirm=true）时：
  - upsert bars 表
  - 发布 stream:bar_close 事件
- 由于 Bybit 不提供 8h interval，内部用 1h bar 聚合生成 8h bar

## 环境变量
- MARKETDATA_SYMBOLS=BTCUSDT,ETHUSDT
- MARKETDATA_TIMEFRAMES=15m,30m,1h,4h,8h,1d
- MARKETDATA_ENABLE_REST_BACKFILL=true/false
- MARKETDATA_BACKFILL_LIMIT=500


## Stage 2：缺口检测与回填（Gapfill）
- 当收到 WS 收盘 candle 时，会对比 DB 中上一根 bar 的 close_time_ms
- 若发现缺口：发布 `risk_event: DATA_GAP`，并用 REST 回补缺口范围 bars
- 回补完成后：按时间顺序补发 `stream:bar_close`（幂等，避免重复补发）
- WS 重连：发布 `risk_event: WS_RECONNECT`
- 回补完成：发布 `risk_event: BACKFILL_DONE`
