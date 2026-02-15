"""Tests for broadcast/direct share helpers."""

from zeus.dashboard.app import ZeusApp, _extract_share_payload
from zeus.models import AgentWindow


def _agent(name: str, kitty_id: int, socket: str = "/tmp/kitty-1") -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket=socket,
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
    )


def test_extract_share_payload_returns_text_between_last_complete_pair() -> None:
    text = (
        "%%%%\n"
        "old payload\n"
        "%%%%\n"
        "noise\n"
        "%%%%\n"
        "new payload line 1\n"
        "new payload line 2\n"
        "%%%%\n"
    )
    assert _extract_share_payload(text) == "new payload line 1\nnew payload line 2"


def test_extract_share_payload_ignores_unmatched_trailing_marker() -> None:
    text = (
        "%%%%\n"
        "payload\n"
        "%%%%\n"
        "%%%%\n"
    )
    assert _extract_share_payload(text) == "payload"


def test_extract_share_payload_returns_none_when_missing_pair() -> None:
    assert _extract_share_payload("a\n%%%%\nb\n") is None


def test_extract_share_payload_empty_when_wrapped_block_empty() -> None:
    assert _extract_share_payload("x\n%%%%\n\n%%%%\n") == ""


def test_broadcast_recipients_exclude_source_and_paused() -> None:
    app = ZeusApp()
    source = _agent("source", 1)
    active = _agent("active", 2)
    paused = _agent("paused", 3)

    app.agents = [source, active, paused]
    app._agent_priorities = {"paused": 4}

    recipients = app._broadcast_recipients(app._agent_key(source))
    assert [a.name for a in recipients] == ["active"]


def test_share_payload_prefers_session_transcript(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)

    monkeypatch.setattr(
        "zeus.dashboard.app.find_current_session",
        lambda cwd: "/tmp/fake-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_text",
        lambda _: "%%%%\nfrom session line 1\nfrom session line 2\n%%%%\n",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.get_screen_text",
        lambda agent, full=False, ansi=False: "%%%%\nfrom screen\n%%%%\n",
    )

    payload = app._share_payload_for_source(source)
    assert payload == "from session line 1\nfrom session line 2"


def test_share_payload_falls_back_to_screen_when_session_has_no_pair(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)

    monkeypatch.setattr(
        "zeus.dashboard.app.find_current_session",
        lambda cwd: "/tmp/fake-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_text",
        lambda _: "no marker here",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.get_screen_text",
        lambda agent, full=False, ansi=False: "%%%%\nfrom screen\n%%%%\n",
    )

    payload = app._share_payload_for_source(source)
    assert payload == "from screen"
