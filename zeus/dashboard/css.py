"""All CSS strings for the Zeus dashboard."""


def _button_row_css(
    row_id: str,
    *,
    align: str = "right middle",
    row_margin: str | None = None,
    button_margin: str = "0 0 0 1",
    width: str | None = None,
) -> str:
    width_rule = f"    width: {width};\n" if width else ""
    row_margin_rule = f"    margin: {row_margin};\n" if row_margin else ""
    return (
        f"#{row_id} {{\n"
        f"{width_rule}"
        "    height: 3;\n"
        f"    align: {align};\n"
        f"{row_margin_rule}"
        "}\n\n"
        f"#{row_id} Button {{\n"
        f"    margin: {button_margin};\n"
        "}\n"
    )


APP_CSS = """
Screen {
    background: #000000;
    layers: default splash;
    overflow: hidden;
    scrollbar-size: 0 0;
}

#title-bar {
    height: 1;
    background: #0a1a2a;
    color: #00d7d7;
    padding: 0 1;
    margin: 0 0 1 0;
}

#title-text {
    width: auto;
    color: #00d7d7;
    text-style: bold;
}

#title-clock {
    color: #3a5a5a;
}



#usage-bar {
    height: 1;
    padding: 0 1;
    background: #050f15;
}

.usage-item {
    width: auto;
    margin: 0 2 0 0;
}

#mini-map {
    height: auto;
    max-height: 10;
    margin: 1 1 0 1;
    padding: 0 2;
    border: round #1a3a3a;
    background: #050a0e;
    color: #cccccc;
    link-style: none;
    link-style-hover: none;
}

#mini-map.hidden {
    display: none;
}

#sparkline-chart {
    height: auto;
    max-height: 12;
    margin: 0 1 0 1;
    padding: 0 2;
    border: round #1a3a3a;
    background: #050a0e;
    color: #cccccc;
}

#sparkline-chart.hidden {
    display: none;
}

#main-content {
    height: 1fr;
    layout: vertical;
}

#main-content.split {
    layout: horizontal;
}

#table-container {
    width: 1fr;
    height: 1fr;
    background: #000000;
}

#agent-table {
    height: 1fr;
    margin: 1 1;
    background: #000000;
    scrollbar-size: 0 1;
}

DataTable {
    height: 1fr;
    background: #000000;
}

DataTable > .datatable--header {
    background: #0a1a2a;
    color: #00aabb;
    text-style: bold;
}

DataTable > .datatable--even-row {
    background: #000000;
}

DataTable > .datatable--odd-row {
    background: #000000;
}

#status-line {
    dock: bottom;
    height: 1;
    padding: 0 1;
    background: #0a1a2a;
    color: #447777;
}

#openai-usage-bar {
    height: 1;
    padding: 0 1;
    background: #050f15;
}

#interact-panel {
    display: none;
    padding: 0 1;
    background: #080c10;
}

#interact-panel.visible {
    display: block;
    width: 100%;
    height: 40%;
    border-top: solid #0a3a3a;
}

#interact-panel.visible.split {
    width: 50%;
    height: 100%;
    border-top: none;
    border-left: solid #0a3a3a;
}

#interact-stream {
    height: 1fr;
    overflow-y: auto;
    scrollbar-size: 0 0;
    padding: 0 1 1 1;
    border-top: solid #1a3030;
}

#interact-target {
    height: 1;
    padding: 0 1;
    content-align: left middle;
    background: #2a2218;
    color: #f2e8dc;
    text-style: bold;
}

#interact-target.hidden {
    display: none;
}

#interact-input {
    height: 3;
    background: #0a1018;
    border: none;
    border-top: solid #1a3030;
    padding: 0 1;
    color: #cccccc;
}

#interact-input.hidden {
    display: none;
}

/* Match the paused/read-only caret color even when editable. */
#interact-input .text-area--cursor {
    background: $warning-darken-1;
}

#interact-input:focus {
    border: none;
    border-top: solid #ff6a00;
}

#empty-message {
    width: 100%;
    height: auto;
    content-align: center middle;
    margin: 3 0;
    color: #447777;
}
"""

NEW_AGENT_CSS = f"""
NewAgentScreen {{
    align: center middle;
    background: transparent;
}}

#new-agent-dialog {{
    width: 60;
    height: auto;
    max-height: 30;
    border: thick #00d7d7;
    background: #0a0a0a;
    padding: 1 2;
}}

#new-agent-dialog Label {{
    margin: 1 0 0 0;
    color: #00d7d7;
}}

#new-agent-dialog Input {{
    margin: 0 0 1 0;
}}

#invoke-role {{
    width: 100%;
    margin: 0 0 1 0;
}}

#invoke-role RadioButton {{
    color: #cccccc;
    margin: 1 0;
}}
"""

AGENT_TASKS_CSS = f"""
AgentTasksScreen {{
    align: center middle;
    background: transparent;
}}

#agent-tasks-dialog {{
    width: 110;
    height: auto;
    max-height: 40;
    border: thick #ffaf00;
    background: #0a0a0a;
    padding: 1 2;
}}

#agent-tasks-dialog Label {{
    margin: 0 0 1 0;
    color: #dddddd;
}}

#agent-tasks-input {{
    height: 20;
    margin: 0 0 1 0;
    border: solid #444444;
    background: #0a1018;
    color: #dddddd;
}}

#agent-tasks-buttons-spacer {{
    width: 1fr;
    height: 1;
}}

{_button_row_css(
    "agent-tasks-buttons",
    align="left middle",
    width="100%",
    button_margin="0 1 0 0",
)}
"""

AGENT_MESSAGE_CSS = f"""
AgentMessageScreen {{
    align: center middle;
    background: transparent;
}}

#agent-message-dialog {{
    width: 110;
    height: auto;
    max-height: 40;
    border: thick #ffaf00;
    background: #0a0a0a;
    padding: 1 2;
}}

#agent-message-dialog Label {{
    margin: 0 0 1 0;
    color: #dddddd;
}}

#agent-message-title-row {{
    width: 100%;
    height: 1;
    align: left middle;
    margin: 0 0 1 0;
}}

#agent-message-title,
#agent-message-title-spacer,
#agent-message-shortcuts-hint {{
    margin: 0;
    height: 1;
}}

#agent-message-title-spacer {{
    width: 1fr;
}}

#agent-message-shortcuts-hint {{
    color: #888888;
    content-align: right middle;
}}

#agent-message-input {{
    height: 20;
    margin: 0 0 1 0;
    border: solid #444444;
    background: #0a1018;
    color: #dddddd;
}}

AgentMessageScreen.from-expanded-output {{
    align: center top;
}}

AgentMessageScreen.from-expanded-output #agent-message-dialog {{
    width: 130;
    max-height: 30;
    margin: 1 0 0 0;
}}

AgentMessageScreen.from-expanded-output #agent-message-input {{
    height: 12;
}}

{_button_row_css(
    "agent-message-buttons",
    align="left middle",
    width="100%",
    button_margin="0 2 0 0",
)}
"""

LAST_SENT_MESSAGE_CSS = """
LastSentMessageScreen {
    align: center middle;
    background: transparent;
}

#last-sent-message-dialog {
    width: 110;
    height: auto;
    max-height: 40;
    border: thick #00d7d7;
    background: #0a0a0a;
    padding: 1 2;
}

#last-sent-message-title-row {
    width: 100%;
    height: 1;
    align: left middle;
    margin: 0 0 1 0;
}

#last-sent-message-title,
#last-sent-message-title-spacer,
#last-sent-message-shortcuts-hint {
    margin: 0;
    height: 1;
}

#last-sent-message-title-spacer {
    width: 1fr;
}

#last-sent-message-shortcuts-hint {
    color: #66a6a6;
    content-align: right middle;
}

#last-sent-message-position {
    margin: 0 0 1 0;
    color: #66a6a6;
}

#last-sent-message-body {
    height: 1fr;
    border: solid #1a5050;
    background: #041418;
    color: #dddddd;
    padding: 0 1;
    overflow-y: auto;
    scrollbar-size: 0 1;
}
"""

EXPANDED_OUTPUT_CSS = """
ExpandedOutputScreen {
    align: center middle;
    background: #000000d0;
}

#expanded-output-dialog {
    width: 100%;
    height: 100%;
    border: none;
    background: #000000;
    padding: 0 1;
}

#expanded-output-title-row {
    width: 100%;
    height: 1;
    align: left middle;
    background: #0a1a2a;
    color: #00d7d7;
    margin: 0 0 1 0;
    padding: 0 1;
}

#expanded-output-title,
#expanded-output-title-spacer,
#expanded-output-hint {
    margin: 0;
    height: 1;
}

#expanded-output-title-spacer {
    width: 1fr;
}

#expanded-output-hint {
    color: #6a9090;
    content-align: right middle;
}

#expanded-output-stream {
    height: 1fr;
    border-top: solid #1a3030;
    padding: 0 1;
    overflow-y: auto;
    scrollbar-size: 0 1;
}

#expanded-output-footer {
    height: 1;
    color: #6a9090;
    margin: 1 0 0 0;
}
"""

DEPENDENCY_SELECT_CSS = f"""
DependencySelectScreen {{
    align: center middle;
    background: transparent;
}}

#dependency-select-dialog {{
    width: 84;
    height: auto;
    max-height: 24;
    border: thick #777777;
    background: #0a0a0a;
    padding: 1 2;
}}

#dependency-select-dialog Label {{
    width: 100%;
    margin: 0 0 1 0;
    color: #cccccc;
}}

#dependency-select {{
    width: 100%;
    margin: 0 0 1 0;
}}

{_button_row_css("dependency-select-buttons", align="center middle", row_margin="1 0 0 0", button_margin="0 1", width="100%")}
"""

SUBAGENT_CSS = f"""
SubAgentScreen {{
    align: center middle;
    background: transparent;
}}

#subagent-dialog {{
    width: 60;
    height: auto;
    max-height: 12;
    border: thick #00d7d7;
    background: #0a0a0a;
    padding: 1 2;
}}

#subagent-dialog Label {{
    margin: 1 0 0 0;
    color: #00d7d7;
}}

#subagent-dialog .dim-label {{
    color: #447777;
    margin: 0;
}}

#subagent-dialog Input {{
    margin: 0 0 1 0;
}}

{_button_row_css("subagent-buttons", row_margin="1 0 0 0")}
"""

RENAME_CSS = """
RenameScreen, RenameTmuxScreen {
    align: center middle;
    background: transparent;
}

#rename-dialog {
    width: 55;
    height: auto;
    min-height: 10;
    border: solid #00d7d7;
    background: #0a0a0a;
    padding: 1 2;
}

#rename-dialog Label {
    margin: 0;
    color: #00d7d7;
}

#rename-dialog Input {
    margin: 1 0;
}

#rename-error {
    margin: 0;
    color: #ff4d4d;
}
"""



HELP_CSS = """
HelpScreen {
    align: center middle;
    background: transparent;
}

#help-dialog {
    width: 100;
    height: 90%;
    max-height: 40;
    border: solid #00d7d7;
    background: #0a0a0a;
    padding: 1 3;
}

#help-bindings-scroll {
    height: 1fr;
    overflow-y: auto;
    scrollbar-size: 1 1;
    margin: 0 0 1 0;
}

#help-dialog Label {
    margin: 0;
    color: #cccccc;
}

#help-bindings-scroll .help-section {
    width: 100%;
    margin: 1 0 0 0;
    color: #888888;
    text-style: bold;
}

#help-bindings-scroll .help-row {
    width: 100%;
    height: auto;
    align: left top;
    margin: 0;
}

#help-bindings-scroll .help-key {
    width: 30;
    margin: 0 1 0 0;
    color: #00d7d7;
    text-style: bold;
}

#help-bindings-scroll .help-desc {
    width: 1fr;
    color: #cccccc;
}

#help-dialog .help-title {
    width: 100%;
    color: #00d7d7;
    text-style: bold;
    margin: 0 0 1 0;
}

#help-dialog .help-footer {
    width: 100%;
    color: #888888;
}
"""

CONFIRM_KILL_CSS = f"""
ConfirmKillScreen, ConfirmKillTmuxScreen {{
    align: center middle;
    background: transparent;
}}

#confirm-kill-dialog {{
    width: 60;
    height: auto;
    max-height: 12;
    border: thick #ff3366;
    background: #0a0a0a;
    padding: 2 3;
}}

#confirm-kill-dialog Label {{
    width: 100%;
    content-align: center middle;
    margin: 0 0 1 0;
    color: #cccccc;
}}

{_button_row_css("confirm-kill-buttons", align="center middle", button_margin="0 1")}
"""

BROADCAST_PREPARING_CSS = f"""
BroadcastPreparingScreen {{
    align: center middle;
    background: transparent;
}}

#broadcast-preparing {{
    width: 100%;
    height: 100%;
    background: transparent;
    align: center middle;
}}

#broadcast-preparing-dialog {{
    width: 72;
    height: auto;
    border: thick #ff6a00;
    background: #0a0a0a;
    padding: 2 3;
}}

#broadcast-preparing-dialog Label {{
    width: 100%;
    margin: 0 0 1 0;
    color: #dddddd;
    content-align: center middle;
}}

#broadcast-preparing-target-select {{
    width: 100%;
    margin: 0 0 1 0;
}}

{_button_row_css("broadcast-preparing-buttons", align="center middle", button_margin="0 1")}
"""

BROADCAST_CONFIRM_CSS = f"""
ConfirmBroadcastScreen {{
    align: center middle;
    background: transparent;
}}

#broadcast-dialog {{
    width: 120;
    height: auto;
    max-height: 36;
    border: thick #ff6a00;
    background: #0a0a0a;
    padding: 1 2;
}}

#broadcast-dialog Label {{
    width: 100%;
    margin: 0 0 1 0;
    color: #cccccc;
}}

#broadcast-preview {{
    height: 20;
    margin: 0 0 1 0;
    border: solid #444444;
    background: #0a1018;
    color: #dddddd;
}}

{_button_row_css("broadcast-buttons")}
"""

DIRECT_MESSAGE_CONFIRM_CSS = f"""
ConfirmDirectMessageScreen {{
    align: center middle;
    background: transparent;
}}

#direct-dialog {{
    width: 120;
    height: auto;
    max-height: 38;
    border: thick #ff6a00;
    background: #0a0a0a;
    padding: 1 2;
}}

#direct-dialog Label {{
    width: 100%;
    margin: 0 0 1 0;
    color: #cccccc;
}}

#direct-target-select {{
    width: 100%;
    margin: 0 0 1 0;
}}

#direct-preview {{
    height: 20;
    margin: 0 0 1 0;
    border: solid #444444;
    background: #0a1018;
    color: #dddddd;
}}

{_button_row_css("direct-buttons")}
"""
