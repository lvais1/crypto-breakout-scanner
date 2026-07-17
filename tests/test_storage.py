from pathlib import Path

from breakout_scanner.models import Decision, SignalStatus
from breakout_scanner.storage import Storage


def test_rejected_decisions_are_saved(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")
    storage.initialize()
    assert storage.save("BTCUSDT", Decision(SignalStatus.NO_SIGNAL, reasons=["bad_data"]))


def test_telegram_subscriptions_are_persistent_and_unique(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "subscribers.db")
    storage.initialize()
    storage.add_telegram_subscriber(123)
    storage.add_telegram_subscriber(123)
    storage.add_telegram_subscriber(456)
    assert storage.telegram_subscribers() == [123, 456]
    storage.remove_telegram_subscriber(123)
    assert storage.telegram_subscribers() == [456]
