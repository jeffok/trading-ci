# -*- coding: utf-8 -*-
"""统一配置模块（Phase 0）

目标：
- 所有服务共享同一套配置读取/校验逻辑，避免不一致。
- 缺失必填项时启动失败，并给出清晰错误。
- 敏感信息仅通过环境变量注入。
"""

from __future__ import annotations
import os
from pydantic import BaseModel, Field


class Settings(BaseModel):
    # 基础
    env: str = Field(default="dev", alias="ENV")
    timezone: str = Field(default="Asia/Dubai", alias="TIMEZONE")

    # 外部依赖
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    # Streams
    redis_stream_group: str = Field(default="bot-group", alias="REDIS_STREAM_GROUP")
    redis_stream_consumer: str = Field(default="bot-consumer-1", alias="REDIS_STREAM_CONSUMER")

    # Bybit（Phase 1/3 实现真实调用）
    bybit_api_key: str = Field(default="", alias="BYBIT_API_KEY")

    # Stage 7: Bybit Private WebSocket (WS+REST consistency)
    bybit_private_ws_enabled: bool = Field(default=False, alias="BYBIT_PRIVATE_WS_ENABLED")
    bybit_private_ws_url: str = Field(default="wss://stream.bybit.com/v5/private", alias="BYBIT_PRIVATE_WS_URL")
    bybit_private_ws_auth_path: str = Field(default="/realtime", alias="BYBIT_PRIVATE_WS_AUTH_PATH")
    bybit_private_ws_subscriptions: str = Field(default="order,execution,position,wallet", alias="BYBIT_PRIVATE_WS_SUBSCRIPTIONS")
    bybit_api_secret: str = Field(default="", alias="BYBIT_API_SECRET")
    bybit_base_url: str = Field(default="https://api.bybit.com", alias="BYBIT_BASE_URL")
    bybit_ws_public_url: str = Field(default="wss://stream.bybit.com/v5/public/linear", alias="BYBIT_WS_PUBLIC_URL")
    bybit_ws_private_url: str = Field(default="wss://stream.bybit.com/v5/private", alias="BYBIT_WS_PRIVATE_URL")

    # 策略/风控参数（默认值）
    risk_pct: float = Field(default=0.005, alias="RISK_PCT")
    # 兼容：早期配置使用 MAX_OPEN_POSITIONS_DEFAULT；需求文档使用 MAX_OPEN_POSITIONS
    max_open_positions_default: int = Field(default=3, alias="MAX_OPEN_POSITIONS_DEFAULT")
    max_open_positions: int = Field(default=3, alias="MAX_OPEN_POSITIONS")
    min_confirmations: int = Field(default=2, alias="MIN_CONFIRMATIONS")
    auto_timeframes: str = Field(default="1h,4h,1d", alias="AUTO_TIMEFRAMES")
    monitor_timeframes: str = Field(default="15m,30m,8h", alias="MONITOR_TIMEFRAMES")

    account_kill_switch_enabled: bool = Field(default=False, alias="ACCOUNT_KILL_SWITCH_ENABLED")
    daily_loss_limit_pct: float = Field(default=0.03, alias="DAILY_LOSS_LIMIT_PCT")

    # 可选增强开关（默认不改变策略）
    enable_signal_scoring: bool = Field(default=False, alias="ENABLE_SIGNAL_SCORING")
    enable_market_state_marking: bool = Field(default=False, alias="ENABLE_MARKET_STATE")
    enable_order_retry: bool = Field(default=True, alias="ENABLE_ORDER_RETRY")

    # Stage 8: trade_plan lifecycle ttl (in bars) and market state marker
    trade_plan_ttl_bars: int = Field(default=1, alias="TRADE_PLAN_TTL_BARS")
    market_state_enabled: bool = Field(default=False, alias="MARKET_STATE_ENABLED")
    market_high_vol_pct: float = Field(default=0.04, alias="MARKET_HIGH_VOL_PCT")
    market_state_emit_on_normal: bool = Field(default=False, alias="MARKET_STATE_EMIT_ON_NORMAL")

    # Stage 11: data quality checks (marketdata, non-trading)
    data_quality_enabled: bool = Field(default=True, alias="DATA_QUALITY_ENABLED")
    data_quality_lag_ms: int = Field(default=180000, alias="DATA_QUALITY_LAG_MS")
    data_quality_price_jump_pct: float = Field(default=0.08, alias="DATA_QUALITY_PRICE_JUMP_PCT")
    data_quality_volume_spike_multiple: float = Field(default=10.0, alias="DATA_QUALITY_VOLUME_SPIKE_MULTIPLE")
    data_quality_volume_window: int = Field(default=30, alias="DATA_QUALITY_VOLUME_WINDOW")
    data_quality_bar_duplicate_enabled: bool = Field(default=False, alias="DATA_QUALITY_BAR_DUPLICATE_ENABLED")

    # Stage 11: market state (ATR + NEWS_WINDOW)
    market_atr_period: int = Field(default=14, alias="MARKET_ATR_PERIOD")
    news_window_utc: str = Field(default="", alias="NEWS_WINDOW_UTC")

    # Stage 11: signal lifecycle (non-trading)
    signal_ttl_bars: int = Field(default=1, alias="SIGNAL_TTL_BARS")

    # Stage 11: account kill switch (block new entries)
    account_kill_switch_force_on: bool = Field(default=False, alias="ACCOUNT_KILL_SWITCH_FORCE_ON")
    kill_switch_flag_name: str = Field(default="KILL_SWITCH", alias="KILL_SWITCH_FLAG_NAME")
    kill_switch_window_ms: int = Field(default=300000, alias="KILL_SWITCH_WINDOW_MS")


    # Execution（运行模式）
    execution_mode: str = Field(default="LIVE", alias="EXECUTION_MODE")  # LIVE/PAPER/BACKTEST

    # Stage 9: Entry order abnormal handling (14.3)
    # Default keeps current behavior (Market entry); switching to Limit enables timeout/retry flow.
    execution_entry_order_type: str = Field(default="Market", alias="EXECUTION_ENTRY_ORDER_TYPE")  # Market/Limit
    execution_entry_timeout_ms: int = Field(default=15_000, alias="EXECUTION_ENTRY_TIMEOUT_MS")
    execution_entry_max_retries: int = Field(default=2, alias="EXECUTION_ENTRY_MAX_RETRIES")
    execution_entry_reprice_bps: int = Field(default=5, alias="EXECUTION_ENTRY_REPRICE_BPS")  # 5bps per retry
    execution_entry_fallback_market: bool = Field(default=True, alias="EXECUTION_ENTRY_FALLBACK_MARKET")
    execution_entry_partial_fill_timeout_ms: int = Field(default=20_000, alias="EXECUTION_ENTRY_PARTIAL_FILL_TIMEOUT_MS")
    # Stage 10: wallet WS+REST drift detection (observability only)
    wallet_compare_enabled: bool = Field(default=True, alias="WALLET_COMPARE_ENABLED")
    bybit_wallet_coin: str = Field(default="USDT", alias="BYBIT_WALLET_COIN")
    wallet_ws_max_age_ms: int = Field(default=90_000, alias="WALLET_WS_MAX_AGE_MS")
    wallet_drift_threshold_pct: float = Field(default=0.02, alias="WALLET_DRIFT_THRESHOLD_PCT")
    wallet_drift_window_ms: int = Field(default=300_000, alias="WALLET_DRIFT_WINDOW_MS")
    # Bybit REST（execution 使用）
    bybit_rest_base_url: str = Field(default="https://api.bybit.com", alias="BYBIT_REST_BASE_URL")
    bybit_recv_window: int = Field(default=5000, alias="BYBIT_RECV_WINDOW")
    bybit_account_type: str = Field(default="UNIFIED", alias="BYBIT_ACCOUNT_TYPE")
    bybit_category: str = Field(default="linear", alias="BYBIT_CATEGORY")
    bybit_position_idx: int = Field(default=0, alias="BYBIT_POSITION_IDX")
    
    # 仓位控制（实际价值）
    min_order_value_usdt: float = Field(default=10.0, alias="MIN_ORDER_VALUE_USDT")
    max_order_value_usdt: float = Field(default=10000.0, alias="MAX_ORDER_VALUE_USDT")
    
    # 合约倍数
    leverage: int = Field(default=1, alias="LEVERAGE")
    
    # 保证金模式（isolated=逐仓，cross=全仓）
    margin_mode: str = Field(default="isolated", alias="MARGIN_MODE")


    # Stage 4: Bybit REST rate limiting (single-instance)
    # Public endpoints (market/instruments/kline) are usually more tolerant but still should be limited.
    bybit_public_rps: float = Field(default=8.0, alias="BYBIT_PUBLIC_RPS")
    bybit_public_burst: float = Field(default=16.0, alias="BYBIT_PUBLIC_BURST")

    # Private endpoints are split into critical (order/create, cancel, trading-stop) vs query.
    bybit_private_critical_rps: float = Field(default=3.0, alias="BYBIT_PRIVATE_CRITICAL_RPS")
    bybit_private_critical_burst: float = Field(default=6.0, alias="BYBIT_PRIVATE_CRITICAL_BURST")
    bybit_private_query_rps: float = Field(default=2.0, alias="BYBIT_PRIVATE_QUERY_RPS")
    bybit_private_query_burst: float = Field(default=4.0, alias="BYBIT_PRIVATE_QUERY_BURST")

    # Stage 5: further split query endpoints into order-query vs account-query.
    # If not set, they fall back to BYBIT_PRIVATE_QUERY_* defaults.
    bybit_private_order_query_rps: float = Field(default=2.0, alias="BYBIT_PRIVATE_ORDER_QUERY_RPS")
    bybit_private_order_query_burst: float = Field(default=4.0, alias="BYBIT_PRIVATE_ORDER_QUERY_BURST")
    bybit_private_account_query_rps: float = Field(default=2.0, alias="BYBIT_PRIVATE_ACCOUNT_QUERY_RPS")
    bybit_private_account_query_burst: float = Field(default=4.0, alias="BYBIT_PRIVATE_ACCOUNT_QUERY_BURST")

    # Per-symbol buckets (protects from N symbols multiplying query load)
    bybit_private_per_symbol_query_rps: float = Field(default=0.7, alias="BYBIT_PRIVATE_PER_SYMBOL_QUERY_RPS")
    bybit_private_per_symbol_query_burst: float = Field(default=1.5, alias="BYBIT_PRIVATE_PER_SYMBOL_QUERY_BURST")
    # Stage 5: per-symbol query buckets split (order vs account)
    bybit_private_per_symbol_order_query_rps: float = Field(default=0.6, alias="BYBIT_PRIVATE_PER_SYMBOL_ORDER_QUERY_RPS")
    bybit_private_per_symbol_order_query_burst: float = Field(default=1.2, alias="BYBIT_PRIVATE_PER_SYMBOL_ORDER_QUERY_BURST")
    bybit_private_per_symbol_account_query_rps: float = Field(default=0.6, alias="BYBIT_PRIVATE_PER_SYMBOL_ACCOUNT_QUERY_RPS")
    bybit_private_per_symbol_account_query_burst: float = Field(default=1.2, alias="BYBIT_PRIVATE_PER_SYMBOL_ACCOUNT_QUERY_BURST")
    bybit_private_per_symbol_critical_rps: float = Field(default=1.0, alias="BYBIT_PRIVATE_PER_SYMBOL_CRITICAL_RPS")
    bybit_private_per_symbol_critical_burst: float = Field(default=2.0, alias="BYBIT_PRIVATE_PER_SYMBOL_CRITICAL_BURST")

    # Degrade non-critical queries if limiter predicts a long wait
    bybit_rate_limit_max_wait_ms: int = Field(default=5000, alias="BYBIT_RATE_LIMIT_MAX_WAIT_MS")
    bybit_rate_limit_low_status_threshold: int = Field(default=2, alias="BYBIT_RATE_LIMIT_LOW_STATUS_THRESHOLD")

    # Stage 5: hard skip private polling for symbols not considered active (reduces private pressure)
    bybit_private_active_symbols_only: bool = Field(default=True, alias="BYBIT_PRIVATE_ACTIVE_SYMBOLS_ONLY")

    # Stage 4: in-client TTL caches for private query endpoints (reduces private pressure)
    bybit_wallet_balance_cache_ttl_sec: float = Field(default=1.0, alias="BYBIT_WALLET_BALANCE_CACHE_TTL_SEC")
    bybit_position_cache_ttl_sec: float = Field(default=1.0, alias="BYBIT_POSITION_CACHE_TTL_SEC")
    bybit_order_realtime_cache_ttl_sec: float = Field(default=0.5, alias="BYBIT_ORDER_REALTIME_CACHE_TTL_SEC")
    bybit_open_orders_cache_ttl_sec: float = Field(default=0.5, alias="BYBIT_OPEN_ORDERS_CACHE_TTL_SEC")

    # Telegram
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # Admin（API 管理口令）
    admin_token: str = Field(default="", alias="ADMIN_TOKEN")

    # 执行轮询参数
    order_poll_interval_sec: float = Field(default=1.0, alias="ORDER_POLL_INTERVAL_SEC")
    order_poll_timeout_sec: float = Field(default=20.0, alias="ORDER_POLL_TIMEOUT_SEC")
    # Stage 8: de-duplicate ORDER_TIMEOUT / ORDER_PARTIAL_FILL alerts
    order_timeout_alert_window_ms: int = Field(default=60000, alias="ORDER_TIMEOUT_ALERT_WINDOW_MS")

    # 冷却（按 1h/4h/1d 的 bar 数）
    cooldown_enabled: bool = Field(default=True, alias="COOLDOWN_ENABLED")
    cooldown_bars_1h: int = Field(default=2, alias="COOLDOWN_BARS_1H")
    cooldown_bars_4h: int = Field(default=1, alias="COOLDOWN_BARS_4H")
    cooldown_bars_1d: int = Field(default=1, alias="COOLDOWN_BARS_1D")

    # 同币种同向互斥：当高优先级周期信号到来时的处理策略
    # - BLOCK：直接拒绝（最保守）
    # - CLOSE_LOWER_AND_OPEN：先强制平掉低优先级仓位，再执行新开仓
    position_mutex_upgrade_action: str = Field(default="CLOSE_LOWER_AND_OPEN", alias="POSITION_MUTEX_UPGRADE_ACTION")

    # 账户级熔断（execution 风控）
    risk_circuit_enabled: bool = Field(default=False, alias="RISK_CIRCUIT_ENABLED")
    daily_drawdown_soft_pct: float = Field(default=0.02, alias="DAILY_DRAWDOWN_SOFT_PCT")
    daily_drawdown_hard_pct: float = Field(default=0.04, alias="DAILY_DRAWDOWN_HARD_PCT")
    risk_monitor_interval_sec: float = Field(default=10.0, alias="RISK_MONITOR_INTERVAL_SEC")

    # Runner 跟随止损参数
    runner_trail_mode: str = Field(default="ATR", alias="RUNNER_TRAIL_MODE")  # ATR/PIVOT
    runner_atr_period: int = Field(default=14, alias="RUNNER_ATR_PERIOD")
    runner_atr_mult: float = Field(default=3.0, alias="RUNNER_ATR_MULT")


    # Stage 6.1: Secondary rule & runner live update controls (execution-side only, does not change strategy)
    secondary_rule_enabled: bool = Field(default=True, alias="SECONDARY_RULE_ENABLED")

    # Stage 6.1: In live mode, continuously apply Runner trailing stop updates after TP2 is filled.
    runner_live_update_enabled: bool = Field(default=True, alias="RUNNER_LIVE_UPDATE_ENABLED")
    runner_live_update_min_interval_ms: int = Field(default=3000, alias="RUNNER_LIVE_UPDATE_MIN_INTERVAL_MS")

    # Stage 7.1: Reduce private REST polling when private WS is enabled.
    reconcile_open_orders_poll_interval_sec: float = Field(default=5.0, alias="RECONCILE_OPEN_ORDERS_POLL_INTERVAL_SEC")

    # Stage 7.1: WS/DB consistency drift detection
    consistency_drift_enabled: bool = Field(default=True, alias="CONSISTENCY_DRIFT_ENABLED")
    consistency_drift_threshold_pct: float = Field(default=0.10, alias="CONSISTENCY_DRIFT_THRESHOLD_PCT")
    consistency_drift_window_ms: int = Field(default=300000, alias="CONSISTENCY_DRIFT_WINDOW_MS")

    # Notifier retries（Stage 3）
    notifier_max_attempts: int = Field(default=5, alias="NOTIFIER_MAX_ATTEMPTS")
    notifier_retry_loop_interval_sec: float = Field(default=5.0, alias="NOTIFIER_RETRY_LOOP_INTERVAL_SEC")

    # Stage 4：资金/仓位快照
    account_snapshot_interval_sec: float = Field(default=30.0, alias="ACCOUNT_SNAPSHOT_INTERVAL_SEC")

    # Stage 4：关键路径指标与告警阈值（不改变策略/执行，只做告警）
    alert_stream_lag_enabled: bool = Field(default=True, alias="ALERT_STREAM_LAG_ENABLED")
    alert_trade_plan_lag_ms: int = Field(default=60000, alias="ALERT_TRADE_PLAN_LAG_MS")
    alert_bar_close_lag_ms: int = Field(default=120000, alias="ALERT_BAR_CLOSE_LAG_MS")


    @staticmethod
    def load() -> "Settings":
        return Settings.model_validate(os.environ)


settings = Settings.load()
