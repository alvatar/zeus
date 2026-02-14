"""Tests for state detection and footer parsing."""

from zeus.models import State
from zeus.state import detect_state, activity_signature, parse_footer


def test_detect_working_spinner():
    screen = "Some output\n⠋ Thinking about the problem...\nmore text"
    assert detect_state(screen) == State.WORKING


def test_detect_working_footer_label():
    screen = "Some output\nWorking...\n"
    assert detect_state(screen) == State.WORKING


def test_detect_working_footer_label_with_spinner_glyph():
    screen = "Some output\n⠋ Working...\n"
    assert detect_state(screen) == State.WORKING


def test_detect_idle_when_working_word_is_plain_prose():
    screen = "Superproject working tree still has local changes\n"
    assert detect_state(screen) == State.IDLE


def test_detect_idle_when_spinner_is_embedded_in_prose():
    screen = "- positive: ⠋ Working... -> WORKING\n"
    assert detect_state(screen) == State.IDLE


def test_detect_idle_no_spinner():
    screen = "Some output\n> ready for input\n"
    assert detect_state(screen) == State.IDLE


def test_detect_idle_empty():
    assert detect_state("") == State.IDLE


def test_activity_signature_strips_footer_and_blanks():
    screen = (
        "line 1\n"
        "\n"
        "line 2\n"
        "opus-4-6 Ctx(200K):██░░░░░░░░░░(10%) ↑1k ↓2k\n"
    )
    assert activity_signature(screen) == "line 1\nline 2"


def test_activity_signature_keeps_recent_tail():
    lines = [f"line {i}" for i in range(120)]
    sig = activity_signature("\n".join(lines))
    kept = sig.splitlines()
    assert len(kept) == 80
    assert kept[0] == "line 40"
    assert kept[-1] == "line 119"


def test_parse_footer_full():
    screen = (
        "some output\n"
        "opus-4-6 (xhigh) Ctx(200K):██████░░░░░░(50%) ↑12.5k ↓3.2k\n"
    )
    model, ctx_pct, tok_in, tok_out = parse_footer(screen)
    assert "opus-4-6" in model
    assert "xhigh" in model
    assert ctx_pct == 50.0
    assert tok_in == "12.5k"
    assert tok_out == "3.2k"


def test_parse_footer_strips_date_suffix():
    screen = "claude-3.5-sonnet-20250101 (xhigh) Ctx(100K):████████████(75%) ↑1k ↓2k\n"
    model, ctx_pct, _, _ = parse_footer(screen)
    assert "20250101" not in model
    assert "3.5-sonnet" in model
    assert ctx_pct == 75.0


def test_parse_footer_empty():
    model, ctx_pct, tok_in, tok_out = parse_footer("")
    assert model == ""
    assert ctx_pct == 0.0
    assert tok_in == ""
    assert tok_out == ""


def test_parse_footer_no_tokens():
    screen = "opus-4-6 Ctx(200K):██░░░░░░░░░░(10%)\n"
    model, ctx_pct, tok_in, tok_out = parse_footer(screen)
    assert ctx_pct == 10.0
    assert tok_in == ""
    assert tok_out == ""
