"""All CSS strings for the Zeus dashboard."""

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

#agent-table.hidden {
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

NEW_AGENT_CSS = """
NewAgentScreen {
    align: center middle;
}

#new-agent-dialog {
    width: 60;
    height: auto;
    max-height: 16;
    border: thick #00d7d7;
    background: #0a0a0a;
    padding: 1 2;
}

#new-agent-dialog Label {
    margin: 1 0 0 0;
    color: #00d7d7;
}

#new-agent-dialog Input {
    margin: 0 0 1 0;
}

#new-agent-buttons {
    height: 3;
    align: right middle;
    margin: 1 0 0 0;
}

#new-agent-buttons Button {
    margin: 0 0 0 1;
}
"""

SUBAGENT_CSS = """
SubAgentScreen {
    align: center middle;
}

#subagent-dialog {
    width: 60;
    height: auto;
    max-height: 12;
    border: thick #00d7d7;
    background: #0a0a0a;
    padding: 1 2;
}

#subagent-dialog Label {
    margin: 1 0 0 0;
    color: #00d7d7;
}

#subagent-dialog .dim-label {
    color: #447777;
    margin: 0;
}

#subagent-dialog Input {
    margin: 0 0 1 0;
}

#subagent-buttons {
    height: 3;
    align: right middle;
    margin: 1 0 0 0;
}

#subagent-buttons Button {
    margin: 0 0 0 1;
}
"""

RENAME_CSS = """
RenameScreen, RenameTmuxScreen {
    align: center middle;
}

#rename-dialog {
    width: 55;
    height: auto;
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

#rename-buttons {
    height: 3;
    align: right middle;
}

#rename-buttons Button {
    margin: 0 0 0 1;
}
"""



HELP_CSS = """
HelpScreen {
    align: center middle;
}

#help-dialog {
    width: 90;
    height: auto;
    max-height: 30;
    border: solid #00d7d7;
    background: #0a0a0a;
    padding: 1 3;
}

#help-dialog Label {
    width: 100%;
    margin: 0;
    color: #cccccc;
}

#help-dialog .help-title {
    color: #00d7d7;
    text-style: bold;
    margin: 0 0 1 0;
}

#help-dialog .help-key {
    color: #00d7d7;
}
"""

CONFIRM_KILL_CSS = """
ConfirmKillScreen, ConfirmKillTmuxScreen {
    align: center middle;
}

#confirm-kill-dialog {
    width: 60;
    height: auto;
    max-height: 12;
    border: thick #ff3366;
    background: #0a0a0a;
    padding: 2 3;
}

#confirm-kill-dialog Label {
    width: 100%;
    content-align: center middle;
    margin: 0 0 1 0;
    color: #cccccc;
}

#confirm-kill-buttons {
    height: 3;
    align: center middle;
}

#confirm-kill-buttons Button {
    margin: 0 1;
}
"""

BROADCAST_PREPARING_CSS = """
BroadcastPreparingScreen {
    align: center middle;
    background: #000000;
}

#broadcast-preparing {
    width: 100%;
    height: 100%;
    background: #000000;
    align: center middle;
}

#broadcast-preparing-dialog {
    width: 72;
    height: auto;
    border: thick #ff6a00;
    background: #0a0a0a;
    padding: 2 3;
}

#broadcast-preparing-dialog Label {
    width: 100%;
    margin: 0 0 1 0;
    color: #dddddd;
    content-align: center middle;
}

#broadcast-preparing-buttons {
    height: 3;
    align: center middle;
}

#broadcast-preparing-buttons Button {
    margin: 0 1;
}
"""

BROADCAST_CONFIRM_CSS = """
ConfirmBroadcastScreen {
    align: center middle;
}

#broadcast-dialog {
    width: 120;
    height: auto;
    max-height: 36;
    border: thick #ff6a00;
    background: #0a0a0a;
    padding: 1 2;
}

#broadcast-dialog Label {
    width: 100%;
    margin: 0 0 1 0;
    color: #cccccc;
}

#broadcast-preview {
    height: 20;
    margin: 0 0 1 0;
    border: solid #444444;
    background: #0a1018;
    color: #dddddd;
}

#broadcast-buttons {
    height: 3;
    align: right middle;
}

#broadcast-buttons Button {
    margin: 0 0 0 1;
}
"""

DIRECT_MESSAGE_CONFIRM_CSS = """
ConfirmDirectMessageScreen {
    align: center middle;
}

#direct-dialog {
    width: 120;
    height: auto;
    max-height: 38;
    border: thick #ff6a00;
    background: #0a0a0a;
    padding: 1 2;
}

#direct-dialog Label {
    width: 100%;
    margin: 0 0 1 0;
    color: #cccccc;
}

#direct-target-select {
    width: 100%;
    margin: 0 0 1 0;
}

#direct-preview {
    height: 20;
    margin: 0 0 1 0;
    border: solid #444444;
    background: #0a1018;
    color: #dddddd;
}

#direct-buttons {
    height: 3;
    align: right middle;
}

#direct-buttons Button {
    margin: 0 0 0 1;
}
"""
