"""Tests for interact stream refresh throttling/deduplication."""

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow


class _DummyStream:
    def __init__(self) -> None:
        self.clear_calls = 0
        self.writes: list[object] = []

    def clear(self) -> None:
        self.clear_calls += 1

    def write(self, payload: object) -> None:
        self.writes.append(payload)


def _agent() -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )


def test_update_interact_stream_defers_fetch_while_typing(monkeypatch) -> None:
    app = ZeusApp()
    app._interact_visible = True
    app._interact_agent_key = "agent-key"

    fetched: list[AgentWindow] = []
    monkeypatch.setattr(app, "_typing_in_interact_input_recently", lambda: True)
    monkeypatch.setattr(app, "_get_agent_by_key", lambda key: _agent())
    monkeypatch.setattr(app, "_fetch_interact_stream", lambda agent: fetched.append(agent))

    app._update_interact_stream()

    assert fetched == []


def test_update_interact_stream_fetches_when_not_typing(monkeypatch) -> None:
    app = ZeusApp()
    app._interact_visible = True
    app._interact_agent_key = "agent-key"

    agent = _agent()
    fetched: list[AgentWindow] = []
    monkeypatch.setattr(app, "_typing_in_interact_input_recently", lambda: False)
    monkeypatch.setattr(app, "_get_agent_by_key", lambda key: agent)
    monkeypatch.setattr(app, "_fetch_interact_stream", lambda target: fetched.append(target))

    app._update_interact_stream()

    assert fetched == [agent]


def test_apply_interact_stream_skips_duplicate_render(monkeypatch) -> None:
    app = ZeusApp()
    app._interact_visible = True
    app._interact_agent_key = "agent-key"
    stream = _DummyStream()

    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: stream)

    app._apply_interact_stream("agent-key", "alpha", "hello\n")
    app._apply_interact_stream("agent-key", "alpha", "hello\n")
    app._apply_interact_stream("agent-key", "alpha", "hello\nworld\n")

    assert stream.clear_calls == 2
    assert len(stream.writes) == 2


def test_apply_tmux_stream_skips_duplicate_render(monkeypatch) -> None:
    app = ZeusApp()
    app._interact_visible = True
    app._interact_tmux_name = "sess-1"
    stream = _DummyStream()

    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: stream)

    app._apply_tmux_stream("sess-1", "line\n")
    app._apply_tmux_stream("sess-1", "line\n")
    app._apply_tmux_stream("sess-1", "line\nnext\n")

    assert stream.clear_calls == 2
    assert len(stream.writes) == 2
