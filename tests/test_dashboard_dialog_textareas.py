"""Tests ensuring dialog textareas use ZeusTextArea behavior parity."""

import inspect
import re
from types import SimpleNamespace

from zeus.dashboard.screens import (
    AgentMessageScreen,
    AgentTasksScreen,
    ConfirmBroadcastScreen,
    ConfirmDirectMessageScreen,
    ExpandedOutputScreen,
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


def test_expanded_output_screen_uses_rich_log_and_message_shortcut() -> None:
    source = _compose_source(ExpandedOutputScreen)
    assert "RichLog(" in source
    assert "expanded-output-stream" in source

    bindings = {binding.key: binding.action for binding in ExpandedOutputScreen.BINDINGS}
    assert bindings["escape"] == "dismiss"
    assert bindings["e"] == "dismiss"
    assert bindings["f5"] == "refresh"
    assert bindings["enter"] == "message"
    assert "m" not in bindings


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
    assert "rename-error" in source

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


class _InputStub:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class _LabelStub:
    def __init__(self) -> None:
        self.text = ""

    def update(self, text: str) -> None:
        self.text = text


def test_invoke_launch_rejects_duplicate_agent_name(monkeypatch) -> None:
    screen = NewAgentScreen()
    name_input = _InputStub("taken")
    dir_input = _InputStub("~/code")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-name":
            return name_input
        if selector == "#agent-dir":
            return dir_input
        if selector == "#invoke-role":
            return SimpleNamespace(pressed_button=SimpleNamespace(id="invoke-role-hippeus"))
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    notices: list[str] = []

    class _ZeusStub:
        def _is_agent_name_taken(self, name: str, **_kwargs) -> bool:  # noqa: ANN003
            return name == "taken"

        def notify(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

        def schedule_polemarch_bootstrap(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("must not bootstrap on duplicate")

        def set_timer(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("must not schedule timer on duplicate")

    monkeypatch.setattr(NewAgentScreen, "zeus", property(lambda self: _ZeusStub()))

    popen_called: list[bool] = []
    monkeypatch.setattr(
        "zeus.dashboard.screens.subprocess.Popen",
        lambda *args, **kwargs: popen_called.append(True),  # noqa: ARG005
    )

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen._launch()

    assert notices[-1] == "Name already exists: taken"
    assert name_input.focused is True
    assert popen_called == []
    assert dismissed == []


def test_invoke_launch_sets_hippeus_role_env(monkeypatch) -> None:
    screen = NewAgentScreen()
    name_input = _InputStub("alpha")
    dir_input = _InputStub("~/code")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-name":
            return name_input
        if selector == "#agent-dir":
            return dir_input
        if selector == "#invoke-role":
            return SimpleNamespace(pressed_button=SimpleNamespace(id="invoke-role-hippeus"))
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)
    monkeypatch.setattr("zeus.dashboard.screens.generate_agent_id", lambda: "agent-1")

    schedule_calls: list[tuple[str, str]] = []
    notices: list[str] = []
    timers: list[float] = []

    class _ZeusStub:
        def _is_agent_name_taken(self, _name: str, **_kwargs) -> bool:  # noqa: ANN003
            return False

        def notify(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

        def schedule_polemarch_bootstrap(self, agent_id: str, name: str) -> None:
            schedule_calls.append((agent_id, name))

        def set_timer(self, delay: float, _callback) -> None:  # noqa: ANN001
            timers.append(delay)

        def poll_and_update(self) -> None:
            return

    monkeypatch.setattr(NewAgentScreen, "zeus", property(lambda self: _ZeusStub()))

    popen_env: dict[str, str] = {}

    class _DummyProc:
        pid = 123

    def _fake_popen(_cmd, **kwargs):  # noqa: ANN001
        popen_env.update(kwargs.get("env", {}))
        return _DummyProc()

    monkeypatch.setattr("zeus.dashboard.screens.subprocess.Popen", _fake_popen)

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen._launch()

    assert popen_env["ZEUS_AGENT_NAME"] == "alpha"
    assert popen_env["ZEUS_AGENT_ID"] == "agent-1"
    assert popen_env["ZEUS_ROLE"] == "hippeus"
    assert "ZEUS_PHALANX_ID" not in popen_env
    assert schedule_calls == []
    assert notices[-1] == "Invoked Hippeus: alpha"
    assert timers == [1.5]
    assert dismissed == [True]


def test_invoke_launch_sets_polemarch_role_env(monkeypatch) -> None:
    screen = NewAgentScreen()
    name_input = _InputStub("planner")
    dir_input = _InputStub("~/code")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-name":
            return name_input
        if selector == "#agent-dir":
            return dir_input
        if selector == "#invoke-role":
            return SimpleNamespace(pressed_button=SimpleNamespace(id="invoke-role-polemarch"))
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)
    monkeypatch.setattr("zeus.dashboard.screens.generate_agent_id", lambda: "agent-2")

    schedule_calls: list[tuple[str, str]] = []
    notices: list[str] = []

    class _ZeusStub:
        def _is_agent_name_taken(self, _name: str, **_kwargs) -> bool:  # noqa: ANN003
            return False

        def notify(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

        def schedule_polemarch_bootstrap(self, agent_id: str, name: str) -> None:
            schedule_calls.append((agent_id, name))

        def set_timer(self, _delay: float, _callback) -> None:  # noqa: ANN001
            return

        def poll_and_update(self) -> None:
            return

    monkeypatch.setattr(NewAgentScreen, "zeus", property(lambda self: _ZeusStub()))

    popen_env: dict[str, str] = {}

    class _DummyProc:
        pid = 123

    def _fake_popen(_cmd, **kwargs):  # noqa: ANN001
        popen_env.update(kwargs.get("env", {}))
        return _DummyProc()

    monkeypatch.setattr("zeus.dashboard.screens.subprocess.Popen", _fake_popen)
    monkeypatch.setattr(screen, "dismiss", lambda: None)

    screen._launch()

    assert popen_env["ZEUS_AGENT_NAME"] == "planner"
    assert popen_env["ZEUS_AGENT_ID"] == "agent-2"
    assert popen_env["ZEUS_ROLE"] == "polemarch"
    assert popen_env["ZEUS_PHALANX_ID"] == "phalanx-agent-2"
    assert schedule_calls == [("agent-2", "planner")]
    assert notices[-1] == "Invoked Polemarch: planner"


def test_rename_dialog_shows_inline_error_for_duplicate_name(monkeypatch) -> None:
    from zeus.models import AgentWindow

    agent = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )
    screen = RenameScreen(agent)

    rename_input = _InputStub("taken")
    rename_error = _LabelStub()

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#rename-input":
            return rename_input
        if selector == "#rename-error":
            return rename_error
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    rename_calls: list[str] = []

    class _ZeusStub:
        def _agent_key(self, _agent: AgentWindow) -> str:
            return "/tmp/kitty-1:1"

        def _is_agent_name_taken(self, name: str, **_kwargs) -> bool:  # noqa: ANN003
            return name == "taken"

        def do_rename_agent(self, _agent: AgentWindow, new_name: str) -> bool:
            rename_calls.append(new_name)
            return True

    monkeypatch.setattr(RenameScreen, "zeus", property(lambda self: _ZeusStub()))

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen._do_rename()

    assert rename_error.text == "Name already exists. Choose a unique Hippeus name."
    assert rename_input.focused is True
    assert rename_calls == []
    assert dismissed == []
