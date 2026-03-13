"""Linux driver hooks for Zeus dashboard input behavior."""

from __future__ import annotations

import os

from textual.drivers.linux_driver import LinuxDriver

_KITTY_KEYBOARD_PROTOCOL_ENABLE = "\x1b[>1u"
_KITTY_KEYBOARD_PROTOCOL_DISABLE = "\x1b[<u"
_KITTY_KEYBOARD_DISAMBIGUATE_ENABLE = "\x1b[=1;1u"
_ENV_TRUE = {"1", "true", "yes", "on"}


def kitty_keyboard_protocol_enabled() -> bool:
    """Return whether Zeus should use kitty's enhanced keyboard protocol."""
    raw = (os.environ.get("ZEUS_DISABLE_KITTY_KEYBOARD_PROTOCOL") or "").strip().lower()
    return raw not in _ENV_TRUE


def _remap_keyboard_protocol_write(data: str) -> str:
    """Adjust keyboard protocol setup for Zeus input handling."""
    if data != _KITTY_KEYBOARD_PROTOCOL_ENABLE:
        return data
    if not kitty_keyboard_protocol_enabled():
        return _KITTY_KEYBOARD_PROTOCOL_DISABLE
    return _KITTY_KEYBOARD_PROTOCOL_ENABLE + _KITTY_KEYBOARD_DISAMBIGUATE_ENABLE


class ZeusLinuxDriver(LinuxDriver):
    """Linux driver with Zeus-specific keyboard protocol behavior."""

    def write(self, data: str) -> None:
        super().write(_remap_keyboard_protocol_write(data))
