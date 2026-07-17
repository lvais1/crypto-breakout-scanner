from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

import pytest

from breakout_scanner.config import Settings
from breakout_scanner.models import Direction, ScoreBreakdown, Signal, Zone
from breakout_scanner.paper import PaperTradeEngine
from breakout_scanner.storage import Storage


def signal(direction: Direction = Direction.LONG, *, expires: datetime | None = None) -> Signal:
    now = datetime.now(UTC)
    long = direction == Direction.LONG
    return Signal(
        "signal-1", "BTCUSDT", "5m", direction, 100.0, 90.0 if long else 110.0,
        110.0 if long else 90.0, 120.0 if long else 80.0, 130.0 if long else 70.0,
        5, 200.0, 1000.0, 10.0, 10.0, 50.0, 100.0, 3.0, 90,
        ScoreBreakdown(), Zone(99, 101, 100, 3, [1, 2, 3], 20, 2, 1, "resistance"),
        now, now, now, expires or now + timedelta(minutes=10),
    )


def engine(tmp_path: Path, **overrides: object) -> PaperTradeEngine:
    path = tmp_path / "paper.db"
    Storage(path).initialize()
    return PaperTradeEngine(path, Settings(**overrides))


@pytest.mark.parametrize(
    ("direction", "prices"),
    [(Direction.LONG, [110, 120, 130]), (Direction.SHORT, [90, 80, 70])],
)
def test_three_targets_close_position(direction: Direction, prices: list[float], tmp_path: Path) -> None:
    e = engine(tmp_path)
    s = signal(direction)
    assert e.create_trade(s, 0.1, 100)
    now = datetime.now(UTC)
    events = []
    for index, price in enumerate(prices, 1):
        events += e.process_price("BTCUSDT", price, now + timedelta(seconds=index))
    assert [x.target_number for x in events] == [1, 2, 3]
    assert [x.closed_quantity for x in events] == [4.0, 4.0, 2.0]
    assert events[-1].remaining_quantity == 0
    assert events[-1].close_reason == "TP3"


def test_stop_before_target(tmp_path: Path) -> None:
    e = engine(tmp_path)
    e.create_trade(signal(), 0.1, 100)
    events = e.process_price("BTCUSDT", 89, datetime.now(UTC) + timedelta(seconds=1))
    assert len(events) == 1 and events[0].event_type == "STOP"
    assert events[0].closed_quantity == 10
    assert events[0].cumulative_net_pnl < -100


def test_tp1_then_cost_inclusive_break_even_stop(tmp_path: Path) -> None:
    e = engine(tmp_path)
    e.create_trade(signal(), 0.1, 100)
    now = datetime.now(UTC)
    tp1 = e.process_price("BTCUSDT", 110, now + timedelta(seconds=1))[0]
    assert tp1.current_stop > 100
    stop = e.process_price("BTCUSDT", tp1.current_stop, now + timedelta(seconds=2))[0]
    assert stop.event_type == "STOP"
    assert stop.targets_hit == ["TP1"]
    assert stop.cumulative_net_pnl > 0


def test_tp1_tp2_then_stop_at_tp1(tmp_path: Path) -> None:
    e = engine(tmp_path)
    e.create_trade(signal(), 0.1, 100)
    now = datetime.now(UTC)
    e.process_price("BTCUSDT", 110, now + timedelta(seconds=1))
    tp2 = e.process_price("BTCUSDT", 120, now + timedelta(seconds=2))[0]
    assert tp2.current_stop == 110
    stop = e.process_price("BTCUSDT", 110, now + timedelta(seconds=3))[0]
    assert stop.targets_hit == ["TP1", "TP2"]
    assert stop.cumulative_net_pnl > 0


def test_price_jump_records_all_targets_once(tmp_path: Path) -> None:
    e = engine(tmp_path)
    e.create_trade(signal(), 0.1, 100)
    at = datetime.now(UTC) + timedelta(seconds=1)
    events = e.process_price("BTCUSDT", 135, at)
    assert [x.target_number for x in events] == [1, 2, 3]
    assert e.process_price("BTCUSDT", 135, at) == []


def test_unknown_candle_order_is_conservative_stop_first(tmp_path: Path) -> None:
    e = engine(tmp_path)
    e.create_trade(signal(), 0.1, 100)
    events = e.process_candle("BTCUSDT", high=115, low=85, event_time=datetime.now(UTC) + timedelta(seconds=1))
    assert len(events) == 1 and events[0].event_type == "STOP"


def test_waiting_signal_expires_without_entry(tmp_path: Path) -> None:
    expires = datetime.now(UTC) + timedelta(seconds=1)
    e = engine(tmp_path)
    e.create_trade(signal(expires=expires), 0.1, 105, immediate=False)
    event = e.process_price("BTCUSDT", 105, expires + timedelta(seconds=1))[0]
    assert event.event_type == "EXPIRED"
    assert event.closed_quantity == 0


def test_partial_quantity_rounds_down_and_final_target_closes_remainder(tmp_path: Path) -> None:
    e = engine(tmp_path)
    s = signal(); s.quantity = 1.1
    e.create_trade(s, 0.3, 100)
    events = e.process_price("BTCUSDT", 135, datetime.now(UTC) + timedelta(seconds=1))
    assert [x.closed_quantity for x in events] == [0.3, 0.3, pytest.approx(0.5)]


def test_invalid_exit_fraction_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        Settings(tp1_close_fraction=0.5, tp2_close_fraction=0.5, tp3_close_fraction=0.5)


def test_restart_restores_partial_trade_without_duplicate_events(tmp_path: Path) -> None:
    e = engine(tmp_path)
    e.create_trade(signal(), 0.1, 100)
    at = datetime.now(UTC) + timedelta(seconds=1)
    first = e.process_price("BTCUSDT", 110, at)[0]
    restored = PaperTradeEngine(e.path, Settings())
    assert restored.active_symbols() == ["BTCUSDT"]
    assert restored.process_price("BTCUSDT", 110, at) == []
    second = restored.process_price("BTCUSDT", 120, at + timedelta(seconds=1))[0]
    assert first.target_number == 1 and second.target_number == 2
    with sqlite3.connect(e.path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_trade_events WHERE event_type='TP'").fetchone()[0] == 2


def test_unrealized_pnl_and_telegram_delivery_timestamp_are_stored(tmp_path: Path) -> None:
    e = engine(tmp_path)
    e.create_trade(signal(), 0.1, 100)
    e.process_price("BTCUSDT", 105, datetime.now(UTC) + timedelta(seconds=1))
    with sqlite3.connect(e.path) as db:
        assert db.execute("SELECT unrealized_pnl FROM paper_trades").fetchone()[0] == pytest.approx(50)
    event = e.process_price("BTCUSDT", 110, datetime.now(UTC) + timedelta(seconds=2))[0]
    e.mark_event_sent(event)
    with sqlite3.connect(e.path) as db:
        assert db.execute("SELECT telegram_sent_at FROM paper_trade_events WHERE event_type='TP'").fetchone()[0]
