from __future__ import annotations

import pytest

from breakout_scanner.config import Settings
from breakout_scanner.models import Direction, SymbolRules
from breakout_scanner.risk import create_risk_plan, round_to_step, take_profits


def test_dynamic_position_respects_loss_and_exchange_steps() -> None:
    cfg = Settings(dynamic_sizing=True, fee_rate=0, slippage_rate=0)
    plan = create_risk_plan(100.0, 99.0, SymbolRules(0.1, 0.01, 5), cfg)
    assert plan.quantity == 4.0
    assert plan.estimated_loss == pytest.approx(4.0)
    assert plan.notional <= cfg.margin_usdt * cfg.leverage


def test_leverage_margin_risk_formula() -> None:
    cfg = Settings(dynamic_sizing=False, fee_rate=0, slippage_rate=0)
    plan = create_risk_plan(100.0, 99.2, SymbolRules(0.1, 0.01, 5), cfg)
    assert plan.notional == pytest.approx(500.0)
    assert plan.margin_risk_percent == pytest.approx(4.0)


def test_rounding_and_take_profit_direction() -> None:
    assert round_to_step(1.234, 0.01) == 1.23
    long = take_profits(Direction.LONG, 100, 98, 104)
    short = take_profits(Direction.SHORT, 100, 102, 96)
    assert long == (102, 104, 104, 2)
    assert short == (98, 96, 96, 2)


def test_invalid_stop_is_rejected() -> None:
    with pytest.raises(ValueError):
        create_risk_plan(100, 100, SymbolRules(0.1, 0.01, 5), Settings())

