from breakout_scanner.alerts import is_start_command, is_stop_command


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
