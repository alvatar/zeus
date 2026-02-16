"""Tests for sparkline rendering and compact name helpers."""

from zeus.dashboard.widgets import (
    _gradient_color,
    braille_sparkline,
    braille_sparkline_markup,
    state_sparkline_markup,
)
from zeus.dashboard.app import _compact_name
from zeus.settings import SETTINGS
from zeus.dashboard.widgets_visual import _usage_gradient_color


# ── _compact_name ─────────────────────────────────────────────────────


def test_compact_name_short_unchanged():
    assert _compact_name("fix", 10) == "fix"


def test_compact_name_exact_length():
    assert _compact_name("fix-auth", 8) == "fix-auth"


def test_compact_name_dash_aware_truncation():
    result = _compact_name("fix-auth-login", 10)
    assert "…" in result
    assert result.endswith("login")
    assert len(result) <= 10


def test_compact_name_long_first_segment():
    result = _compact_name("refactor-dashboard-styling", 12)
    assert "…" in result
    assert result.endswith("styling")
    assert len(result) <= 12


def test_compact_name_no_dashes():
    result = _compact_name("longagentname", 8)
    assert result == "longage…"
    assert len(result) <= 8


def test_compact_name_two_segments():
    result = _compact_name("implement-config", 10)
    assert "…" in result
    assert len(result) <= 10


def test_compact_name_two_long_segments_keeps_tail():
    result = _compact_name("barlovento-supervisor", 10)
    assert "…" in result
    assert result.endswith("visor")
    assert len(result) <= 10


def test_compact_name_many_segments():
    result = _compact_name("a-b-c-d-e", 5)
    assert result.startswith("a")
    assert result.endswith("e")
    assert len(result) <= 5


# ── _gradient_color ───────────────────────────────────────────────────


def test_gradient_color_uses_white_to_red_stops() -> None:
    assert _gradient_color(0) == "#ffffff"
    assert _gradient_color(50) == "#ffff00"
    assert _gradient_color(80) == "#ff9900"
    assert _gradient_color(100) == "#ff0000"


def test_gradient_color_drops_blue_then_green() -> None:
    low = _gradient_color(25)
    mid = _gradient_color(60)
    high = _gradient_color(90)

    assert low.startswith("#ffff")  # white -> yellow transition
    assert mid.endswith("00")       # blue gone by yellow/orange zone
    assert high.endswith("00")      # blue remains absent near red


def test_usage_gradient_keeps_original_cyan_to_red_ramp() -> None:
    assert _usage_gradient_color(0) == "#00d7d7"
    assert _usage_gradient_color(70) == "#d7d700"
    assert _usage_gradient_color(100) == "#ff3233"


# ── braille_sparkline ─────────────────────────────────────────────────


def test_braille_sparkline_returns_text():
    from rich.text import Text
    result = braille_sparkline([50.0, 50.0, 80.0, 80.0], width=2)
    assert isinstance(result, Text)
    assert len(result.plain) == 2


def test_braille_sparkline_empty_values():
    result = braille_sparkline([], width=3)
    # Should render blank braille (all zeros)
    assert len(result.plain) == 3
    assert all(ch == "\u2800" for ch in result.plain)


def test_braille_sparkline_full_values():
    result = braille_sparkline([100.0] * 10, width=5)
    assert len(result.plain) == 5
    # All chars should have dots set (not blank braille)
    assert all(ch != "\u2800" for ch in result.plain)


def test_braille_sparkline_markup_returns_str():
    result = braille_sparkline_markup([25.0, 75.0], width=1)
    assert isinstance(result, str)
    # Should contain Rich markup color tags
    assert "[" in result and "[/]" in result


def test_braille_sparkline_values_clipped():
    """Values outside 0-100 should be clamped, not crash."""
    result = braille_sparkline([-10.0, 150.0], width=1)
    assert len(result.plain) == 1


# ── state_sparkline_markup ────────────────────────────────────────────


def test_state_sparkline_working_green():
    result = state_sparkline_markup(["WORKING", "WORKING"], width=1)
    assert SETTINGS.state_colors.working in result


def test_state_sparkline_idle_red():
    result = state_sparkline_markup(["IDLE", "IDLE"], width=1)
    assert SETTINGS.state_colors.idle in result


def test_state_sparkline_waiting_uses_configured_color():
    result = state_sparkline_markup(["WAITING", "WAITING"], width=1)
    assert SETTINGS.state_colors.waiting in result


def test_state_sparkline_empty_states():
    result = state_sparkline_markup([], width=3)
    # All blank braille
    assert "\u2800" in result


def test_state_sparkline_mixed_pair_uses_urgent_color():
    """When a pair has WAITING + WORKING, WAITING color wins."""
    result = state_sparkline_markup(["WORKING", "WAITING"], width=1)
    assert SETTINGS.state_colors.waiting in result


def test_state_sparkline_stable_pairing():
    """Odd sample count should drop oldest to keep even pairing."""
    r1 = state_sparkline_markup(["WORKING", "IDLE", "WORKING"], width=2)
    r2 = state_sparkline_markup(["WORKING", "IDLE", "WORKING", "WORKING"], width=2)
    # Both should produce 2 braille chars without crashing
    assert "[/]" in r1
    assert "[/]" in r2


def test_state_sparkline_width_respected():
    states = ["WORKING"] * 20
    result = state_sparkline_markup(states, width=5)
    # Count braille characters (between markup tags)
    import re
    chars = re.findall(r"[\u2800-\u28ff]", result)
    assert len(chars) == 5
