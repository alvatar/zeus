"""Tests for dashboard cell formatting helpers."""

from zeus.dashboard.app import _compact_model_label, _format_ram_mb


def test_format_ram_mb_keeps_megabytes_below_threshold() -> None:
    assert _format_ram_mb(999.9) == "999M"


def test_format_ram_mb_switches_to_gigabytes_at_threshold() -> None:
    assert _format_ram_mb(1000.0) == "1G"


def test_format_ram_mb_keeps_single_decimal_for_small_gigabytes() -> None:
    assert _format_ram_mb(1500.0) == "1.5G"


def test_format_ram_mb_drops_decimal_for_double_digit_gigabytes() -> None:
    assert _format_ram_mb(12345.0) == "12G"


def test_compact_model_label_keeps_family_version_and_thinking() -> None:
    assert _compact_model_label("anthropic/claude-opus-4-5 (xhigh)", 15) == "op4.5 (xh)"


def test_compact_model_label_compacts_gpt_variant_to_family_version_only() -> None:
    assert _compact_model_label("gpt-5-3-codex", 15) == "gpt5.3"


def test_compact_model_label_keeps_thinking_suffix_when_it_fits() -> None:
    assert _compact_model_label("openai/gpt-5 (high)", 15) == "gpt5 (h)"


def test_compact_model_label_falls_back_to_family_for_unknown_models() -> None:
    compact = _compact_model_label("this-is-a-very-long-model-name", 11)
    assert compact == "this"
    assert len(compact) <= 11
