"""Tests for process metrics helpers."""

from zeus.process import fmt_bytes


def test_fmt_bytes_small():
    assert fmt_bytes(0) == "0B"
    assert fmt_bytes(500) == "500B"
    assert fmt_bytes(1023) == "1023B"


def test_fmt_bytes_kb():
    assert fmt_bytes(1024) == "1K"
    assert fmt_bytes(2048) == "2K"
    assert fmt_bytes(50000) == "49K"


def test_fmt_bytes_mb():
    assert fmt_bytes(1048576) == "1.0M"
    assert fmt_bytes(5 * 1048576) == "5.0M"
    assert fmt_bytes(1_500_000) == "1.4M"
