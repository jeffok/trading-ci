# execution-service

## Phase 3/4 功能概览
输入：
- `stream:trade_plan`
- `stream:bar_close`（Phase 4，用于 runner 跟随止损与次日规则检查）

输出：
- `stream:execution_report`
- `stream:risk_event`

## 执行逻辑（不改变策略）
- 入场：Market（收盘确认后的计划）
- 止损：primary_sl_price（第三极值止损）
- 止盈：TP1=1R 40%，TP2=2R 40%，Runner=20% 跟随止损（ATR 或 Pivot）
- 次日规则：NEXT_BAR_NOT_SHORTEN_EXIT（Phase 4 做“检查 + 事件化”，退出动作可在下一步加上自动执行）

## 模式
- `EXECUTION_MODE=paper`：不发真实订单，便于联调
- `EXECUTION_MODE=live`：真实下单（需配置 BYBIT_API_KEY/SECRET）

## 关键环境变量
- `BYBIT_REST_BASE_URL`：主网 https://api.bybit.com / 测试网 https://api-testnet.bybit.com
- `BYBIT_CATEGORY=linear`
- `BYBIT_ACCOUNT_TYPE=UNIFIED`
- `BYBIT_POSITION_IDX=0`
- `RUNNER_TRAIL_MODE=ATR|PIVOT`


## Phase 4 对账循环
- live 模式下，每 5 秒对账 TP1/TP2 成交状态，并按规则更新止损。
