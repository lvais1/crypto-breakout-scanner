from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalStatus(StrEnum):
    PAPER_SIGNAL = "PAPER_SIGNAL"
    NO_SIGNAL = "NO_SIGNAL"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class SymbolRules:
    tick_size: float
    step_size: float
    min_notional: float


@dataclass
class Zone:
    low: float
    high: float
    center: float
    touches: int
    indices: list[int]
    age: int
    reaction_strength: float
    touch_volume: float
    kind: str


@dataclass
class ScoreBreakdown:
    level_quality: int = 0
    breakout_quality: int = 0
    volume_confirmation: int = 0
    retest_quality: int = 0
    rejection_candle: int = 0
    trend_alignment: int = 0
    market_quality: int = 0

    @property
    def total(self) -> int:
        return sum(asdict(self).values())


@dataclass
class Signal:
    signal_id: str
    symbol: str
    timeframe: str
    direction: Direction
    entry_price: float
    stop_price: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    leverage: int
    margin_usdt: float
    notional_usdt: float
    quantity: float
    price_risk_percent: float
    margin_risk_percent: float
    estimated_loss_usdt: float
    risk_reward_ratio: float
    confidence_score: int
    score_breakdown: ScoreBreakdown
    breakout_zone: Zone
    breakout_candle_time: datetime
    retest_candle_time: datetime
    signal_created_at: datetime
    expires_at: datetime
    status: SignalStatus = SignalStatus.PAPER_SIGNAL
    rejection_reasons: list[str] = field(default_factory=list)
    pattern: str = "breakout_retest"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("direction", "status"):
            payload[key] = str(payload[key])
        for key in ("breakout_candle_time", "retest_candle_time", "signal_created_at", "expires_at"):
            payload[key] = payload[key].isoformat()
        return payload


@dataclass
class Decision:
    status: SignalStatus
    signal: Signal | None = None
    reasons: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

