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

    @staticmethod
    def load() -> "Settings":
        return Settings.model_validate(os.environ)


settings = Settings.load()
