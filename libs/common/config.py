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
    bybit_api_secret: str = Field(default="", alias="BYBIT_API_SECRET")
    bybit_base_url: str = Field(default="https://api.bybit.com", alias="BYBIT_BASE_URL")
    bybit_ws_public_url: str = Field(default="wss://stream.bybit.com/v5/public/linear", alias="BYBIT_WS_PUBLIC_URL")
    bybit_ws_private_url: str = Field(default="wss://stream.bybit.com/v5/private", alias="BYBIT_WS_PRIVATE_URL")

    # 策略/风控参数（默认值）
    risk_pct: float = Field(default=0.005, alias="RISK_PCT")
    max_open_positions_default: int = Field(default=3, alias="MAX_OPEN_POSITIONS_DEFAULT")
    min_confirmations: int = Field(default=2, alias="MIN_CONFIRMATIONS")
    auto_timeframes: str = Field(default="1h,4h,1d", alias="AUTO_TIMEFRAMES")
    monitor_timeframes: str = Field(default="15m,30m,8h", alias="MONITOR_TIMEFRAMES")

    account_kill_switch_enabled: bool = Field(default=False, alias="ACCOUNT_KILL_SWITCH_ENABLED")
    daily_loss_limit_pct: float = Field(default=0.03, alias="DAILY_LOSS_LIMIT_PCT")

    # 可选增强开关（默认不改变策略）
    enable_signal_scoring: bool = Field(default=False, alias="ENABLE_SIGNAL_SCORING")
    enable_market_state_marking: bool = Field(default=False, alias="ENABLE_MARKET_STATE")
    enable_order_retry: bool = Field(default=True, alias="ENABLE_ORDER_RETRY")

    # Execution（运行模式）
    execution_mode: str = Field(default="LIVE", alias="EXECUTION_MODE")  # LIVE/PAPER/BACKTEST

    # Bybit REST（execution 使用）
    bybit_rest_base_url: str = Field(default="https://api.bybit.com", alias="BYBIT_REST_BASE_URL")
    bybit_recv_window: int = Field(default=5000, alias="BYBIT_RECV_WINDOW")
    bybit_account_type: str = Field(default="UNIFIED", alias="BYBIT_ACCOUNT_TYPE")
    bybit_category: str = Field(default="linear", alias="BYBIT_CATEGORY")
    bybit_position_idx: int = Field(default=0, alias="BYBIT_POSITION_IDX")

    # Telegram
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # Admin（API 管理口令）
    admin_token: str = Field(default="", alias="ADMIN_TOKEN")

    # 执行轮询参数
    order_poll_interval_sec: float = Field(default=1.0, alias="ORDER_POLL_INTERVAL_SEC")
    order_poll_timeout_sec: float = Field(default=20.0, alias="ORDER_POLL_TIMEOUT_SEC")

    # 冷却（按 1h/4h/1d 的 bar 数）
    cooldown_enabled: bool = Field(default=True, alias="COOLDOWN_ENABLED")
    cooldown_bars_1h: int = Field(default=2, alias="COOLDOWN_BARS_1H")
    cooldown_bars_4h: int = Field(default=1, alias="COOLDOWN_BARS_4H")
    cooldown_bars_1d: int = Field(default=1, alias="COOLDOWN_BARS_1D")

    # 账户级熔断（execution 风控）
    risk_circuit_enabled: bool = Field(default=False, alias="RISK_CIRCUIT_ENABLED")
    daily_drawdown_soft_pct: float = Field(default=0.02, alias="DAILY_DRAWDOWN_SOFT_PCT")
    daily_drawdown_hard_pct: float = Field(default=0.04, alias="DAILY_DRAWDOWN_HARD_PCT")
    risk_monitor_interval_sec: float = Field(default=10.0, alias="RISK_MONITOR_INTERVAL_SEC")

    # Runner 跟随止损参数
    runner_trail_mode: str = Field(default="ATR", alias="RUNNER_TRAIL_MODE")  # ATR/PIVOT
    runner_atr_period: int = Field(default=14, alias="RUNNER_ATR_PERIOD")
    runner_atr_mult: float = Field(default=3.0, alias="RUNNER_ATR_MULT")

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
