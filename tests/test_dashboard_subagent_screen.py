"""Tests for SubAgentScreen model selection + dispatch."""

from types import SimpleNamespace

from zeus.dashboard.screens import SubAgentScreen
from zeus.models import AgentWindow


def _agent() -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="parent",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
        agent_id="parent-1",
    )


class _InputStub:
    def __init__(self, value: str) -> None:
        self.value = value
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class _SelectStub:
    def __init__(self, value: str) -> None:
        self.value = value


def test_subagent_selected_model_default_maps_to_empty(monkeypatch) -> None:
    screen = SubAgentScreen(_agent())

    monkeypatch.setattr(
        screen,
        "query_one",
        lambda selector, cls=None: _SelectStub("__default__") if selector == "#subagent-model" else None,
    )

    assert screen._selected_model_spec() == ""


def test_subagent_create_clone_forwards_model_spec(monkeypatch) -> None:
    screen = SubAgentScreen(_agent())

    name_input = _InputStub("child")
    mode_radio = SimpleNamespace(pressed_index=0)
    model_select = _SelectStub("openai/gpt-4o")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#subagent-name":
            return name_input
        if selector == "#subagent-mode":
            return mode_radio
        if selector == "#subagent-model":
            return model_select
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    clone_calls: list[tuple[str, str]] = []
    workdir_called: list[bool] = []

    class _ZeusStub:
        def do_spawn_subagent(self, agent, name: str, *, model_spec: str = "") -> None:  # noqa: ANN001
            clone_calls.append((name, model_spec))

        def do_spawn_workdir_agent(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            workdir_called.append(True)

    monkeypatch.setattr(SubAgentScreen, "zeus", property(lambda self: _ZeusStub()))

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen._create()

    assert clone_calls == [("child", "openai/gpt-4o")]
    assert workdir_called == []
    assert dismissed == [True]


def test_subagent_create_workdir_forwards_model_spec(monkeypatch) -> None:
    screen = SubAgentScreen(_agent())

    name_input = _InputStub("child-wt")
    mode_radio = SimpleNamespace(pressed_index=1)
    model_select = _SelectStub("anthropic/claude-sonnet-4-5")

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#subagent-name":
            return name_input
        if selector == "#subagent-mode":
            return mode_radio
        if selector == "#subagent-model":
            return model_select
        raise LookupError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    workdir_calls: list[tuple[str, str, object]] = []
    clone_called: list[bool] = []

    class _ZeusStub:
        def do_spawn_workdir_agent(
            self,
            agent,
            name: str,
            dismiss_screen=None,
            source_directory: str | None = None,
            *,
            model_spec: str = "",
        ) -> None:  # noqa: ANN001
            workdir_calls.append((name, model_spec, dismiss_screen))

        def do_spawn_subagent(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            clone_called.append(True)

    monkeypatch.setattr(SubAgentScreen, "zeus", property(lambda self: _ZeusStub()))

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen._create()

    assert workdir_calls == [("child-wt", "anthropic/claude-sonnet-4-5", screen)]
    assert clone_called == []
    assert dismissed == []
