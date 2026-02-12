"""Tests for config regex patterns."""

from zeus.config import SPINNER_RE, MODEL_RE, CTX_RE, TOKENS_RE


def test_spinner_re_matches_pi_frames():
    assert SPINNER_RE.search("⠋ Thinking...")
    assert SPINNER_RE.search("⠹ Working on it")
    assert not SPINNER_RE.search("plain text no spinner")
    assert not SPINNER_RE.search("⠋ ")  # needs \S after space


def test_model_re():
    m = MODEL_RE.match("claude-3.5-sonnet (xhigh)")
    assert m
    assert m.group(1) == "claude-3.5-sonnet"
    assert m.group(2) == "xhigh"

    m2 = MODEL_RE.match("opus-4-6")
    assert m2
    assert m2.group(1) == "opus-4-6"
    assert m2.group(2) is None


def test_ctx_re():
    m = CTX_RE.search("opus-4-6 (xhigh) Ctx(200K):██████░░░░░░(50%)")
    assert m
    assert m.group(1) == "50"

    m2 = CTX_RE.search("Ctx(100K):████████████(100%)")
    assert m2
    assert m2.group(1) == "100"


def test_tokens_re():
    m = TOKENS_RE.search("↑12.5k ↓3.2M")
    assert m
    assert m.group(1) == "12.5k"
    assert m.group(2) == "3.2M"
