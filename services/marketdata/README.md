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
