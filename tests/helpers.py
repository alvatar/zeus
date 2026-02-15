"""Shared test helpers."""

from __future__ import annotations

from typing import Any


def capture_kitty_cmd(monkeypatch: Any) -> list[tuple[str, tuple[str, ...]]]:
    """Patch dashboard kitty_cmd and return collected calls."""
    sent: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.kitty_cmd",
        lambda socket, *args, timeout=3: sent.append((socket, args)) or "",
    )
    return sent


def capture_notify(app: Any, monkeypatch: Any) -> list[str]:
    """Patch app.notify and return collected messages."""
    notices: list[str] = []
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    return notices
