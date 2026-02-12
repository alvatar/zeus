"""Tests for process metrics helpers."""

from zeus.process import _fmt_bytes


def test_fmt_bytes_small():
    assert _fmt_bytes(0) == "0B"
    assert _fmt_bytes(500) == "500B"
    assert _fmt_bytes(1023) == "1023B"


def test_fmt_bytes_kb():
    assert _fmt_bytes(1024) == "1K"
    assert _fmt_bytes(2048) == "2K"
    assert _fmt_bytes(50000) == "49K"


def test_fmt_bytes_mb():
    assert _fmt_bytes(1048576) == "1.0M"
    assert _fmt_bytes(5 * 1048576) == "5.0M"
    assert _fmt_bytes(1_500_000) == "1.4M"
