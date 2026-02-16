"""Tests for configurable state color mapping in dashboard UI."""

from zeus.dashboard.app import ZeusApp
from zeus.settings import SETTINGS


def test_state_ui_color_uses_settings_palette() -> None:
    assert ZeusApp._state_ui_color("WORKING") == SETTINGS.state_colors.working
    assert ZeusApp._state_ui_color("WAITING") == SETTINGS.state_colors.waiting
    assert ZeusApp._state_ui_color("IDLE") == SETTINGS.state_colors.idle
