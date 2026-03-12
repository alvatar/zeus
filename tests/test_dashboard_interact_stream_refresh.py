"""Tests for interact stream refresh deduplication."""

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


def test_update_interact_stream_skips_fetch_when_signature_unchanged(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent()
    agent_key = app._agent_key(agent)

    app.agents = [agent]
    app._interact_visible = True
    app._interact_agent_key = agent_key
    app._screen_activity_sig[agent_key] = "sig-a"

    fetched: list[AgentWindow] = []
    monkeypatch.setattr(app, "_fetch_interact_stream", lambda target: fetched.append(target))

    app._update_interact_stream()
    app._update_interact_stream()

    assert fetched == [agent]


def test_update_interact_stream_fetches_when_signature_changes(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent()
    agent_key = app._agent_key(agent)

    app.agents = [agent]
    app._interact_visible = True
    app._interact_agent_key = agent_key

    fetched: list[AgentWindow] = []
    monkeypatch.setattr(app, "_fetch_interact_stream", lambda target: fetched.append(target))

    app._screen_activity_sig[agent_key] = "sig-a"
    app._update_interact_stream()

    app._screen_activity_sig[agent_key] = "sig-b"
    app._update_interact_stream()

    assert fetched == [agent, agent]


def test_update_interact_stream_uses_screen_text_signature_fallback(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent()
    agent_key = app._agent_key(agent)

    app.agents = [agent]
    app._interact_visible = True
    app._interact_agent_key = agent_key
    agent._screen_text = "line 1\n"

    fetched: list[AgentWindow] = []
    monkeypatch.setattr(app, "_fetch_interact_stream", lambda target: fetched.append(target))

    app._update_interact_stream()
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
