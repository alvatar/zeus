"""Tests for ConsolidationScreen."""

from __future__ import annotations

import pytest

from zeus.dashboard.screens import ConsolidationScreen


def test_screen_init_defaults() -> None:
    """ConsolidationScreen initialises with default empty lists."""
    s = ConsolidationScreen()
    assert s._available_model_specs == []
    assert s._topics == []


def test_screen_init_with_args() -> None:
    """ConsolidationScreen preserves constructor args."""
    s = ConsolidationScreen(
        available_model_specs=["anthropic/claude-sonnet-4-20250514"],
        topics=["zk-proofs", "rust-async"],
    )
    assert s._available_model_specs == ["anthropic/claude-sonnet-4-20250514"]
    assert s._topics == ["zk-proofs", "rust-async"]


def test_consolidation_css_defined() -> None:
    from zeus.dashboard.css import CONSOLIDATION_CSS
    assert "consolidation-dialog" in CONSOLIDATION_CSS
    assert "consolidation-model" in CONSOLIDATION_CSS
    assert "consolidation-topic" in CONSOLIDATION_CSS


def test_help_binding_includes_consolidation() -> None:
    from zeus.dashboard.screens import _HELP_BINDINGS
    keys = [k for k, _ in _HELP_BINDINGS]
    assert "Ctrl+Alt+m" in keys


def test_app_has_consolidation_binding() -> None:
    from zeus.dashboard.app import ZeusApp
    binding_keys = [b.key for b in ZeusApp.BINDINGS]
    assert any("alt+ctrl+m" in k or "ctrl+alt+m" in k for k in binding_keys)
