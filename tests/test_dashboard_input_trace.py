"""Tests for dashboard input driver selection and keyboard protocol behavior."""

from __future__ import annotations

from textual.app import App
from textual.drivers.linux_driver import LinuxDriver

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.input_driver import (
    ZeusLinuxDriver,
    _remap_keyboard_protocol_write,
    kitty_keyboard_protocol_enabled,
)


def test_zeus_uses_linux_driver_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(App, "get_driver_class", lambda self: LinuxDriver)

    app = ZeusApp()

    assert app.driver_class is ZeusLinuxDriver


def test_kitty_keyboard_protocol_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ZEUS_DISABLE_KITTY_KEYBOARD_PROTOCOL", raising=False)

    assert kitty_keyboard_protocol_enabled() is True
    assert _remap_keyboard_protocol_write("\x1b[>1u") == "\x1b[>1u\x1b[=1;1u"
    assert _remap_keyboard_protocol_write("plain-text") == "plain-text"


def test_kitty_keyboard_protocol_can_be_forced_to_legacy(monkeypatch) -> None:
    monkeypatch.setenv("ZEUS_DISABLE_KITTY_KEYBOARD_PROTOCOL", "1")

    assert kitty_keyboard_protocol_enabled() is False
    assert _remap_keyboard_protocol_write("\x1b[>1u") == "\x1b[<u"
    assert _remap_keyboard_protocol_write("plain-text") == "plain-text"
