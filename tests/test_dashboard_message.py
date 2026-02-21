"""Tests for table-triggered Hippeus message dialog helpers."""

import inspect
from types import SimpleNamespace

from textual.widgets import DataTable

from zeus.config import MESSAGE_TMP_DIR
from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import (
    AgentMessageScreen,
    PremadeMessageScreen,
    LastSentMessageScreen,
    ExpandedOutputScreen,
)
from zeus.models import AgentWindow
from tests.helpers import capture_kitty_cmd, capture_notify


def _agent(
    name: str,
    kitty_id: int,
    socket: str = "/tmp/kitty-1",
    agent_id: str = "",
) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket=socket,
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        agent_id=agent_id,
    )


def _new_app() -> ZeusApp:
    app = ZeusApp()
    app._agent_dependencies = {}
    app._agent_priorities = {}
    app._agent_tasks = {}
    app._agent_message_drafts = {}
    app._pending_polemarch_bootstraps = {}
    return app


class _DummyKeyEvent:
    def __init__(self, key: str) -> None:
        self.key = key
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


class _DummyInput:
    def __init__(self) -> None:
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class _DummyInteractInput:
    def __init__(self, text: str) -> None:
        self.text = text
        self.styles = SimpleNamespace(height=3)

    def clear(self) -> None:
        self.text = ""


class _DummyRichLog:
    def __init__(self) -> None:
        self.scrolled_to_end = False
        self.writes: list[str] = []
        self.can_focus = False
        self.focused = False

    def clear(self) -> None:
        self.writes = []

    def write(self, value) -> None:  # noqa: ANN001
        plain = getattr(value, "plain", None)
        if isinstance(plain, str):
            self.writes.append(plain)
            return
        self.writes.append(str(value))

    def focus(self) -> None:
        self.focused = True

    def scroll_up(self, animate: bool = False) -> None:
        return

    def scroll_down(self, animate: bool = False) -> None:
        return

    def scroll_page_up(self, animate: bool = False) -> None:
        return

    def scroll_page_down(self, animate: bool = False) -> None:
        return

    def scroll_home(self, animate: bool = False) -> None:
        return

    def scroll_end(self, animate: bool = False) -> None:
        self.scrolled_to_end = True


class _DummyLabel:
    def __init__(self) -> None:
        self.text = ""

    def update(self, text: str) -> None:
        self.text = text


class _ScreenStackAppStub:
    def __init__(self, stack: list[object]) -> None:
        self.screen_stack = stack


class _DummyRegion:
    def __init__(self, contains_result: bool) -> None:
        self.contains_result = contains_result

    def contains(self, _x: int, _y: int) -> bool:
        return self.contains_result


class _DummyDialog:
    def __init__(self, contains_result: bool) -> None:
        self.region = _DummyRegion(contains_result)


class _DummyMouseEvent:
    def __init__(self, screen_x: int = 1, screen_y: int = 1) -> None:
        self.screen_x = screen_x
        self.screen_y = screen_y
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


def test_action_agent_message_pushes_message_screen(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_agent_message()

    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, AgentMessageScreen)
    assert screen.agent is agent


def test_action_agent_message_restores_saved_draft(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)
    app._agent_message_drafts[app._agent_message_draft_key(agent)] = "draft body"

    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_agent_message()

    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, AgentMessageScreen)
    assert screen.draft == "draft body"


def test_action_premade_message_pushes_preset_screen(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_premade_message()

    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, PremadeMessageScreen)
    assert screen.agent is agent


def test_action_premade_message_requires_selected_agent(monkeypatch) -> None:
    app = _new_app()
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: None)

    app.action_premade_message()

    assert notices[-1] == "Select a Hippeus row to message"


def test_action_message_history_pushes_history_view_screen(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1, agent_id="agent-1")

    pushed: list[object] = []
    requested_keys: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr(
        "zeus.dashboard.app.load_history",
        lambda key: requested_keys.append(key) or ["older", "latest payload"],
    )

    app.action_message_history()

    assert requested_keys == ["agent:alpha"]
    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, LastSentMessageScreen)
    assert screen.agent is agent
    assert screen.history_entries == ["older", "latest payload"]


def test_action_message_history_requires_selected_agent(monkeypatch) -> None:
    app = _new_app()
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: None)

    app.action_message_history()

    assert notices[-1] == "Select a Hippeus row to show history"


def test_action_message_history_opens_placeholder_when_no_message(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1, agent_id="agent-1")
    notices = capture_notify(app, monkeypatch)
    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr("zeus.dashboard.app.load_history", lambda _key: [])

    app.action_message_history()

    assert notices == []
    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, LastSentMessageScreen)
    assert screen.history_entries == ["(no sent message recorded yet)"]


def test_history_screen_up_down_navigates_from_latest_to_previous(monkeypatch) -> None:
    screen = LastSentMessageScreen(_agent("alpha", 1), ["first", "second", "third"])
    body = _DummyRichLog()
    pos = _DummyLabel()

    def _query_one(selector: str, _cls=None):
        if selector == "#last-sent-message-body":
            return body
        if selector == "#last-sent-message-position":
            return pos
        raise AssertionError(selector)

    monkeypatch.setattr(screen, "query_one", _query_one)

    screen.on_mount()
    assert body.writes == ["third"]
    assert "latest" in pos.text
    assert "1/3" in pos.text

    screen.action_older()
    assert body.writes == ["second"]
    assert "previous" in pos.text
    assert "2/3" in pos.text

    screen.action_older()
    assert body.writes == ["first"]
    assert "previous-2" in pos.text
    assert "3/3" in pos.text

    screen.action_newer()
    assert body.writes == ["second"]
    assert "2/3" in pos.text


def test_history_screen_includes_yank_binding() -> None:
    bindings = {binding.key: binding.action for binding in LastSentMessageScreen.BINDINGS}

    assert bindings["y"] == "yank"


def test_history_screen_hint_mentions_yank_shortcut() -> None:
    source = inspect.getsource(LastSentMessageScreen.compose)

    assert "(↑ older | ↓ newer | y yank | Esc close)" in source


def test_history_screen_yank_copies_current_entry(monkeypatch) -> None:
    screen = LastSentMessageScreen(_agent("alpha", 1), ["first", "second", "third"])

    copied: list[str] = []
    notices: list[str] = []

    class _ZeusStub:
        def _copy_text_to_system_clipboard(self, text: str) -> bool:
            copied.append(text)
            return True

        def notify(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

        def notify_force(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

    monkeypatch.setattr(LastSentMessageScreen, "zeus", property(lambda self: _ZeusStub()))

    screen.history_offset = 1
    screen.action_yank()

    assert copied == ["second"]
    assert notices[-1] == "Yanked history: alpha"


def test_history_screen_yank_notifies_when_clipboard_unavailable(monkeypatch) -> None:
    screen = LastSentMessageScreen(_agent("alpha", 1), ["entry"])

    notices: list[str] = []

    class _ZeusStub:
        def _copy_text_to_system_clipboard(self, _text: str) -> bool:
            return False

        def notify(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

        def notify_force(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

    monkeypatch.setattr(LastSentMessageScreen, "zeus", property(lambda self: _ZeusStub()))

    screen.action_yank()

    assert notices[-1] == "Could not copy history entry to clipboard (wl-copy)"


def test_action_expand_output_pushes_expanded_output_screen(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_expand_output()

    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, ExpandedOutputScreen)
    assert screen.agent is agent


def test_action_expand_output_requires_selected_agent(monkeypatch) -> None:
    app = _new_app()
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: None)

    app.action_expand_output()

    assert notices[-1] == "Select a Hippeus row to expand output"


def test_should_ignore_table_action_allows_expanded_output_modal(monkeypatch) -> None:
    app = _new_app()
    expanded = ExpandedOutputScreen(_agent("alpha", 1))

    monkeypatch.setattr(app, "_is_text_input_focused", lambda: False)
    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(ZeusApp, "screen", property(lambda self: expanded))

    assert app._should_ignore_table_action() is False

    message_modal = AgentMessageScreen(_agent("alpha", 1))
    monkeypatch.setattr(ZeusApp, "screen", property(lambda self: message_modal))

    assert app._should_ignore_table_action() is True


def test_expanded_output_apply_scrolls_to_bottom(monkeypatch) -> None:
    screen = ExpandedOutputScreen(_agent("alpha", 1))
    stream = _DummyRichLog()

    monkeypatch.setattr(ExpandedOutputScreen, "is_attached", property(lambda self: True))
    monkeypatch.setattr(screen, "query_one", lambda _selector, _cls=None: stream)

    screen._apply_output("line 1\nline 2\n")

    assert stream.scrolled_to_end is True


def test_expanded_output_empty_state_has_no_leading_margin(monkeypatch) -> None:
    screen = ExpandedOutputScreen(_agent("alpha", 1))
    stream = _DummyRichLog()

    monkeypatch.setattr(ExpandedOutputScreen, "is_attached", property(lambda self: True))
    monkeypatch.setattr(screen, "query_one", lambda _selector, _cls=None: stream)

    screen._apply_output("\n\n")

    assert stream.writes == ["[alpha] (no output)"]


def test_expanded_output_message_opens_compact_dialog(monkeypatch) -> None:
    agent = _agent("alpha", 1)
    screen = ExpandedOutputScreen(agent)
    pushed: list[object] = []

    class _ZeusStub:
        def _message_draft_for_agent(self, _agent: AgentWindow) -> str:
            return "draft"

        def push_screen(self, modal: object) -> None:
            pushed.append(modal)

    monkeypatch.setattr(ExpandedOutputScreen, "zeus", property(lambda self: _ZeusStub()))

    screen.action_message()

    assert len(pushed) == 1
    modal = pushed[0]
    assert isinstance(modal, AgentMessageScreen)
    assert modal.compact_for_expanded_output is True


def test_expanded_output_go_ahead_closes_screen_and_dispatches_action(monkeypatch) -> None:
    agent = _agent("alpha", 1)
    screen = ExpandedOutputScreen(agent)

    calls: list[str] = []

    class _ZeusStub:
        def action_go_ahead(self) -> None:
            calls.append("go")

    dismissed: list[bool] = []
    monkeypatch.setattr(ExpandedOutputScreen, "zeus", property(lambda self: _ZeusStub()))
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    screen.action_go_ahead()

    assert dismissed == [True]
    assert calls == ["go"]


def test_message_screen_mouse_scroll_forwards_to_expanded_output_when_outside_dialog(
    monkeypatch,
) -> None:
    agent = _agent("alpha", 1)
    message = AgentMessageScreen(agent)
    expanded = ExpandedOutputScreen(agent)
    calls: list[str] = []

    monkeypatch.setattr(
        expanded,
        "_scroll_stream_by_key",
        lambda key: calls.append(key) or True,
    )
    app_stub = _ScreenStackAppStub([expanded, message])
    monkeypatch.setattr(AgentMessageScreen, "app", property(lambda self: app_stub))
    monkeypatch.setattr(message, "query_one", lambda _selector, _cls=None: _DummyDialog(False))

    up_event = _DummyMouseEvent()
    down_event = _DummyMouseEvent()
    message.on_mouse_scroll_up(up_event)  # type: ignore[arg-type]
    message.on_mouse_scroll_down(down_event)  # type: ignore[arg-type]

    assert calls == ["up", "down"]
    assert up_event.prevented is True
    assert up_event.stopped is True
    assert down_event.prevented is True
    assert down_event.stopped is True


def test_message_screen_mouse_scroll_does_not_forward_inside_dialog(monkeypatch) -> None:
    agent = _agent("alpha", 1)
    message = AgentMessageScreen(agent)
    expanded = ExpandedOutputScreen(agent)
    calls: list[str] = []

    monkeypatch.setattr(
        expanded,
        "_scroll_stream_by_key",
        lambda key: calls.append(key) or True,
    )
    app_stub = _ScreenStackAppStub([expanded, message])
    monkeypatch.setattr(AgentMessageScreen, "app", property(lambda self: app_stub))
    monkeypatch.setattr(message, "query_one", lambda _selector, _cls=None: _DummyDialog(True))

    event = _DummyMouseEvent()
    message.on_mouse_scroll_up(event)  # type: ignore[arg-type]

    assert calls == []
    assert event.prevented is False
    assert event.stopped is False


def test_action_go_ahead_queues_fixed_message_to_selected_agent(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)
    app.agents = [agent]

    sent = capture_kitty_cmd(monkeypatch)
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)

    app.action_go_ahead()

    assert sent == [
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "go ahead")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x1b[13;3u")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x03")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x15")),
    ]
    assert notices[-1] == "Queued go ahead: alpha"


def test_action_go_ahead_requires_selected_agent(monkeypatch) -> None:
    app = _new_app()
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: None)

    app.action_go_ahead()

    assert notices[-1] == "Select a Hippeus row to queue go ahead"


def test_action_go_ahead_unpauses_paused_target_and_rejects_blocked_target(monkeypatch) -> None:
    app = _new_app()
    paused = _agent("paused", 1)
    blocked = _agent("blocked", 2)
    blocker = _agent("blocker", 3)

    app.agents = [paused, blocked, blocker]
    app._agent_priorities[paused.name] = 4
    app._agent_dependencies[app._agent_dependency_key(blocked)] = app._agent_dependency_key(
        blocker
    )

    sent = capture_kitty_cmd(monkeypatch)
    notices = capture_notify(app, monkeypatch)

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)

    monkeypatch.setattr(app, "_get_selected_agent", lambda: paused)
    app.action_go_ahead()
    assert notices[-1] == "Queued go ahead: paused"
    assert app._agent_priorities.get(paused.name, 3) == 3

    monkeypatch.setattr(app, "_get_selected_agent", lambda: blocked)
    app.action_go_ahead()
    assert notices[-1] == "Hippeus is BLOCKED by dependency; input disabled"

    assert sent[:4] == [
        (paused.socket, ("send-text", "--match", f"id:{paused.kitty_id}", "go ahead")),
        (paused.socket, ("send-text", "--match", f"id:{paused.kitty_id}", "\x1b[13;3u")),
        (paused.socket, ("send-text", "--match", f"id:{paused.kitty_id}", "\x03")),
        (paused.socket, ("send-text", "--match", f"id:{paused.kitty_id}", "\x15")),
    ]


def test_schedule_polemarch_bootstrap_delivers_when_agent_visible(monkeypatch) -> None:
    app = _new_app()
    polemarch = _agent("planner", 1, agent_id="polemarch-1")
    app.agents = [polemarch]

    sent = capture_kitty_cmd(monkeypatch)
    notices = capture_notify(app, monkeypatch)

    app.schedule_polemarch_bootstrap("polemarch-1", "planner")
    app._deliver_pending_polemarch_bootstraps()

    assert sent
    message = sent[0][1][-1]
    assert isinstance(message, str)
    assert "You are the agent named planner." in message
    assert "A polemarch is a coordinator role in Zeus, not your personal name." in message
    assert "The Oracle (the user) will send your concrete task in the following message." in message
    assert "tmux new-session -d -s \"$SESSION\" -c \"$PWD\"" in message
    assert "Use ONLY the canonical tool: zeus-msg send." in message
    assert f"zeus-msg send --to phalanx --file {MESSAGE_TMP_DIR}/zeus-msg-<uuid>.md" in message
    assert "DO NOT poll message-tmp files as a communication protocol." in message
    assert "@zeus_agent \"$HOPLITE_ID\"" in message
    assert "@zeus_role \"hoplite\"" in message
    assert notices[-1] == "Polemarch bootstrap sent: planner"
    assert app._pending_polemarch_bootstraps == {}


def test_pending_polemarch_bootstrap_waits_until_agent_visible(monkeypatch) -> None:
    app = _new_app()

    sent = capture_kitty_cmd(monkeypatch)

    app.schedule_polemarch_bootstrap("polemarch-1", "planner")
    app._deliver_pending_polemarch_bootstraps()

    assert sent == []
    assert app._pending_polemarch_bootstraps == {"polemarch-1": "planner"}


def test_enter_on_table_opens_message_dialog_when_input_hidden(monkeypatch) -> None:
    app = _new_app()
    table = DataTable()
    event = _DummyKeyEvent("enter")

    called: list[bool] = []
    monkeypatch.setattr(ZeusApp, "focused", property(lambda self: table))
    monkeypatch.setattr(app, "_dismiss_splash", lambda: False)
    monkeypatch.setattr(app, "_dismiss_celebration", lambda: False)
    monkeypatch.setattr(app, "action_agent_message", lambda: called.append(True))

    app._show_interact_input = False
    app._interact_visible = True

    app.on_key(event)  # type: ignore[arg-type]

    assert called == [True]
    assert event.prevented is True
    assert event.stopped is True


def test_enter_on_table_focuses_input_when_input_visible(monkeypatch) -> None:
    app = _new_app()
    table = DataTable()
    event = _DummyKeyEvent("enter")
    interact_input = _DummyInput()

    called: list[bool] = []
    monkeypatch.setattr(ZeusApp, "focused", property(lambda self: table))
    monkeypatch.setattr(app, "_dismiss_splash", lambda: False)
    monkeypatch.setattr(app, "_dismiss_celebration", lambda: False)
    monkeypatch.setattr(app, "action_agent_message", lambda: called.append(True))
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: interact_input)

    app._show_interact_input = True
    app._interact_visible = True

    app.on_key(event)  # type: ignore[arg-type]

    assert interact_input.focused is True
    assert called == []
    assert event.prevented is True
    assert event.stopped is True


def test_do_save_agent_message_draft_roundtrip() -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    app.do_save_agent_message_draft(agent, "draft body")
    assert app._message_draft_for_agent(agent) == "draft body"

    app.do_save_agent_message_draft(agent, "")
    assert app._message_draft_for_agent(agent) == ""


def test_do_send_agent_message_enqueues_steer_delivery(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1, agent_id="a" * 32)
    app.agents = [agent]
    app._agent_message_drafts[app._agent_message_draft_key(agent)] = "draft body"

    calls: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        app,
        "_enqueue_outbound_agent_message",
        lambda target, message, source_name, source_agent_id="", delivery_mode="followUp": calls.append(
            (target.name, message, source_name, delivery_mode)
        )
        or True,
    )

    drains: list[bool] = []
    monkeypatch.setattr(app, "_drain_message_queue", lambda: drains.append(True))

    ok = app.do_send_agent_message(agent, "hello")

    assert ok is True
    assert calls == [("alpha", "hello", "oracle", "steer")]
    assert drains == [True]
    assert app._agent_message_drafts == {}


def test_do_queue_agent_message_enqueues_followup_delivery(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1, agent_id="a" * 32)
    app.agents = [agent]
    app._agent_message_drafts[app._agent_message_draft_key(agent)] = "draft body"

    calls: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        app,
        "_enqueue_outbound_agent_message",
        lambda target, message, source_name, source_agent_id="", delivery_mode="followUp": calls.append(
            (target.name, message, source_name, delivery_mode)
        )
        or True,
    )

    drains: list[bool] = []
    monkeypatch.setattr(app, "_drain_message_queue", lambda: drains.append(True))

    ok = app.do_queue_agent_message(agent, "hello")

    assert ok is True
    assert calls == [("alpha", "hello", "oracle", "followUp")]
    assert drains == [True]
    assert app._agent_message_drafts == {}


def test_do_send_agent_message_reports_failure_and_keeps_draft(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1, agent_id="a" * 32)
    app.agents = [agent]
    draft_key = app._agent_message_draft_key(agent)
    app._agent_message_drafts[draft_key] = "draft body"

    monkeypatch.setattr(
        app,
        "_enqueue_outbound_agent_message",
        lambda _target, _message, source_name, source_agent_id="", delivery_mode="followUp": False,
    )

    notices: list[str] = []
    monkeypatch.setattr(app, "notify_force", lambda message, timeout=3: notices.append(message))

    ok = app.do_send_agent_message(agent, "hello")

    assert ok is False
    assert app._agent_message_drafts[draft_key] == "draft body"
    assert notices[-1] == "Failed to send message: alpha"


def test_do_queue_agent_message_reports_failure_and_keeps_draft(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1, agent_id="a" * 32)
    app.agents = [agent]
    draft_key = app._agent_message_draft_key(agent)
    app._agent_message_drafts[draft_key] = "draft body"

    monkeypatch.setattr(
        app,
        "_enqueue_outbound_agent_message",
        lambda _target, _message, source_name, source_agent_id="", delivery_mode="followUp": False,
    )

    notices: list[str] = []
    monkeypatch.setattr(app, "notify_force", lambda message, timeout=3: notices.append(message))

    ok = app.do_queue_agent_message(agent, "hello")

    assert ok is False
    assert app._agent_message_drafts[draft_key] == "draft body"
    assert notices[-1] == "Failed to queue message: alpha"


def test_dispatch_tmux_text_queue_sends_followup_then_clear(monkeypatch) -> None:
    app = _new_app()
    calls: list[list[str]] = []

    class _Result:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    monkeypatch.setattr(
        "zeus.dashboard.app.subprocess.run",
        lambda cmd, capture_output=True, timeout=3: calls.append(cmd) or _Result(),
    )

    ok = app._dispatch_tmux_text("hoplite-a", "hello", queue=True)

    assert ok is True
    assert calls == [
        ["tmux", "send-keys", "-t", "hoplite-a", "hello"],
        ["tmux", "send-keys", "-t", "hoplite-a", "M-Enter"],
        ["tmux", "send-keys", "-t", "hoplite-a", "C-c"],
    ]


def test_dispatch_tmux_text_send_uses_enter_only(monkeypatch) -> None:
    app = _new_app()
    calls: list[list[str]] = []

    class _Result:
        def __init__(self, returncode: int = 0) -> None:
            self.returncode = returncode

    monkeypatch.setattr(
        "zeus.dashboard.app.subprocess.run",
        lambda cmd, capture_output=True, timeout=3: calls.append(cmd) or _Result(),
    )

    ok = app._dispatch_tmux_text("hoplite-a", "hello", queue=False)

    assert ok is True
    assert calls == [
        ["tmux", "send-keys", "-t", "hoplite-a", "hello"],
        ["tmux", "send-keys", "-t", "hoplite-a", "Enter"],
    ]


def test_action_send_interact_unpauses_paused_target(monkeypatch) -> None:
    app = _new_app()
    paused = _agent("paused", 1)
    app.agents = [paused]
    app._agent_priorities[paused.name] = 4
    app._interact_visible = True
    app._show_interact_input = True
    app._interact_agent_key = app._agent_key(paused)

    ta = _DummyInteractInput("hello")
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: ta)
    monkeypatch.setattr(app, "_append_interact_history", lambda _text: None)

    sent = capture_kitty_cmd(monkeypatch)
    history_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.append_history",
        lambda key, text: history_calls.append((key, text)) or [text],
    )

    app.action_send_interact()

    assert app._agent_priorities.get(paused.name, 3) == 3
    assert sent == [
        (paused.socket, ("send-text", "--match", f"id:{paused.kitty_id}", "hello\r")),
    ]
    assert history_calls == [("agent:paused", "hello")]


def test_action_queue_interact_failed_dispatch_keeps_input(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)
    app.agents = [agent]
    app._interact_visible = True
    app._show_interact_input = True
    app._interact_agent_key = app._agent_key(agent)

    ta = _DummyInteractInput("hello")
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: ta)
    monkeypatch.setattr(app, "_has_modal_open", lambda: False)
    monkeypatch.setattr(app, "_current_interact_block_reason", lambda: None)
    monkeypatch.setattr(app, "_append_interact_history", lambda _text: None)
    monkeypatch.setattr(app, "_interact_target_agent", lambda: agent)
    monkeypatch.setattr(app, "_resume_agent_if_paused", lambda _agent: False)
    monkeypatch.setattr(app, "_get_agent_by_key", lambda _key: agent)
    monkeypatch.setattr(app, "_queue_text_to_agent_interact", lambda _agent, _text: False)

    resets: list[bool] = []
    monkeypatch.setattr(app, "_reset_history_nav", lambda: resets.append(True))

    notices: list[str] = []
    monkeypatch.setattr(app, "notify_force", lambda message, timeout=3: notices.append(message))

    app.action_queue_interact()

    assert ta.text == "hello"
    assert resets == []
    assert notices[-1] == "Failed to queue message: alpha"


def test_resume_agent_if_paused_refreshes_ui_when_running(monkeypatch) -> None:
    app = _new_app()
    paused = _agent("paused", 1)
    app.agents = [paused]
    app._agent_priorities[paused.name] = 4
    app._interact_visible = True

    saves: list[bool] = []
    renders: list[bool] = []
    refreshes: list[bool] = []

    monkeypatch.setattr(app, "_save_priorities", lambda: saves.append(True))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: renders.append(True),
    )
    monkeypatch.setattr(app, "_refresh_interact_panel", lambda: refreshes.append(True))
    monkeypatch.setattr(ZeusApp, "is_running", property(lambda _self: True))

    assert app._resume_agent_if_paused(paused) is True
    assert app._agent_priorities.get(paused.name, 3) == 3
    assert saves == [True]
    assert renders == [True]
    assert refreshes == [True]


def test_message_dialog_send_unpauses_paused_target_and_rejects_blocked_target(monkeypatch) -> None:
    app = _new_app()
    source = _agent("source", 1, agent_id="1" * 32)
    paused = _agent("paused", 2, agent_id="2" * 32)
    blocked = _agent("blocked", 3, agent_id="3" * 32)
    blocker = _agent("blocker", 4, agent_id="4" * 32)

    app.agents = [source, paused, blocked, blocker]
    app._agent_priorities[paused.name] = 4
    app._agent_dependencies[app._agent_dependency_key(blocked)] = app._agent_dependency_key(
        blocker
    )

    notices = capture_notify(app, monkeypatch)

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        app,
        "_enqueue_outbound_agent_message",
        lambda target, message, source_name, source_agent_id="", delivery_mode="followUp": calls.append(
            (target.name, delivery_mode)
        )
        or True,
    )
    monkeypatch.setattr(app, "_drain_message_queue", lambda: None)

    assert app.do_send_agent_message(paused, "hello") is True
    assert app._agent_priorities.get(paused.name, 3) == 3

    assert app.do_queue_agent_message(blocked, "hello") is False
    assert notices[-1] == "Hippeus is BLOCKED by dependency; input disabled"

    assert calls == [("paused", "steer")]


def test_do_add_agent_message_task_appends_checkbox_item(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)
    app._agent_tasks[app._agent_tasks_key(agent)] = "existing line"
    app._agent_message_drafts[app._agent_message_draft_key(agent)] = "draft body"

    notices = capture_notify(app, monkeypatch)
    saves: list[bool] = []
    renders: list[bool] = []

    monkeypatch.setattr(app, "_save_agent_tasks", lambda: saves.append(True))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: renders.append(True) or True,
    )
    app._interact_visible = False

    ok = app.do_add_agent_message_task(agent, "new task")

    assert ok is True
    key = app._agent_tasks_key(agent)
    assert app._agent_tasks[key] == "existing line\n- [ ] new task"
    assert notices[-1] == "Added task: alpha"
    assert saves == [True]
    assert renders == [True]
    assert app._agent_message_drafts == {}


def test_do_prepend_agent_message_task_inserts_before_existing(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)
    app._agent_tasks[app._agent_tasks_key(agent)] = "existing line"
    app._agent_message_drafts[app._agent_message_draft_key(agent)] = "draft body"

    notices = capture_notify(app, monkeypatch)
    saves: list[bool] = []
    renders: list[bool] = []

    monkeypatch.setattr(app, "_save_agent_tasks", lambda: saves.append(True))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: renders.append(True) or True,
    )
    app._interact_visible = False

    ok = app.do_prepend_agent_message_task(agent, "new task")

    assert ok is True
    key = app._agent_tasks_key(agent)
    assert app._agent_tasks[key] == "- [ ] new task\nexisting line"
    assert notices[-1] == "Added task at start: alpha"
    assert saves == [True]
    assert renders == [True]
    assert app._agent_message_drafts == {}


def test_do_add_agent_message_task_keeps_multiline_payload(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    monkeypatch.setattr(app, "_save_agent_tasks", lambda: None)
    monkeypatch.setattr(app, "_render_agent_table_and_status", lambda: True)
    app._interact_visible = False

    ok = app.do_add_agent_message_task(agent, "first line\n  detail line")

    assert ok is True
    key = app._agent_tasks_key(agent)
    assert app._agent_tasks[key] == "- [ ] first line\n  detail line"


def test_do_prepend_agent_message_task_keeps_multiline_payload(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    monkeypatch.setattr(app, "_save_agent_tasks", lambda: None)
    monkeypatch.setattr(app, "_render_agent_table_and_status", lambda: True)
    app._interact_visible = False

    ok = app.do_prepend_agent_message_task(agent, "first line\n  detail line")

    assert ok is True
    key = app._agent_tasks_key(agent)
    assert app._agent_tasks[key] == "- [ ] first line\n  detail line"


def test_do_add_agent_message_task_rejects_empty_text(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    saves: list[bool] = []
    monkeypatch.setattr(app, "_save_agent_tasks", lambda: saves.append(True))

    ok = app.do_add_agent_message_task(agent, "   \n\n")

    assert ok is False
    assert saves == []


def test_do_prepend_agent_message_task_rejects_empty_text(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    saves: list[bool] = []
    monkeypatch.setattr(app, "_save_agent_tasks", lambda: saves.append(True))

    ok = app.do_prepend_agent_message_task(agent, "   \n\n")

    assert ok is False
    assert saves == []


def test_message_screen_escape_binding_saves_via_cancel_action() -> None:
    bindings = {binding.key: binding.action for binding in AgentMessageScreen.BINDINGS}
    assert bindings["escape"] == "cancel"
    assert "pageup" not in bindings
    assert "pagedown" not in bindings
    assert "home" not in bindings
    assert "end" not in bindings
    assert "alt+up" not in bindings
    assert "alt+down" not in bindings


def test_app_ctrl_s_routes_to_message_modal_when_open(monkeypatch) -> None:
    app = _new_app()
    modal = AgentMessageScreen(_agent("alpha", 1))

    called: list[bool] = []
    monkeypatch.setattr(modal, "action_send", lambda: called.append(True))
    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(ZeusApp, "screen", property(lambda self: modal))

    app.action_send_interact()

    assert called == [True]


def test_app_ctrl_w_routes_to_message_modal_when_open(monkeypatch) -> None:
    app = _new_app()
    modal = AgentMessageScreen(_agent("alpha", 1))

    called: list[bool] = []
    monkeypatch.setattr(modal, "action_queue", lambda: called.append(True))
    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(ZeusApp, "screen", property(lambda self: modal))

    app.action_queue_interact()

    assert called == [True]


def test_app_ctrl_s_routes_to_premade_message_modal_when_open(monkeypatch) -> None:
    app = _new_app()
    modal = PremadeMessageScreen(
        _agent("alpha", 1),
        templates=[("Self-review", "Review your output against your own claims again")],
    )

    called: list[bool] = []
    monkeypatch.setattr(modal, "action_send", lambda: called.append(True))
    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(ZeusApp, "screen", property(lambda self: modal))

    app.action_send_interact()

    assert called == [True]


def test_app_ctrl_w_routes_to_premade_message_modal_when_open(monkeypatch) -> None:
    app = _new_app()
    modal = PremadeMessageScreen(
        _agent("alpha", 1),
        templates=[("Self-review", "Review your output against your own claims again")],
    )

    called: list[bool] = []
    monkeypatch.setattr(modal, "action_queue", lambda: called.append(True))
    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(ZeusApp, "screen", property(lambda self: modal))

    app.action_queue_interact()

    assert called == [True]
