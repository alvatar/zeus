"""Tests for dashboard CSS composition helpers."""

from zeus.dashboard import css


def test_button_row_css_renders_expected_rules() -> None:
    block = css._button_row_css(
        "demo-buttons",
        align="center middle",
        row_margin="1 0 0 0",
        button_margin="0 1",
        width="100%",
    )

    assert "#demo-buttons {" in block
    assert "width: 100%;" in block
    assert "align: center middle;" in block
    assert "margin: 1 0 0 0;" in block
    assert "#demo-buttons Button {" in block
    assert "margin: 0 1;" in block


def test_dialog_css_contains_inlined_button_rows() -> None:
    assert "#broadcast-buttons {" in css.BROADCAST_CONFIRM_CSS
    assert "#broadcast-buttons Button {" in css.BROADCAST_CONFIRM_CSS
    assert "#direct-buttons {" in css.DIRECT_MESSAGE_CONFIRM_CSS
    assert "#confirm-kill-buttons {" in css.CONFIRM_KILL_CSS


def test_app_css_can_hide_interact_input() -> None:
    assert "#interact-input.hidden {" in css.APP_CSS
    assert "display: none;" in css.APP_CSS


def test_dependency_dialog_css_has_expected_spacing() -> None:
    assert "max-height: 24;" in css.DEPENDENCY_SELECT_CSS
    assert "#dependency-select-buttons {" in css.DEPENDENCY_SELECT_CSS
    assert "margin: 1 0 0 0;" in css.DEPENDENCY_SELECT_CSS


def test_notes_dialog_buttons_include_left_clear_done_layout() -> None:
    assert "#agent-tasks-buttons-spacer {" in css.AGENT_TASKS_CSS
    assert "width: 1fr;" in css.AGENT_TASKS_CSS
    assert "#agent-tasks-buttons {" in css.AGENT_TASKS_CSS
    assert "align: left middle;" in css.AGENT_TASKS_CSS


def test_message_dialog_css_matches_notes_shell() -> None:
    assert "#agent-message-dialog {" in css.AGENT_MESSAGE_CSS
    assert "width: 110;" in css.AGENT_MESSAGE_CSS
    assert "max-height: 40;" in css.AGENT_MESSAGE_CSS
    assert "#agent-message-title-row {" in css.AGENT_MESSAGE_CSS
    assert "#agent-message-shortcuts-hint {" in css.AGENT_MESSAGE_CSS
    assert "content-align: right middle;" in css.AGENT_MESSAGE_CSS
    assert "#agent-message-input {" in css.AGENT_MESSAGE_CSS
    assert "#agent-message-buttons {" in css.AGENT_MESSAGE_CSS
    assert "align: left middle;" in css.AGENT_MESSAGE_CSS
    assert "margin: 0 2 0 0;" in css.AGENT_MESSAGE_CSS
