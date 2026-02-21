"""Tests ensuring dialog textareas use ZeusTextArea behavior parity."""

import inspect
import re
from types import SimpleNamespace

from zeus.dashboard.screens import (
    AegisConfigureScreen,
    AgentMessageScreen,
    PremadeMessageScreen,
    AgentTasksScreen,
    ConfirmBroadcastScreen,
    ConfirmDirectMessageScreen,
    ExpandedOutputScreen,
    NewAgentScreen,
    RenameScreen,
    RenameTmuxScreen,
    SaveSnapshotScreen,
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


def test_premade_message_dialog_uses_select_and_editable_textarea() -> None:
    source = _compose_source(PremadeMessageScreen)
    assert "Select(" in source
    assert "premade-message-template-select" in source
    assert "ZeusTextArea(" in source
    assert _PLAIN_TEXTAREA_CALL_RE.search(source) is None
    assert "premade-message-input" in source
    assert "(Control-S send | Control-W queue)" in source


def test_expanded_output_screen_uses_rich_log_and_message_shortcut() -> None:
    source = _compose_source(ExpandedOutputScreen)
    assert "RichLog(" in source
    assert "expanded-output-stream" in source
    assert "expanded-output-scroll-flash" in source

    bindings = {binding.key: binding.action for binding in ExpandedOutputScreen.BINDINGS}
    assert bindings["escape"] == "dismiss"
    assert bindings["e"] == "dismiss"
    assert bindings["f5"] == "refresh"
    assert bindings["g"] == "go_ahead"
    assert bindings["enter"] == "message"
    assert "m" not in bindings


def test_invoke_dialog_defaults_directory_and_has_role_selector() -> None:
    source = _compose_source(NewAgentScreen)
    assert 'Label("Invoke")' in source
    assert 'value="~/code"' in source
    assert "os.getcwd()" not in source
    assert "RadioSet(" in source
    assert "invoke-role-hippeus" in source
    assert "invoke-role-stygian-hippeus" in source
    assert "invoke-role-polemarch" in source
    assert "compact=False" in source
    assert "OptionList(" in source
    assert "agent-dir-suggestions" in source
    assert "new-agent-buttons" not in source
    assert "launch-btn" not in source
    assert "cancel-btn" not in source

    submit_source = inspect.getsource(NewAgentScreen.on_input_submitted)
    assert "event.input.id == \"agent-dir\"" in submit_source
    assert "self._apply_highlighted_dir_suggestion" not in submit_source
    assert "self._launch()" in submit_source


def test_aegis_config_dialog_uses_radio_options_and_textarea() -> None:
    source = _compose_source(AegisConfigureScreen)
    assert "RadioSet(" in source
    assert "aegis-config-continue" in source
    assert "aegis-config-iterate" in source
    assert "aegis-config-completion" in source
    assert "ZeusTextArea(" in source
    assert "aegis-config-prompt" in source


def test_aegis_config_switching_mode_loads_different_prompt(monkeypatch) -> None:
    from zeus.models import AgentWindow

    agent = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )
    screen = AegisConfigureScreen(
        agent,
        continue_prompt="continue-default",
        iterate_prompt="iterate-default",
        completion_prompt="completion-default",
    )

    mode_set = _RadioSetStub("aegis-config-iterate")
    prompt = _TextAreaStub("edited-continue")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#aegis-config-mode":
            return mode_set
        if selector == "#aegis-config-prompt":
            return prompt
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    event = SimpleNamespace(radio_set=SimpleNamespace(id="aegis-config-mode"))
    screen.on_radio_set_changed(event)

    assert prompt.text == "iterate-default"
    assert screen._prompt_by_mode["continue"] == "edited-continue"
    assert mode_set.focused is True


def test_aegis_config_switching_to_completion_loads_completion_prompt(monkeypatch) -> None:
    from zeus.models import AgentWindow

    agent = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )
    screen = AegisConfigureScreen(
        agent,
        continue_prompt="continue-default",
        iterate_prompt="iterate-default",
        completion_prompt="completion-default",
    )

    mode_set = _RadioSetStub("aegis-config-completion")
    prompt = _TextAreaStub("edited-continue")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#aegis-config-mode":
            return mode_set
        if selector == "#aegis-config-prompt":
            return prompt
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    event = SimpleNamespace(radio_set=SimpleNamespace(id="aegis-config-mode"))
    screen.on_radio_set_changed(event)

    assert prompt.text == "completion-default"
    assert screen._prompt_by_mode["continue"] == "edited-continue"
    assert mode_set.focused is True


def test_aegis_config_mount_focuses_mode_selection(monkeypatch) -> None:
    from zeus.models import AgentWindow

    agent = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )
    screen = AegisConfigureScreen(
        agent,
        continue_prompt="continue-default",
        iterate_prompt="iterate-default",
        completion_prompt="completion-default",
    )

    mode_set = _RadioSetStub("aegis-config-continue")

    monkeypatch.setattr(
        screen,
        "query_one",
        lambda selector, cls=None: mode_set if selector == "#aegis-config-mode" else (_ for _ in ()).throw(LookupError(selector)),
    )

    screen.on_mount()

    assert mode_set.focused is True


def test_premade_message_switching_template_loads_selected_text(monkeypatch) -> None:
    from zeus.models import AgentWindow

    agent = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )
    screen = PremadeMessageScreen(
        agent,
        templates=[
            ("Self-review", "Review your output against your own claims again"),
            ("Escalate", "Escalate blockers with concrete options"),
        ],
    )

    select = _SelectStub("Escalate")
    text_area = _TextAreaStub("custom self-review")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#premade-message-template-select":
            return select
        if selector == "#premade-message-input":
            return text_area
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    event = SimpleNamespace(
        select=SimpleNamespace(id="premade-message-template-select"),
        value="Escalate",
    )
    screen.on_select_changed(event)

    assert screen._message_by_title["Self-review"] == "custom self-review"
    assert text_area.text == "Escalate blockers with concrete options"


def test_premade_message_mount_focuses_template_select(monkeypatch) -> None:
    from zeus.models import AgentWindow

    agent = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )
    screen = PremadeMessageScreen(
        agent,
        templates=[("Self-review", "Review your output against your own claims again")],
    )

    select = _SelectStub("Self-review")

    monkeypatch.setattr(
        screen,
        "query_one",
        lambda selector, cls=None: select if selector == "#premade-message-template-select" else (_ for _ in ()).throw(LookupError(selector)),
    )

    screen.on_mount()

    assert select.focused is True


def test_new_agent_dir_suggestions_match_prefix() -> None:
    from tempfile import TemporaryDirectory
    from pathlib import Path

    with TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        (tmp / "alpha").mkdir()
        (tmp / "alphabet").mkdir()
        (tmp / "beta").mkdir()

        screen = NewAgentScreen()
        suggestions = screen._dir_suggestions(str(tmp / "alp"))

    assert suggestions == [
        str(tmp / "alpha") + "/",
        str(tmp / "alphabet") + "/",
    ]


def test_new_agent_submit_launches_without_completion_capture(monkeypatch) -> None:
    screen = NewAgentScreen()
    launches: list[bool] = []

    monkeypatch.setattr(
        screen,
        "_apply_highlighted_dir_suggestion",
        lambda *, only_if_different: (_ for _ in ()).throw(
            AssertionError("should not capture Enter for completion")
        ),
    )
    monkeypatch.setattr(screen, "_launch", lambda: launches.append(True))

    event = SimpleNamespace(input=SimpleNamespace(id="agent-dir"))
    screen.on_input_submitted(event)

    assert launches == [True]


def test_new_agent_tab_cycles_directory_suggestions(monkeypatch) -> None:
    screen = NewAgentScreen()
    directory_input = _InputStub("~/co")
    options = _OptionListStub(hidden=True)

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-dir":
            return directory_input
        if selector == "#agent-dir-suggestions":
            return options
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    def _refresh(_raw: str) -> None:
        screen._dir_suggestion_values = ["~/code/", "~/config/"]
        options.remove_class("hidden")

    monkeypatch.setattr(screen, "_refresh_dir_suggestions", _refresh)

    assert screen._cycle_dir_suggestion(forward=True) is True
    assert directory_input.value == "~/code/"
    assert options.highlighted == 0

    assert screen._cycle_dir_suggestion(forward=True) is True
    assert directory_input.value == "~/config/"
    assert options.highlighted == 1

    assert screen._cycle_dir_suggestion(forward=False) is True
    assert directory_input.value == "~/code/"
    assert options.highlighted == 0


def test_new_agent_on_key_routes_tab_to_cycle_and_leaves_shift_tab_for_focus_nav(
    monkeypatch,
) -> None:
    screen = NewAgentScreen()
    directory_input = _InputStub("~/co")
    options = _OptionListStub(hidden=False)

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-dir":
            return directory_input
        if selector == "#agent-dir-suggestions":
            return options
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)
    monkeypatch.setattr(NewAgentScreen, "focused", property(lambda _self: directory_input))

    calls: list[bool] = []
    monkeypatch.setattr(
        screen,
        "_cycle_dir_suggestion",
        lambda *, forward: calls.append(forward) or True,
    )

    tab_event = _KeyEventStub("tab")
    screen.on_key(tab_event)

    shift_tab_event = _KeyEventStub("shift+tab")
    screen.on_key(shift_tab_event)

    assert calls == [True]
    assert tab_event.prevented is True
    assert tab_event.stopped is True
    assert shift_tab_event.prevented is False
    assert shift_tab_event.stopped is False


def test_new_agent_delete_dir_segment_left_to_previous_slash(monkeypatch) -> None:
    screen = NewAgentScreen()
    directory_input = _InputStub("~/code/zeus/")
    directory_input.cursor_position = len(directory_input.value)

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-dir":
            return directory_input
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    refreshed: list[str] = []
    monkeypatch.setattr(screen, "_refresh_dir_suggestions", lambda raw: refreshed.append(raw))

    ok = screen._delete_dir_segment_left()

    assert ok is True
    assert directory_input.value == "~/code/"
    assert directory_input.cursor_position == len("~/code/")
    assert refreshed == ["~/code/"]


def test_new_agent_on_key_routes_alt_backspace_to_path_segment_delete(monkeypatch) -> None:
    screen = NewAgentScreen()
    directory_input = _InputStub("~/code/zeus/")
    options = _OptionListStub(hidden=False)

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-dir":
            return directory_input
        if selector == "#agent-dir-suggestions":
            return options
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)
    monkeypatch.setattr(NewAgentScreen, "focused", property(lambda _self: directory_input))

    called: list[bool] = []
    monkeypatch.setattr(screen, "_delete_dir_segment_left", lambda: called.append(True) or True)

    event = _KeyEventStub("alt+backspace")
    screen.on_key(event)

    assert called == [True]
    assert event.prevented is True
    assert event.stopped is True


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


def test_snapshot_save_dialog_uses_checkbox_for_close_all() -> None:
    source = _compose_source(SaveSnapshotScreen)
    assert "Checkbox(" in source
    assert "snapshot-save-close-all" in source
    assert "value=False" in source
    assert "compact=False" in source
    assert "RadioSet(" not in source
    assert "Select(" not in source


class _InputStub:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.cursor_position = len(value)
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class _OptionListStub:
    def __init__(self, *, hidden: bool = True) -> None:
        self.classes: set[str] = {"hidden"} if hidden else set()
        self.highlighted: int | None = None

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)


class _RadioSetStub:
    def __init__(self, pressed_id: str) -> None:
        self.pressed_button = SimpleNamespace(id=pressed_id)
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class _SelectStub:
    def __init__(self, value: str) -> None:
        self.value = value
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class _TextAreaStub:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.document = SimpleNamespace(end=(0, 0))

    def load_text(self, text: str) -> None:
        self.text = text

    def move_cursor(self, _cursor) -> None:  # noqa: ANN001
        return


class _KeyEventStub:
    def __init__(self, key: str) -> None:
        self.key = key
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


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
    monkeypatch.setattr(
        "zeus.dashboard.screens.make_new_session_path",
        lambda _cwd: "/tmp/invoke-agent-1.jsonl",
    )

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
    popen_cmd: list[str] = []

    class _DummyProc:
        pid = 123

    def _fake_popen(cmd, **kwargs):  # noqa: ANN001
        popen_cmd[:] = list(cmd)
        popen_env.update(kwargs.get("env", {}))
        return _DummyProc()

    monkeypatch.setattr("zeus.dashboard.screens.subprocess.Popen", _fake_popen)

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen._launch()

    assert popen_env["ZEUS_AGENT_NAME"] == "alpha"
    assert popen_env["ZEUS_AGENT_ID"] == "agent-1"
    assert popen_env["ZEUS_ROLE"] == "hippeus"
    assert popen_env["ZEUS_SESSION_PATH"] == "/tmp/invoke-agent-1.jsonl"
    assert "ZEUS_PHALANX_ID" not in popen_env
    assert popen_cmd[-1] == "pi --session /tmp/invoke-agent-1.jsonl"
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
    monkeypatch.setattr(
        "zeus.dashboard.screens.make_new_session_path",
        lambda _cwd: "/tmp/invoke-agent-2.jsonl",
    )

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
    popen_cmd: list[str] = []

    class _DummyProc:
        pid = 123

    def _fake_popen(cmd, **kwargs):  # noqa: ANN001
        popen_cmd[:] = list(cmd)
        popen_env.update(kwargs.get("env", {}))
        return _DummyProc()

    monkeypatch.setattr("zeus.dashboard.screens.subprocess.Popen", _fake_popen)
    monkeypatch.setattr(screen, "dismiss", lambda: None)

    screen._launch()

    assert popen_env["ZEUS_AGENT_NAME"] == "planner"
    assert popen_env["ZEUS_AGENT_ID"] == "agent-2"
    assert popen_env["ZEUS_ROLE"] == "polemarch"
    assert popen_env["ZEUS_SESSION_PATH"] == "/tmp/invoke-agent-2.jsonl"
    assert popen_env["ZEUS_PHALANX_ID"] == "phalanx-agent-2"
    assert popen_cmd[-1] == "pi --session /tmp/invoke-agent-2.jsonl"
    assert schedule_calls == [("agent-2", "planner")]
    assert notices[-1] == "Invoked Polemarch: planner"


def test_invoke_launch_stygian_hippeus_uses_tmux_backend(monkeypatch) -> None:
    screen = NewAgentScreen()
    name_input = _InputStub("shadow")
    dir_input = _InputStub("~/code")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-name":
            return name_input
        if selector == "#agent-dir":
            return dir_input
        if selector == "#invoke-role":
            return SimpleNamespace(
                pressed_button=SimpleNamespace(id="invoke-role-stygian-hippeus")
            )
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)
    monkeypatch.setattr("zeus.dashboard.screens.generate_agent_id", lambda: "agent-3")

    notices: list[str] = []
    timers: list[float] = []

    class _ZeusStub:
        def _is_agent_name_taken(self, _name: str, **_kwargs) -> bool:  # noqa: ANN003
            return False

        def notify(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

        def schedule_polemarch_bootstrap(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("must not bootstrap stygian invoke")

        def set_timer(self, delay: float, _callback) -> None:  # noqa: ANN001
            timers.append(delay)

        def poll_and_update(self) -> None:
            return

    monkeypatch.setattr(NewAgentScreen, "zeus", property(lambda self: _ZeusStub()))

    launch_calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "zeus.dashboard.screens.launch_stygian_hippeus",
        lambda *, name, directory, agent_id: launch_calls.append(
            (name, directory, agent_id)
        )
        or ("stygian-agent-3", "/tmp/session.jsonl"),
    )

    popen_called: list[bool] = []
    monkeypatch.setattr(
        "zeus.dashboard.screens.subprocess.Popen",
        lambda *args, **kwargs: popen_called.append(True),  # noqa: ARG005
    )

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen._launch()

    assert launch_calls[0][0] == "shadow"
    assert launch_calls[0][1].endswith("/code")
    assert launch_calls[0][2] == "agent-3"
    assert popen_called == []
    assert notices[-1] == "Invoked Stygian Hippeus: shadow"
    assert timers == [1.5]
    assert dismissed == [True]


def test_invoke_launch_stygian_hippeus_notifies_on_failure(monkeypatch) -> None:
    screen = NewAgentScreen()
    name_input = _InputStub("shadow")
    dir_input = _InputStub("~/code")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-name":
            return name_input
        if selector == "#agent-dir":
            return dir_input
        if selector == "#invoke-role":
            return SimpleNamespace(
                pressed_button=SimpleNamespace(id="invoke-role-stygian-hippeus")
            )
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)
    monkeypatch.setattr("zeus.dashboard.screens.generate_agent_id", lambda: "agent-4")

    notices: list[str] = []

    class _ZeusStub:
        def _is_agent_name_taken(self, _name: str, **_kwargs) -> bool:  # noqa: ANN003
            return False

        def notify(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

        def schedule_polemarch_bootstrap(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("must not bootstrap stygian invoke")

        def set_timer(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("must not schedule timer on failed invoke")

        def poll_and_update(self) -> None:
            return

    monkeypatch.setattr(NewAgentScreen, "zeus", property(lambda self: _ZeusStub()))

    monkeypatch.setattr(
        "zeus.dashboard.screens.launch_stygian_hippeus",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("tmux unavailable")),
    )

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen._launch()

    assert notices[-1] == "Failed to invoke Stygian Hippeus: tmux unavailable"
    assert dismissed == []


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
