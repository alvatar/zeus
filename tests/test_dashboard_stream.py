"""Tests for interact stream parsing helpers."""

from zeus.dashboard.stream import (
    kitty_ansi_to_standard,
    strip_pi_input_chrome,
    trim_trailing_blank_lines,
)


def test_kitty_ansi_to_standard_colon_sgr():
    raw = "\x1b[38:2:255:0:0mRED\x1b[0m"
    converted = kitty_ansi_to_standard(raw)
    assert "\x1b[38;2;255;0;0m" in converted


def test_trim_trailing_blank_lines():
    text = "line1\nline2\n\n\n"
    assert trim_trailing_blank_lines(text) == "line1\nline2\n"


def test_strip_pi_input_chrome_two_separators_from_bottom():
    sep = "─" * 40
    screen = (
        "top\n"
        "keep this\n"
        f"{sep}\n"
        "input area\n"
        f"{sep}\n"
        "status\n"
    )
    stripped = strip_pi_input_chrome(screen)
    assert stripped == "top\nkeep this\n"


def test_strip_pi_input_chrome_no_separator_keeps_content():
    screen = "a\nb\nc\n"
    assert strip_pi_input_chrome(screen) == screen


def test_strip_pi_input_chrome_ignores_short_separator_like_content():
    screen = "line\n───\nmore\n"
    assert strip_pi_input_chrome(screen) == screen
