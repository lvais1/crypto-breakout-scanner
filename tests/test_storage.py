from pathlib import Path

from breakout_scanner.models import Decision, SignalStatus
from breakout_scanner.storage import Storage


def test_rejected_decisions_are_saved(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test.db")
    storage.initialize()
    assert storage.save("BTCUSDT", Decision(SignalStatus.NO_SIGNAL, reasons=["bad_data"]))

