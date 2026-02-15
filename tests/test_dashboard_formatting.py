"""Tests for dashboard cell formatting helpers."""

from zeus.dashboard.app import _format_ram_mb


def test_format_ram_mb_keeps_megabytes_below_threshold() -> None:
    assert _format_ram_mb(999.9) == "999M"


def test_format_ram_mb_switches_to_gigabytes_at_threshold() -> None:
    assert _format_ram_mb(1000.0) == "1G"


def test_format_ram_mb_keeps_single_decimal_for_small_gigabytes() -> None:
    assert _format_ram_mb(1500.0) == "1.5G"


def test_format_ram_mb_drops_decimal_for_double_digit_gigabytes() -> None:
    assert _format_ram_mb(12345.0) == "12G"
