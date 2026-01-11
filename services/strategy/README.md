# strategy-service

## Phase 2 功能
输入：`stream:bar_close`  
输出：
- `stream:signal`（所有周期可输出）
- `stream:trade_plan`（仅自动下单周期：1h/4h/1d）

## 策略（不改变你定义的规则）
- 核心结构：MACD histogram 三段顶/底背离
- 入场：收盘确认（由 marketdata 的 bar_close 保证）
- 止损：第三极值止损（第三段 pivot price）
- 共振门槛：Vegas 同向强门槛 + min_confirmations=2
  - confirmations：ENGULFING / RSI_DIV / OBV_DIV / FVG_PROXIMITY

## 环境变量（继承 .env）
- AUTO_TIMEFRAMES=1h,4h,1d
- MONITOR_TIMEFRAMES=15m,30m,8h
- MIN_CONFIRMATIONS=2
