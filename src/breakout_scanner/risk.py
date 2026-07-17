from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from .config import Settings
from .models import Direction, SymbolRules


@dataclass(frozen=True)
class RiskPlan:
    entry: float
    stop: float
    quantity: float
    margin: float
    notional: float
    price_risk_percent: float
    margin_risk_percent: float
    estimated_loss: float
    fees_and_slippage: float


def round_to_step(value: float, step: float, rounding: str = ROUND_DOWN) -> float:
    if step <= 0:
        raise ValueError("step must be positive")
    units = (Decimal(str(value)) / Decimal(str(step))).quantize(Decimal("1"), rounding=rounding)
    return float(units * Decimal(str(step)))


def create_risk_plan(entry: float, stop: float, rules: SymbolRules, cfg: Settings) -> RiskPlan:
    if entry <= 0 or stop <= 0 or entry == stop:
        raise ValueError("entry and stop must be distinct positive prices")
    risk_per_unit = abs(entry - stop)
    allowed_risk = min(cfg.max_loss_usdt, cfg.account_balance * cfg.risk_per_trade_percent)
    max_notional = cfg.margin_usdt * cfg.leverage
    raw_quantity = allowed_risk / risk_per_unit if cfg.dynamic_sizing else max_notional / entry
    quantity = round_to_step(min(raw_quantity, max_notional / entry), rules.step_size)
    if quantity <= 0:
        raise ValueError("quantity rounds to zero")
    notional = quantity * entry
    if notional < rules.min_notional:
        raise ValueError("notional below exchange minimum")
    margin = notional / cfg.leverage
    gross_loss = quantity * risk_per_unit
    costs = notional * (cfg.fee_rate + cfg.slippage_rate) * 2
    total_loss = gross_loss + costs
    if total_loss > cfg.max_loss_usdt + max(rules.tick_size * quantity, 1e-8):
        adjusted = round_to_step(max(0.0, (cfg.max_loss_usdt - costs) / risk_per_unit), rules.step_size)
        if adjusted <= 0:
            raise ValueError("fees leave no risk budget")
        quantity, notional, margin = adjusted, adjusted * entry, adjusted * entry / cfg.leverage
        gross_loss = adjusted * risk_per_unit
        costs = notional * (cfg.fee_rate + cfg.slippage_rate) * 2
        total_loss = gross_loss + costs
    return RiskPlan(
        entry=round_to_step(entry, rules.tick_size, ROUND_HALF_UP),
        stop=round_to_step(stop, rules.tick_size, ROUND_HALF_UP), quantity=quantity,
        margin=margin, notional=notional, price_risk_percent=risk_per_unit / entry * 100,
        margin_risk_percent=total_loss / margin * 100, estimated_loss=total_loss,
        fees_and_slippage=costs,
    )


def take_profits(direction: Direction, entry: float, stop: float, structural_target: float) -> tuple[float, float, float, float]:
    risk = abs(entry - stop)
    sign = 1 if direction == Direction.LONG else -1
    tp1, tp2 = entry + sign * risk, entry + sign * 2 * risk
    structural_r = sign * (structural_target - entry) / risk
    return tp1, tp2, structural_target, structural_r

