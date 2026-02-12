"""Modal screens: new agent, sub-agent, rename, confirm kill."""

import os
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from ..models import AgentWindow, TmuxSession
from .css import (
    NEW_AGENT_CSS,
    SUBAGENT_CSS,
    RENAME_CSS,
    CONFIRM_KILL_CSS,
)


# ── New agent ─────────────────────────────────────────────────────────

class NewAgentScreen(ModalScreen):
    CSS = NEW_AGENT_CSS
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="new-agent-dialog"):
            yield Label("New Agent")
            yield Label("Name:")
            yield Input(placeholder="e.g. fix-auth-bug", id="agent-name")
            yield Label("Directory:")
            yield Input(
                placeholder="e.g. /home/user/projects/backend",
                value=os.getcwd(),
                id="agent-dir",
            )
            with Horizontal(id="new-agent-buttons"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Launch", variant="primary", id="launch-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "launch-btn":
            self._launch()
        else:
            self.dismiss()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "agent-name":
            self.query_one("#agent-dir", Input).focus()
        elif event.input.id == "agent-dir":
            self._launch()

    def _launch(self) -> None:
        name = self.query_one("#agent-name", Input).value.strip()
        directory = self.query_one("#agent-dir", Input).value.strip() or "."
        if not name:
            self.query_one("#agent-name", Input).focus()
            return
        directory = os.path.expanduser(directory)
        env = os.environ.copy()
        env["AGENTMON_NAME"] = name
        subprocess.Popen(
            ["kitty", "--directory", directory, "--hold",
             "bash", "-lc", "pi"],
            env=env, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.dismiss()
        self.app.notify(f"Launched: {name} (pi)", timeout=3)
        self.app.set_timer(1.5, self.app.poll_and_update)


# ── Sub-agent ─────────────────────────────────────────────────────────

class SubAgentScreen(ModalScreen):
    CSS = SUBAGENT_CSS
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def __init__(self, agent: AgentWindow):
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        with Vertical(id="subagent-dialog"):
            yield Label(
                f"🧬 Fork sub-agent from [bold]{self.agent.name}[/bold]"
            )
            yield Label(f"CWD: {self.agent.cwd}", classes="dim-label")
            yield Label("Name:")
            yield Input(
                placeholder=f"e.g. {self.agent.name}-sub",
                value=f"{self.agent.name}-sub",
                id="subagent-name",
            )
            with Horizontal(id="subagent-buttons"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("🧬 Fork", variant="primary", id="fork-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fork-btn":
            self._fork()
        else:
            self.dismiss()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._fork()

    def _fork(self) -> None:
        name = self.query_one("#subagent-name", Input).value.strip()
        if not name:
            self.query_one("#subagent-name", Input).focus()
            return
        self.dismiss()
        self.app.do_spawn_subagent(self.agent, name)


# ── Rename ────────────────────────────────────────────────────────────

class RenameScreen(ModalScreen):
    CSS = RENAME_CSS
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def __init__(self, agent: AgentWindow):
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        with Vertical(id="rename-dialog"):
            yield Label(f"Rename agent [bold]{self.agent.name}[/bold]")
            yield Label("New name:")
            yield Input(value=self.agent.name, id="rename-input")
            with Horizontal(id="rename-buttons"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Rename", variant="primary", id="rename-btn")

    def on_mount(self) -> None:
        inp = self.query_one("#rename-input", Input)
        inp.focus()
        inp.action_select_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rename-btn":
            self._do_rename()
        else:
            self.dismiss()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_rename()

    def _do_rename(self) -> None:
        new_name = self.query_one("#rename-input", Input).value.strip()
        if not new_name or new_name == self.agent.name:
            self.dismiss()
            return
        self.dismiss()
        self.app.do_rename_agent(self.agent, new_name)


class RenameTmuxScreen(ModalScreen):
    CSS = RENAME_CSS
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def __init__(self, sess: TmuxSession):
        super().__init__()
        self.sess = sess

    def compose(self) -> ComposeResult:
        with Vertical(id="rename-dialog"):
            yield Label(
                f"Rename tmux session [bold]{self.sess.name}[/bold]"
            )
            yield Label("New name:")
            yield Input(value=self.sess.name, id="rename-input")
            with Horizontal(id="rename-buttons"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Rename", variant="primary", id="rename-btn")

    def on_mount(self) -> None:
        inp = self.query_one("#rename-input", Input)
        inp.focus()
        inp.action_select_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rename-btn":
            self._do_rename()
        else:
            self.dismiss()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_rename()

    def _do_rename(self) -> None:
        new_name = self.query_one("#rename-input", Input).value.strip()
        if not new_name or new_name == self.sess.name:
            self.dismiss()
            return
        self.dismiss()
        self.app.do_rename_tmux(self.sess, new_name)


# ── Kill confirmation ─────────────────────────────────────────────────

class ConfirmKillScreen(ModalScreen):
    CSS = CONFIRM_KILL_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "dismiss", "No", show=False),
    ]

    def __init__(self, agent: AgentWindow):
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-kill-dialog"):
            yield Label(f"Kill agent [bold]{self.agent.name}[/bold]?")
            with Horizontal(id="confirm-kill-buttons"):
                yield Button("Yes, kill", variant="error", id="yes-btn")
                yield Button("No", variant="default", id="no-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes-btn":
            self.app.do_kill_agent(self.agent)
        self.dismiss()
        event.stop()

    def on_key(self, event) -> None:
        if event.key == "enter":
            self.app.do_kill_agent(self.agent)
            self.dismiss()
            event.stop()
            event.prevent_default()

    def action_confirm(self) -> None:
        self.app.do_kill_agent(self.agent)
        self.dismiss()


class ConfirmKillTmuxScreen(ModalScreen):
    CSS = CONFIRM_KILL_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "dismiss", "No", show=False),
    ]

    def __init__(self, sess: TmuxSession):
        super().__init__()
        self.sess = sess

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-kill-dialog"):
            yield Label(
                f"Detach and close window for [bold]{self.sess.name}[/bold]?"
            )
            with Horizontal(id="confirm-kill-buttons"):
                yield Button("Yes, close", variant="error", id="yes-btn")
                yield Button("No", variant="default", id="no-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes-btn":
            self.app.do_kill_tmux(self.sess)
        self.dismiss()
        event.stop()

    def on_key(self, event) -> None:
        if event.key == "enter":
            self.app.do_kill_tmux(self.sess)
            self.dismiss()
            event.stop()
            event.prevent_default()

    def action_confirm(self) -> None:
        self.app.do_kill_tmux(self.sess)
        self.dismiss()
