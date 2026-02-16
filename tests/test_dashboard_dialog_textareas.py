"""Tests ensuring dialog textareas use ZeusTextArea behavior parity."""

import inspect
import re

from zeus.dashboard.screens import (
    AgentNotesScreen,
    ConfirmBroadcastScreen,
    ConfirmDirectMessageScreen,
)

_PLAIN_TEXTAREA_CALL_RE = re.compile(r"(?<!Zeus)TextArea\(")


def _compose_source(screen_class: type) -> str:
    return inspect.getsource(screen_class.compose)


def test_agent_notes_dialog_uses_zeus_textarea() -> None:
    source = _compose_source(AgentNotesScreen)
    assert "ZeusTextArea(" in source
    assert _PLAIN_TEXTAREA_CALL_RE.search(source) is None


def test_broadcast_dialog_uses_zeus_textarea() -> None:
    source = _compose_source(ConfirmBroadcastScreen)
    assert "ZeusTextArea(" in source
    assert _PLAIN_TEXTAREA_CALL_RE.search(source) is None


def test_direct_dialog_uses_zeus_textarea() -> None:
    source = _compose_source(ConfirmDirectMessageScreen)
    assert "ZeusTextArea(" in source
    assert _PLAIN_TEXTAREA_CALL_RE.search(source) is None
