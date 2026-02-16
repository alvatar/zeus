"""Tests for dashboard agent notes behavior helpers."""

from zeus.dashboard.app import ZeusApp, _extract_next_note_task
from zeus.models import AgentWindow


def _agent(name: str, kitty_id: int, agent_id: str = "") -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        agent_id=agent_id,
    )


def test_agent_notes_key_prefers_agent_id() -> None:
    app = ZeusApp()
    agent = _agent("x", 1, agent_id="agent-1")
    assert app._agent_notes_key(agent) == "agent-1"


def test_has_note_for_agent_checks_stored_text() -> None:
    app = ZeusApp()
    agent = _agent("x", 1, agent_id="agent-1")
    app._agent_notes = {"agent-1": "next: fix parser"}

    assert app._has_note_for_agent(agent) is True


def test_extract_next_note_task_consumes_first_pending_block() -> None:
    note = (
        "- [ ] first line\n"
        "  detail line\n"
        "- [ ] second line\n"
    )

    extracted = _extract_next_note_task(note)
    assert extracted is not None
    message, updated = extracted

    assert message == "first line\n  detail line"
    assert updated.splitlines()[0] == "- [x] first line"
    assert updated.splitlines()[2] == "- [ ] second line"


def test_extract_next_note_task_accepts_brackets_without_inner_space() -> None:
    note = (
        "- [] first line\n"
        "  detail line\n"
        "- [] second line\n"
    )

    extracted = _extract_next_note_task(note)
    assert extracted is not None
    message, updated = extracted

    assert message == "first line\n  detail line"
    assert updated.splitlines()[0] == "- [x] first line"
    assert updated.splitlines()[2] == "- [] second line"


def test_extract_next_note_task_falls_back_to_first_non_empty_line() -> None:
    note = "\nplain next step\n- [x] done item\n"

    extracted = _extract_next_note_task(note)
    assert extracted is not None
    message, updated = extracted

    assert message == "plain next step"
    assert "plain next step" not in updated


def test_action_queue_next_note_task_queues_and_marks_done(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1, agent_id="agent-1")
    app._agent_notes = {
        "agent-1": "- [ ] first line\n  detail line\n- [ ] second line"
    }

    queued: list[tuple[str, str]] = []
    notices: list[str] = []
    renders: list[bool] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(
        app,
        "_queue_text_to_agent",
        lambda target, text: queued.append((target.name, text)),
    )
    monkeypatch.setattr(app, "_save_agent_notes", lambda: None)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: renders.append(True) or True,
    )
    app._interact_visible = False

    app.action_queue_next_note_task()

    assert queued == [("alpha", "first line\n  detail line")]
    assert app._agent_notes["agent-1"].splitlines()[0] == "- [x] first line"
    assert notices[-1] == "Queued next task from notes: alpha"
    assert renders == [True]


def test_action_queue_next_note_task_notifies_when_no_task(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1, agent_id="agent-1")
    app._agent_notes = {"agent-1": "\n  \n"}

    notices: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))

    app.action_queue_next_note_task()

    assert notices[-1] == "No note task found for alpha"
