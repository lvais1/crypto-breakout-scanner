from __future__ import annotations

import pandas as pd

from breakout_scanner.config import Settings
from breakout_scanner.detector import _breakout, _rejection
from breakout_scanner.indicators import enrich, swing_points
from breakout_scanner.models import Direction, Zone


def row(**overrides: float) -> pd.Series:
    values = {"open": 100.0, "high": 103.0, "low": 99.8, "close": 102.8, "volume": 150.0, "atr14": 2.0, "volume_ma20": 100.0}
    values.update(overrides)
    return pd.Series(values)


def test_bullish_breakout_requires_close_body_location_and_volume() -> None:
    zone = Zone(99.5, 100.0, 99.75, 3, [1, 10, 20], 5, 1.0, 100, "resistance")
    valid, metrics = _breakout(row(), zone, Direction.LONG, Settings())
    assert valid
    assert metrics["volume_ratio"] == 1.5
    invalid, _ = _breakout(row(volume=110), zone, Direction.LONG, Settings())
    assert not invalid


def test_retest_rejection_wick_and_direction() -> None:
    previous = row(open=101, close=100, high=101.2, low=99.8)
    retest = row(open=100.2, close=101.0, high=101.2, low=98.0)
    valid, score = _rejection(retest, previous, Direction.LONG)
    assert valid
    assert score >= 8


def test_swing_confirmation_uses_bars_on_both_sides() -> None:
    frame = pd.DataFrame({"high": [1, 2, 3, 7, 3, 2, 1], "low": [1, 0, -1, -3, -1, 0, 1]})
    highs, lows = swing_points(frame, 3)
    assert highs.iloc[3]
    assert lows.iloc[3]
    assert not highs.iloc[-1]


def test_missing_market_data_fails_closed() -> None:
    frame = pd.DataFrame({"open": [1], "high": [2]})
    try:
        enrich(frame)
    except ValueError as exc:
        assert "missing market columns" in str(exc)
    else:
        raise AssertionError("missing columns were accepted")

