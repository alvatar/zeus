"""Tests for dashboard agent tasks behavior helpers."""

from zeus.dashboard.app import ZeusApp, _extract_next_task
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


def test_agent_tasks_key_prefers_agent_id() -> None:
    app = ZeusApp()
    agent = _agent("x", 1, agent_id="agent-1")
    assert app._agent_tasks_key(agent) == "agent-1"


def test_has_task_for_agent_checks_stored_text() -> None:
    app = ZeusApp()
    agent = _agent("x", 1, agent_id="agent-1")
    app._agent_tasks = {"agent-1": "next: fix parser"}

    assert app._has_task_for_agent(agent) is True


def test_extract_next_task_consumes_first_pending_block() -> None:
    note = (
        "- [ ] first line\n"
        "  detail line\n"
        "- [ ] second line\n"
    )

    extracted = _extract_next_task(note)
    assert extracted is not None
    message, updated = extracted

    assert message == "first line\n  detail line"
    assert updated.splitlines()[0] == "- [x] first line"
    assert updated.splitlines()[2] == "- [ ] second line"


def test_extract_next_task_accepts_brackets_without_inner_space() -> None:
    note = (
        "- [] first line\n"
        "  detail line\n"
        "- [] second line\n"
    )

    extracted = _extract_next_task(note)
    assert extracted is not None
    message, updated = extracted

    assert message == "first line\n  detail line"
    assert updated.splitlines()[0] == "- [x] first line"
    assert updated.splitlines()[2] == "- [] second line"


def test_extract_next_task_ignores_checkbox_marker_not_at_line_start() -> None:
    note = (
        "paragraph mentions - [ ] inline marker\n"
        "- [ ] real task\n"
    )

    extracted = _extract_next_task(note)
    assert extracted is not None
    message, updated = extracted

    assert message == "real task"
    assert updated.splitlines() == [
        "paragraph mentions - [ ] inline marker",
        "- [x] real task",
    ]


def test_extract_next_task_falls_back_when_only_inline_checkbox_text_exists() -> None:
    note = "paragraph mentions - [ ] inline marker only\n"

    extracted = _extract_next_task(note)
    assert extracted is not None
    message, updated = extracted

    assert message == "paragraph mentions - [ ] inline marker only"
    assert updated == ""


def test_extract_next_task_falls_back_to_first_non_empty_line() -> None:
    note = "\nplain next step\nplain follow-up\n"

    extracted = _extract_next_task(note)
    assert extracted is not None
    message, updated = extracted

    assert message == "plain next step"
    assert "plain next step" not in updated


def test_extract_next_task_does_not_fallback_when_checkbox_headers_exist() -> None:
    note = "\nplain next step\n- [x] done item\n"

    extracted = _extract_next_task(note)

    assert extracted is None


def test_action_queue_next_task_queues_and_marks_done(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1, agent_id="agent-1")
    app.agents = [agent]
    app._agent_tasks = {
        "agent-1": "- [ ] first line\n  detail line\n- [ ] second line"
    }

    queued: list[tuple[str, str, str, str]] = []
    notices: list[str] = []
    renders: list[bool] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(
        app,
        "_enqueue_outbound_agent_message",
        lambda target, text, source_name, source_agent_id="", delivery_mode="followUp": queued.append(
            (target.name, text, source_name, delivery_mode)
        )
        or True,
    )
    monkeypatch.setattr(app, "_drain_message_queue", lambda: None)
    monkeypatch.setattr(app, "_save_agent_tasks", lambda: None)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: renders.append(True) or True,
    )
    app._interact_visible = False

    app.action_queue_next_task()

    assert queued == [("alpha", "first line\n  detail line", "oracle", "followUp")]
    assert app._agent_tasks["agent-1"].splitlines()[0] == "- [x] first line"
    assert notices[-1] == "Queued next task: alpha"
    assert renders == [True]


def test_action_queue_next_task_keeps_task_when_enqueue_fails(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1, agent_id="agent-1")
    app.agents = [agent]
    original = "- [ ] first line\n  detail line\n- [ ] second line"
    app._agent_tasks = {"agent-1": original}

    notices: list[str] = []
    saves: list[bool] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(
        app,
        "_enqueue_outbound_agent_message",
        lambda target, text, source_name, source_agent_id="", delivery_mode="followUp": False,
    )
    monkeypatch.setattr(app, "notify_force", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "_save_agent_tasks", lambda: saves.append(True))

    app.action_queue_next_task()

    assert app._agent_tasks["agent-1"] == original
    assert notices[-1] == "Failed to queue message: alpha"
    assert saves == []


def test_action_queue_next_task_notifies_when_no_task(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1, agent_id="agent-1")
    app._agent_tasks = {"agent-1": "\n  \n"}

    notices: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))

    app.action_queue_next_task()

    assert notices[-1] == "No task found for alpha"


def test_action_queue_next_task_ignores_plain_lines_when_only_done_headers_remain(
    monkeypatch,
) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1, agent_id="agent-1")
    app._agent_tasks = {
        "agent-1": "legacy plain line\n- [x] done one\n- [x] done two"
    }

    notices: list[str] = []
    attempted: list[bool] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(
        app,
        "_enqueue_outbound_agent_message",
        lambda *args, **kwargs: attempted.append(True) or True,
    )

    app.action_queue_next_task()

    assert notices[-1] == "No task found for alpha"
    assert attempted == []


def test_action_clear_done_tasks_clears_done_entries(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1, agent_id="agent-1")
    app._agent_tasks = {
        "agent-1": "- [x] done one\n- [ ] keep this"
    }

    notices: list[str] = []
    saves: list[bool] = []
    renders: list[bool] = []

    monkeypatch.setattr(app, "_has_modal_open", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "_save_agent_tasks", lambda: saves.append(True))
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: renders.append(True) or True,
    )
    app._interact_visible = False

    app.action_clear_done_tasks()

    assert app._agent_tasks["agent-1"] == "- [ ] keep this"
    assert notices[-1] == "Cleared 1 done task: alpha"
    assert saves == [True]
    assert renders == [True]


def test_action_clear_done_tasks_notifies_when_none_found(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1, agent_id="agent-1")
    app._agent_tasks = {"agent-1": "- [ ] keep this"}

    notices: list[str] = []
    saves: list[bool] = []

    monkeypatch.setattr(app, "_has_modal_open", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "_save_agent_tasks", lambda: saves.append(True))
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))

    app.action_clear_done_tasks()

    assert notices[-1] == "No done tasks to clear for alpha"
    assert saves == []
