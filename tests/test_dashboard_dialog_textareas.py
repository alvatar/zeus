"""Tests ensuring dialog textareas use ZeusTextArea behavior parity."""

import inspect
import re

from zeus.dashboard.screens import (
    AgentMessageScreen,
    AgentTasksScreen,
    ConfirmBroadcastScreen,
    ConfirmDirectMessageScreen,
    NewAgentScreen,
)

_PLAIN_TEXTAREA_CALL_RE = re.compile(r"(?<!Zeus)TextArea\(")


def _compose_source(screen_class: type) -> str:
    return inspect.getsource(screen_class.compose)


def test_agent_tasks_dialog_uses_zeus_textarea() -> None:
    source = _compose_source(AgentTasksScreen)
    assert "ZeusTextArea(" in source
    assert _PLAIN_TEXTAREA_CALL_RE.search(source) is None


def test_agent_tasks_dialog_includes_clear_done_button() -> None:
    source = _compose_source(AgentTasksScreen)
    assert "agent-tasks-clear-done-btn" in source
    assert "Clear done [x]" in source


def test_agent_tasks_dialog_header_uses_single_title_and_format_line() -> None:
    source = _compose_source(AgentTasksScreen)
    assert "Tasks:" in source
    assert "Format: '- [] task' or '- [ ] task'" in source
    assert "Press H" not in source


def test_agent_tasks_dialog_has_no_cancel_button() -> None:
    source = _compose_source(AgentTasksScreen)
    assert "agent-tasks-cancel-btn" not in source
    assert 'Button("Save"' in source


def test_broadcast_dialog_uses_zeus_textarea() -> None:
    source = _compose_source(ConfirmBroadcastScreen)
    assert "ZeusTextArea(" in source
    assert _PLAIN_TEXTAREA_CALL_RE.search(source) is None


def test_direct_dialog_uses_zeus_textarea() -> None:
    source = _compose_source(ConfirmDirectMessageScreen)
    assert "ZeusTextArea(" in source
    assert _PLAIN_TEXTAREA_CALL_RE.search(source) is None


def test_agent_message_dialog_uses_zeus_textarea_with_task_buttons() -> None:
    source = _compose_source(AgentMessageScreen)
    assert "ZeusTextArea(" in source
    assert _PLAIN_TEXTAREA_CALL_RE.search(source) is None
    assert "agent-message-add-task-btn" in source
    assert "agent-message-add-task-first-btn" in source
    assert "append as task" in source
    assert "prepend as task" in source
    assert source.index("agent-message-add-task-btn") < source.index(
        "agent-message-add-task-first-btn"
    )
    assert "agent-message-shortcuts-hint" in source
    assert "(Control-S send | Control-W queue)" in source
    assert "agent-message-title-row" in source


def test_new_agent_dialog_defaults_directory_to_home_code() -> None:
    source = _compose_source(NewAgentScreen)
    assert 'value="~/code"' in source
    assert "os.getcwd()" not in source
