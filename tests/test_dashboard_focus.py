"""Tests for dashboard focus behavior."""

from zeus.dashboard.app import ZeusApp


def test_dashboard_does_not_force_focus_on_app_focus() -> None:
    """Returning to Zeus should not forcibly move focus to the agent table."""
    assert "on_app_focus" not in ZeusApp.__dict__
