"""Tests for interact stream parsing helpers."""

from rich.text import Text

from zeus.dashboard.app import _iter_url_ranges, _linkify_rich_text
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


def test_iter_url_ranges_detects_http_and_www():
    text = "Links: https://example.com/x and www.test.dev/path"
    ranges = _iter_url_ranges(text)
    assert ranges == [
        (7, 28, "https://example.com/x"),
        (33, 50, "https://www.test.dev/path"),
    ]


def test_iter_url_ranges_trims_trailing_punctuation():
    text = "Go: https://example.com/foo), now"
    ranges = _iter_url_ranges(text)
    assert ranges == [
        (4, 27, "https://example.com/foo"),
    ]


def test_linkify_rich_text_adds_clickable_link_style_spans():
    t = Text("Open https://example.com.")
    out = _linkify_rich_text(t)
    assert any(
        getattr(span.style, "meta", {}).get("@click")
        == "app.open_url('https://example.com')"
        for span in out.spans
    )
    assert any(
        "link https://example.com" in str(span.style)
        for span in out.spans
    )
