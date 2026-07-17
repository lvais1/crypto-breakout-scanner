from breakout_scanner.alerts import is_start_command


def test_start_command_recognizes_private_bot_variants() -> None:
    assert is_start_command("/start")
    assert is_start_command(" /START ")
    assert is_start_command("/start@LiorAlerts_bot payload")


def test_start_command_rejects_other_input() -> None:
    assert not is_start_command("start")
    assert not is_start_command("/status")
    assert not is_start_command(None)
