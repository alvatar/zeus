"""Tests for blocked-row visual color defaults."""

from zeus.dashboard.app import ZeusApp


def test_blocked_state_color_is_soft_gold() -> None:
    assert ZeusApp._BLOCKED_ROW_FG == "#f2e6a7"


def test_blocked_non_state_color_is_gray() -> None:
    assert ZeusApp._BLOCKED_NON_STATE_FG == "#666666"
