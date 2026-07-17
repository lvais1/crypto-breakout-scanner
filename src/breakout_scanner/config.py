from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    rest_base_url: str = "https://api.bybit.com"
    ws_base_url: str = "wss://stream.bybit.com/v5/public/linear"
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    timeframe: str = "1h"
    history_limit: int = Field(default=500, ge=210, le=1500)
    database_path: Path = Path("scanner.db")
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    log_level: str = "INFO"
    debug_decisions: bool = False

    swing_width: int = Field(default=3, ge=2, le=10)
    level_lookback_min: int = 20
    level_lookback_max: int = 150
    min_touches: int = 2
    min_touch_separation: int = 3
    zone_price_fraction: float = 0.0015
    zone_atr_multiple: float = 0.25
    breakout_price_fraction: float = 0.0015
    breakout_atr_multiple: float = 0.20
    breakout_body_atr: float = 0.50
    breakout_body_range_fraction: float = 0.55
    breakout_volume_multiple: float = 1.20
    retest_price_fraction: float = 0.0010
    retest_atr_multiple: float = 0.20
    retest_min_candles: int = 1
    retest_max_candles: int = 8
    stop_atr_buffer: float = 0.15
    max_preentry_r: float = 2.0
    max_entry_drift_r: float = 0.25
    max_atr_ratio: float = 2.5
    cooldown_candles: int = 6
    signal_expiry_candles: int = 2
    min_confidence: int = 75
    min_rr: float = 1.5

    margin_usdt: float = 100.0
    leverage: int = 5
    max_loss_usdt: float = 4.0
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0002
    dynamic_sizing: bool = True
    account_balance: float = 1000.0
    risk_per_trade_percent: float = 0.004

    request_timeout_seconds: float = 15.0
    reconnect_max_seconds: float = 60.0

    tp1_close_fraction: float = Field(default=0.40, ge=0, le=1)
    tp2_close_fraction: float = Field(default=0.40, ge=0, le=1)
    tp3_close_fraction: float = Field(default=0.20, ge=0, le=1)
    move_stop_to_break_even_after_tp1: bool = True
    stop_after_tp2: str = "TP1"
    mark_price_stale_seconds: int = Field(default=30, ge=5, le=300)
    paper_monitoring_enabled: bool = True
    paper_status_updates_enabled: bool = False

    @model_validator(mode="after")
    def validate_paper_exit_configuration(self) -> "Settings":
        total = self.tp1_close_fraction + self.tp2_close_fraction + self.tp3_close_fraction
        if abs(total - 1.0) > 1e-9:
            raise ValueError("TP close fractions must sum to 1.0")
        if self.stop_after_tp2 not in {"TP1", "NONE"}:
            raise ValueError("stop_after_tp2 must be TP1 or NONE")
        return self

    @field_validator("rest_base_url")
    @classmethod
    def fixed_rest_host(cls, value: str) -> str:
        allowed = {"https://api.bybit.com", "https://api.bytick.com"}
        if value.rstrip("/") not in allowed:
            raise ValueError("REST host is allowlisted to Bybit V5")
        return value.rstrip("/")

    @field_validator("ws_base_url")
    @classmethod
    def fixed_ws_host(cls, value: str) -> str:
        if value.rstrip("/") != "wss://stream.bybit.com/v5/public/linear":
            raise ValueError("WebSocket host is allowlisted to Bybit linear markets")
        return value.rstrip("/")

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, values: list[str]) -> list[str]:
        cleaned = [value.upper() for value in values]
        if not cleaned or any(not s.isalnum() or not s.endswith("USDT") for s in cleaned):
            raise ValueError("symbols must be non-empty Bybit USDT symbols")
        return cleaned
