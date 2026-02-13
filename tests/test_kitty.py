"""Tests for kitty window detection heuristics."""

from zeus.kitty import _iter_cmdline_tokens, _looks_like_pi_window


def test_iter_cmdline_tokens_splits_shell_payload():
    cmdline = ["bash", "-lc", "pi --session abc"]
    assert _iter_cmdline_tokens(cmdline) == ["bash", "-lc", "pi", "--session", "abc"]


def test_looks_like_pi_window_exact_token():
    win = {"cmdline": ["pi", "--print"], "title": "shell"}
    assert _looks_like_pi_window(win) is True


def test_looks_like_pi_window_path_token():
    win = {"cmdline": ["/home/user/.local/bin/pi", "--print"], "title": "shell"}
    assert _looks_like_pi_window(win) is True


def test_looks_like_pi_window_shell_command_payload():
    win = {"cmdline": ["bash", "-lc", "exec pi --session x"], "title": "shell"}
    assert _looks_like_pi_window(win) is True


def test_looks_like_pi_window_does_not_match_pip():
    win = {"cmdline": ["python", "-m", "pip", "install", "textual"], "title": "shell"}
    assert _looks_like_pi_window(win) is False


def test_looks_like_pi_window_title_pi_symbol():
    win = {"cmdline": ["bash"], "title": "π my-agent"}
    assert _looks_like_pi_window(win) is True
