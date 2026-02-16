"""Tests for configurable state color mapping in dashboard UI."""

from zeus.dashboard.app import ZeusApp
from zeus.settings import SETTINGS


def test_state_ui_color_uses_settings_palette() -> None:
    assert ZeusApp._state_ui_color("WORKING") == SETTINGS.state_colors.working
    assert ZeusApp._state_ui_color("WAITING") == SETTINGS.state_colors.waiting
    assert ZeusApp._state_ui_color("IDLE") == SETTINGS.state_colors.idle


def _scale(hex_color: str, factor: float) -> str:
    value = hex_color.lstrip("#")
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def test_minimap_priority_colors_are_derived_from_configured_state_color(monkeypatch) -> None:
    monkeypatch.setattr(SETTINGS.state_colors, "working", "#123456")

    colors = ZeusApp._state_minimap_priority_colors("WORKING")

    assert colors == (
        "#123456",
        _scale("#123456", 0.45),
        _scale("#123456", 0.25),
        _scale("#123456", 0.15),
    )
