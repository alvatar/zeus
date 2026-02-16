"""Tests ensuring dialog textareas use ZeusTextArea behavior parity."""

import inspect
import re

from zeus.dashboard.screens import (
    AgentMessageScreen,
    AgentTasksScreen,
    ConfirmBroadcastScreen,
    ConfirmDirectMessageScreen,
    NewAgentScreen,
    RenameScreen,
    RenameTmuxScreen,
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


def test_invoke_dialog_defaults_directory_and_has_role_selector() -> None:
    source = _compose_source(NewAgentScreen)
    assert 'Label("Invoke")' in source
    assert 'value="~/code"' in source
    assert "os.getcwd()" not in source
    assert "RadioSet(" in source
    assert "invoke-role-hippeus" in source
    assert "invoke-role-polemarch" in source
    assert "compact=False" in source
    assert "new-agent-buttons" not in source
    assert "launch-btn" not in source
    assert "cancel-btn" not in source

    submit_source = inspect.getsource(NewAgentScreen.on_input_submitted)
    assert "event.input.id == \"agent-dir\"" in submit_source
    assert "self._launch()" in submit_source


def test_rename_dialog_has_no_buttons_and_keeps_keyboard_flow() -> None:
    source = _compose_source(RenameScreen)
    assert "rename-buttons" not in source
    assert "rename-btn" not in source
    assert "cancel-btn" not in source

    submit_source = inspect.getsource(RenameScreen.on_input_submitted)
    assert "self._do_rename()" in submit_source

    bindings = {binding.key: binding.action for binding in RenameScreen.BINDINGS}
    assert bindings["escape"] == "dismiss"


def test_rename_tmux_dialog_has_no_buttons_and_keeps_keyboard_flow() -> None:
    source = _compose_source(RenameTmuxScreen)
    assert "rename-buttons" not in source
    assert "rename-btn" not in source
    assert "cancel-btn" not in source

    submit_source = inspect.getsource(RenameTmuxScreen.on_input_submitted)
    assert "self._do_rename()" in submit_source

    bindings = {binding.key: binding.action for binding in RenameTmuxScreen.BINDINGS}
    assert bindings["escape"] == "dismiss"
