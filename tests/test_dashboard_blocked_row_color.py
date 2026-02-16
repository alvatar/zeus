"""Tests for blocked-row visual color defaults."""

from zeus.dashboard.app import ZeusApp


def test_blocked_row_color_is_soft_gold() -> None:
    assert ZeusApp._BLOCKED_ROW_FG == "#f2e6a7"
