"""Linux driver hooks for Zeus dashboard input behavior."""

from __future__ import annotations

import os

from textual.drivers.linux_driver import LinuxDriver

_KITTY_KEYBOARD_PROTOCOL_ENABLE = "\x1b[>1u"
_KITTY_KEYBOARD_PROTOCOL_DISABLE = "\x1b[<u"
_ENV_TRUE = {"1", "true", "yes", "on"}


def kitty_keyboard_protocol_enabled() -> bool:
    """Return whether Zeus should use kitty's enhanced keyboard protocol."""
    raw = (os.environ.get("ZEUS_DISABLE_KITTY_KEYBOARD_PROTOCOL") or "").strip().lower()
    return raw not in _ENV_TRUE


def _remap_keyboard_protocol_write(data: str) -> str:
    """Force legacy terminal key encoding when requested."""
    if not kitty_keyboard_protocol_enabled() and data == _KITTY_KEYBOARD_PROTOCOL_ENABLE:
        return _KITTY_KEYBOARD_PROTOCOL_DISABLE
    return data


class ZeusLinuxDriver(LinuxDriver):
    """Linux driver with optional legacy keyboard-mode fallback for Zeus."""

    def write(self, data: str) -> None:
        super().write(_remap_keyboard_protocol_write(data))
