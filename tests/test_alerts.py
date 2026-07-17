from breakout_scanner.alerts import format_active_trades, format_near_signals, is_near_command, is_start_command, is_status_command, is_stop_command


def test_start_command_recognizes_private_bot_variants() -> None:
    assert is_start_command("/start")
    assert is_start_command(" /START ")
    assert is_start_command("/start@LiorAlerts_bot payload")


def test_start_command_rejects_other_input() -> None:
    assert not is_start_command("start")
    assert not is_start_command("/status")
    assert not is_start_command(None)


def test_stop_command_recognizes_bot_variants() -> None:
    assert is_stop_command("/stop")
    assert is_stop_command("/stop@LiorAlerts_bot")
    assert not is_stop_command("stop")


def test_status_command_and_empty_status_message() -> None:
    assert is_status_command("/status")
    assert is_status_command("/status@LiorAlerts_bot")
    assert "אין עסקאות Paper פעילות" in format_active_trades([])


def test_near_command_and_candidate_message() -> None:
    assert is_near_command("/near")
    message = format_near_signals([{"symbol": "BTCUSDT", "direction": "LONG", "proximity": 75, "stage": "RETEST", "touched": True, "held": True, "rejected": False, "created_at": "now"}])
    assert "BTCUSDT" in message and "נר דחייה" in message
