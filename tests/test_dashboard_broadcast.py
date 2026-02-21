"""Tests for broadcast/direct share helpers."""

import subprocess
from pathlib import Path

from zeus.dashboard.app import ZeusApp, _extract_share_file_path, _extract_share_payload
from zeus.models import AgentWindow
from tests.helpers import capture_notify


def _agent(name: str, kitty_id: int, socket: str = "/tmp/kitty-1") -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket=socket,
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        agent_id=f"agent-{kitty_id}",
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


def test_extract_share_file_path_prefers_latest_zeus_msg_file_line() -> None:
    text = (
        "line\n"
        "ZEUS_MSG_FILE=/tmp/old.md\n"
        "another\n"
        "ZEUS_MSG_FILE='/tmp/new.md'\n"
    )
    assert _extract_share_file_path(text) == "/tmp/new.md"


def test_broadcast_recipients_include_paused_and_exclude_blocked() -> None:
    app = ZeusApp()
    source = _agent("source", 1)
    active = _agent("active", 2)
    paused = _agent("paused", 3)
    blocked = _agent("blocked", 4)

    app.agents = [source, active, paused, blocked]
    app._agent_priorities = {"paused": 4}
    app._agent_dependencies = {
        app._agent_dependency_key(blocked): app._agent_dependency_key(active),
    }

    recipients = app._broadcast_recipients(app._agent_key(source))
    assert [a.name for a in recipients] == ["active", "paused"]


def test_share_payload_prefers_session_transcript(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)

    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path",
        lambda agent: "/tmp/fake-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_text",
        lambda _: "",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_user_text",
        lambda _: "%%%%\nfrom session line 1\nfrom session line 2\n%%%%\n",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.get_screen_text",
        lambda agent, full=False, ansi=False: "%%%%\nfrom screen\n%%%%\n",
    )

    payload = app._share_payload_for_source(source)
    assert payload == "from session line 1\nfrom session line 2"


def test_share_payload_prefers_zeus_msg_file_pointer_in_session(monkeypatch, tmp_path: Path) -> None:
    app = ZeusApp()
    source = _agent("source", 1)
    payload_file = tmp_path / "zeus-msg-1.md"
    payload_file.write_text("from file payload\n")

    monkeypatch.setattr("zeus.dashboard.app.MESSAGE_TMP_DIR", tmp_path)
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path",
        lambda agent: "/tmp/fake-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_text",
        lambda _: f"note\nZEUS_MSG_FILE={payload_file}\n",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_user_text",
        lambda _: "%%%%\nfrom markers\n%%%%\n",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.get_screen_text",
        lambda agent, full=False, ansi=False: "%%%%\nfrom screen\n%%%%\n",
    )

    payload = app._share_payload_for_source(source)
    assert payload == "from file payload"


def test_share_payload_ignores_file_pointer_outside_message_tmp_dir(monkeypatch, tmp_path: Path) -> None:
    app = ZeusApp()
    source = _agent("source", 1)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside")

    monkeypatch.setattr("zeus.dashboard.app.MESSAGE_TMP_DIR", allowed)
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path",
        lambda agent: "/tmp/fake-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_text",
        lambda _: f"ZEUS_MSG_FILE={outside}\n",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_user_text",
        lambda _: "%%%%\nfrom markers\n%%%%\n",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.get_screen_text",
        lambda agent, full=False, ansi=False: "%%%%\nfrom screen\n%%%%\n",
    )

    payload = app._share_payload_for_source(source)
    assert payload == "from markers"


def test_share_payload_falls_back_to_screen_when_session_has_no_pair(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)

    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path",
        lambda agent: "/tmp/fake-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_user_text",
        lambda _: "no marker here",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.get_screen_text",
        lambda agent, full=False, ansi=False: "%%%%\nfrom screen\n%%%%\n",
    )

    payload = app._share_payload_for_source(source)
    assert payload == "from screen"


def test_share_payload_probe_reports_placeholder_file_pointer(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)

    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path",
        lambda _agent: "/tmp/fake-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.read_session_text",
        lambda _path: "ZEUS_MSG_FILE={MESSAGE_TMP_DIR}/zeus-msg-<uuid>.md\n",
    )
    monkeypatch.setattr("zeus.dashboard.app.read_session_user_text", lambda _path: "")
    monkeypatch.setattr(app, "_read_agent_screen_text", lambda _agent, full=False: "")

    payload, reason = app._share_payload_probe_for_source(source)

    assert payload is None
    assert reason is not None
    assert "placeholder" in reason
    assert "ZEUS_MSG_FILE" in reason


def test_summary_prepare_failed_notifies_as_warning(monkeypatch) -> None:
    app = ZeusApp()
    app._broadcast_active_job = 1

    notices: list[tuple[str, str, float]] = []
    monkeypatch.setattr(app, "_dismiss_broadcast_preparing_screen", lambda: None)
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, timeout=0, severity="information": notices.append(
            (message, severity, float(timeout))
        ),
    )

    app._summary_prepare_failed(1, "missing payload", 4)

    assert notices == [("missing payload", "warning", 4.0)]


def test_do_enqueue_broadcast_queues_active_and_paused_recipients(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)
    a1 = _agent("alpha", 2)
    a2 = _agent("beta", 3)
    paused = _agent("paused", 4)
    app.agents = [source, a1, a2, paused]
    app._agent_priorities = {"paused": 4}

    queued: list[str] = []
    monkeypatch.setattr("zeus.dashboard.app.capability_health", lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr("zeus.dashboard.app.has_agent_bus_receipt", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "zeus.dashboard.app.enqueue_agent_bus_message",
        lambda agent_id, *_args, **_kwargs: queued.append(agent_id) or True,
    )

    notices = capture_notify(app, monkeypatch)

    recipients = [app._agent_key(a1), app._agent_key(a2), app._agent_key(paused)]
    app.do_enqueue_broadcast("source", recipients, "payload")

    assert queued == ["agent-2", "agent-3", "agent-4"]
    assert app._agent_priorities.get(paused.name, 3) == 3
    assert notices[-1] == "Broadcast from source queued to 3 Hippeis"


def test_action_yank_summary_payload_copies_payload(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)

    copied: list[str] = []
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: source)
    monkeypatch.setattr(app, "_share_payload_for_source", lambda _source: "payload")
    monkeypatch.setattr(
        app,
        "_copy_text_to_system_clipboard",
        lambda text: copied.append(text) or True,
    )

    app.action_yank_summary_payload()

    assert copied == ["payload"]
    assert notices[-1] == "Yanked payload: source"


def test_action_yank_summary_payload_requires_selected_agent(monkeypatch) -> None:
    app = ZeusApp()
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: None)

    app.action_yank_summary_payload()

    assert notices[-1] == "Select a Hippeus row to yank summary payload"


def test_action_yank_summary_payload_notifies_when_no_payload(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: source)
    monkeypatch.setattr(app, "_share_payload_for_source", lambda _source: None)

    app.action_yank_summary_payload()

    assert notices[-1] == app._SHARE_MARKER_REMINDER


def test_action_yank_summary_payload_notifies_when_block_empty(monkeypatch) -> None:
    app = ZeusApp()
    source = _agent("source", 1)
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: source)
    monkeypatch.setattr(app, "_share_payload_for_source", lambda _source: "")

    app.action_yank_summary_payload()

    assert notices[-1] == "Wrapped %%%% markers found, but the enclosed block is empty."


def test_action_yank_summary_payload_uses_force_notify_when_clipboard_missing(
    monkeypatch,
) -> None:
    app = ZeusApp()
    source = _agent("source", 1)

    notices = capture_notify(app, monkeypatch)
    forced: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: source)
    monkeypatch.setattr(app, "_share_payload_for_source", lambda _source: "payload")
    monkeypatch.setattr(app, "_copy_text_to_system_clipboard", lambda _text: False)
    monkeypatch.setattr(app, "notify_force", lambda message, timeout=3: forced.append(message))

    app.action_yank_summary_payload()

    assert notices == []
    assert forced[-1] == "Could not copy payload to clipboard (wl-copy)"


def test_copy_text_to_system_clipboard_returns_false_when_wl_copy_missing(monkeypatch) -> None:
    app = ZeusApp()
    monkeypatch.setattr("zeus.dashboard.app.shutil.which", lambda _name: None)

    assert app._copy_text_to_system_clipboard("payload") is False


def test_copy_text_to_system_clipboard_treats_timeout_as_success(monkeypatch) -> None:
    app = ZeusApp()

    class _DummyStdin:
        def __init__(self) -> None:
            self.writes: list[str] = []
            self.closed = False

        def write(self, text: str) -> None:
            self.writes.append(text)

        def close(self) -> None:
            self.closed = True

    stdin = _DummyStdin()

    class _DummyProc:
        def __init__(self) -> None:
            self.stdin = stdin
            self.returncode = 0

        def wait(self, timeout: float = 0.0) -> int:
            raise subprocess.TimeoutExpired(cmd=["wl-copy"], timeout=timeout)

    monkeypatch.setattr("zeus.dashboard.app.shutil.which", lambda _name: "/usr/bin/wl-copy")
    monkeypatch.setattr("zeus.dashboard.app.subprocess.Popen", lambda *args, **kwargs: _DummyProc())

    assert app._copy_text_to_system_clipboard("payload") is True
    assert stdin.writes == ["payload"]
    assert stdin.closed is True
