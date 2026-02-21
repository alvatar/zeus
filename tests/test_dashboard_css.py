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
    assert "#confirm-promote-buttons {" in css.CONFIRM_PROMOTE_CSS
    assert "#aegis-config-buttons {" in css.AEGIS_CONFIG_CSS
    assert "#snapshot-save-buttons {" in css.SNAPSHOT_SAVE_CSS
    assert "#snapshot-save-close-all {" in css.SNAPSHOT_SAVE_CSS
    assert "color: #cccccc;" in css.SNAPSHOT_SAVE_CSS
    assert "#snapshot-restore-buttons {" in css.SNAPSHOT_RESTORE_CSS


def test_confirm_promote_css_uses_distinct_border_color() -> None:
    assert "border: thick #ff3366;" in css.CONFIRM_KILL_CSS
    assert "border: thick #ffb000;" in css.CONFIRM_PROMOTE_CSS


def test_app_css_can_hide_interact_input() -> None:
    assert "#interact-input.hidden {" in css.APP_CSS
    assert "display: none;" in css.APP_CSS


def test_agent_table_hides_horizontal_scrollbar() -> None:
    assert "#agent-table {" in css.APP_CSS
    assert "scrollbar-size: 0 1;" in css.APP_CSS


def test_modal_dialog_screens_use_transparent_overlay_background() -> None:
    modal_css_blocks = [
        css.NEW_AGENT_CSS,
        css.AGENT_TASKS_CSS,
        css.AGENT_MESSAGE_CSS,
        css.PREMADE_MESSAGE_CSS,
        css.LAST_SENT_MESSAGE_CSS,
        css.DEPENDENCY_SELECT_CSS,
        css.SUBAGENT_CSS,
        css.RENAME_CSS,
        css.HELP_CSS,
        css.CONFIRM_KILL_CSS,
        css.CONFIRM_PROMOTE_CSS,
        css.AEGIS_CONFIG_CSS,
        css.SNAPSHOT_SAVE_CSS,
        css.SNAPSHOT_RESTORE_CSS,
        css.BROADCAST_PREPARING_CSS,
        css.BROADCAST_CONFIRM_CSS,
        css.DIRECT_MESSAGE_CONFIRM_CSS,
    ]
    for block in modal_css_blocks:
        assert "background: transparent;" in block


def test_invoke_dialog_css_has_role_selector_layout() -> None:
    assert "#invoke-role {" in css.NEW_AGENT_CSS
    assert "#invoke-role RadioButton {" in css.NEW_AGENT_CSS
    assert "#agent-dir-suggestions {" in css.NEW_AGENT_CSS
    assert "position: absolute;" in css.NEW_AGENT_CSS
    assert "layer: overlay;" in css.NEW_AGENT_CSS
    assert "#agent-dir-suggestions.hidden {" in css.NEW_AGENT_CSS
    assert "margin: 1 0;" in css.NEW_AGENT_CSS
    assert "max-height: 30;" in css.NEW_AGENT_CSS


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
    assert "AgentMessageScreen {" in css.AGENT_MESSAGE_CSS
    assert "background: transparent;" in css.AGENT_MESSAGE_CSS
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
    assert "AgentMessageScreen.from-expanded-output {" in css.AGENT_MESSAGE_CSS
    assert "AgentMessageScreen.from-expanded-output #agent-message-dialog {" in css.AGENT_MESSAGE_CSS
    assert "width: 130;" in css.AGENT_MESSAGE_CSS
    assert "max-height: 30;" in css.AGENT_MESSAGE_CSS
    assert "AgentMessageScreen.from-expanded-output #agent-message-input {" in css.AGENT_MESSAGE_CSS
    assert "height: 12;" in css.AGENT_MESSAGE_CSS


def test_premade_message_dialog_css_uses_soft_pear_green_border() -> None:
    assert "PremadeMessageScreen {" in css.PREMADE_MESSAGE_CSS
    assert "background: transparent;" in css.PREMADE_MESSAGE_CSS
    assert "#premade-message-dialog {" in css.PREMADE_MESSAGE_CSS
    assert "border: thick #9acb7a;" in css.PREMADE_MESSAGE_CSS
    assert "#premade-message-template-select {" in css.PREMADE_MESSAGE_CSS
    assert "#premade-message-input {" in css.PREMADE_MESSAGE_CSS
    assert "#premade-message-shortcuts-hint {" in css.PREMADE_MESSAGE_CSS


def test_last_sent_message_dialog_css_uses_cyan_shell_without_buttons() -> None:
    assert "LastSentMessageScreen {" in css.LAST_SENT_MESSAGE_CSS
    assert "background: transparent;" in css.LAST_SENT_MESSAGE_CSS
    assert "#last-sent-message-dialog {" in css.LAST_SENT_MESSAGE_CSS
    assert "border: thick #00d7d7;" in css.LAST_SENT_MESSAGE_CSS
    assert "#last-sent-message-body {" in css.LAST_SENT_MESSAGE_CSS
    assert "scrollbar-size: 0 1;" in css.LAST_SENT_MESSAGE_CSS
    assert "#last-sent-message-buttons" not in css.LAST_SENT_MESSAGE_CSS


def test_expanded_output_hides_horizontal_scrollbar() -> None:
    assert "#expanded-output-stream {" in css.EXPANDED_OUTPUT_CSS
    assert "scrollbar-size: 0 1;" in css.EXPANDED_OUTPUT_CSS


def test_expanded_output_stream_uses_zero_side_padding_only_for_output_content() -> None:
    assert "#expanded-output-dialog {" in css.EXPANDED_OUTPUT_CSS
    assert "padding: 0 0;" in css.EXPANDED_OUTPUT_CSS
    assert "#expanded-output-stream {" in css.EXPANDED_OUTPUT_CSS
    assert "padding: 0 0;" in css.EXPANDED_OUTPUT_CSS
    assert "#expanded-output-title-row {" in css.EXPANDED_OUTPUT_CSS
    assert "#expanded-output-footer {" in css.EXPANDED_OUTPUT_CSS
    assert "#expanded-output-footer {\n    height: 1;\n    color: #6a9090;\n    margin: 1 0 0 0;\n    padding: 0 1;" in css.EXPANDED_OUTPUT_CSS


def test_help_css_uses_table_like_rows_without_borders() -> None:
    assert "#help-bindings-scroll .help-row {" in css.HELP_CSS
    assert "#help-bindings-scroll .help-key {" in css.HELP_CSS
    assert "#help-bindings-scroll .help-desc {" in css.HELP_CSS
    assert "border:" not in css.HELP_CSS.split("#help-bindings-scroll .help-row {")[1]
