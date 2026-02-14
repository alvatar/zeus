"""All CSS strings for the Zeus dashboard."""

APP_CSS = """
Screen {
    background: #000000;
    layers: default splash;
    overflow: hidden;
    scrollbar-size: 0 0;
}

#title-bar {
    dock: top;
    height: 1;
    background: #0a1a2a;
    color: #00d7d7;
    padding: 0 1;
}

#title-text {
    width: auto;
    color: #00d7d7;
    text-style: bold;
}

#title-clock {
    color: #3a5a5a;
}

#top-bars {
    dock: top;
    height: 2;
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
    max-height: 3;
    margin: 0 1;
    padding: 0 2;
    border: round #1a3a3a;
    background: #050a0e;
    color: #cccccc;
}

#mini-map.hidden {
    display: none;
}

#main-content {
    height: 1fr;
}

#table-container {
    width: 1fr;
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

#left-summary {
    height: auto;
    max-height: 8;
    color: #bbbbbb;
    padding: 0 2;
    margin: 0 0 1 0;
    display: none;
}

#left-summary.visible {
    display: block;
}

#interact-panel {
    display: none;
    padding: 0 1;
    background: #080c10;
}

#interact-panel.visible {
    display: block;
    width: 50%;
    border-left: solid #0a3a3a;
}

#interact-panel.visible.split {
    display: block;
}

#interact-summary {
    height: 6;
    color: #bbbbbb;
    padding: 0 1;
}

#interact-summary.hidden {
    display: none;
}

#interact-stream {
    height: 1fr;
    overflow-y: auto;
    scrollbar-size: 0 0;
    padding: 0 1 1 1;
    border-top: solid #1a3030;
}

#interact-input {
    height: 3;
    background: #0a1018;
    border: none;
    border-top: solid #1a3030;
    padding: 0 1;
    color: #cccccc;
}

#interact-input:focus {
    border: none;
    border-top: solid #00d7d7;
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

CHANGE_MODEL_CSS = """
ChangeModelScreen {
    align: center middle;
}

#model-dialog {
    width: 60;
    height: auto;
    border: solid #00d7d7;
    background: #0a0a0a;
    padding: 1 2;
}

#model-dialog Label {
    margin: 0;
    color: #00d7d7;
}

#model-dialog Input {
    margin: 1 0;
}

#model-buttons {
    height: 3;
    align: right middle;
}

#model-buttons Button {
    margin: 0 0 0 1;
}
"""

HELP_CSS = """
HelpScreen {
    align: center middle;
}

#help-dialog {
    width: 70;
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
