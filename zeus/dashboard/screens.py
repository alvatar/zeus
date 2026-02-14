"""Modal screens: new agent, sub-agent, rename, confirm kill, help."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from ..kitty import generate_agent_id
from ..models import AgentWindow, TmuxSession
from .css import (
    NEW_AGENT_CSS,
    SUBAGENT_CSS,
    RENAME_CSS,
    CONFIRM_KILL_CSS,
    HELP_CSS,

)

if TYPE_CHECKING:
    from .app import ZeusApp


# ── New agent ─────────────────────────────────────────────────────────

class _ZeusScreenMixin:
    """Mixin providing typed access to the ZeusApp instance."""

    @property
    def zeus(self) -> ZeusApp:
        return self.app  # type: ignore[return-value, attr-defined]


class NewAgentScreen(_ZeusScreenMixin, ModalScreen):
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
        name: str = self.query_one("#agent-name", Input).value.strip()
        directory: str = (
            self.query_one("#agent-dir", Input).value.strip() or "."
        )
        if not name:
            self.query_one("#agent-name", Input).focus()
            return
        directory = os.path.expanduser(directory)
        env: dict[str, str] = os.environ.copy()
        env["AGENTMON_NAME"] = name
        env["ZEUS_AGENT_ID"] = generate_agent_id()
        subprocess.Popen(
            ["kitty", "--directory", directory, "--hold",
             "bash", "-lc", "pi"],
            env=env, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.dismiss()
        self.zeus.notify(f"Launched: {name} (pi)", timeout=3)
        self.zeus.set_timer(1.5, self.zeus.poll_and_update)


# ── Sub-agent ─────────────────────────────────────────────────────────

class SubAgentScreen(_ZeusScreenMixin, ModalScreen):
    CSS = SUBAGENT_CSS
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def __init__(self, agent: AgentWindow) -> None:
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
        name: str = self.query_one("#subagent-name", Input).value.strip()
        if not name:
            self.query_one("#subagent-name", Input).focus()
            return
        self.dismiss()
        self.zeus.do_spawn_subagent(self.agent, name)


# ── Rename ────────────────────────────────────────────────────────────

class RenameScreen(_ZeusScreenMixin, ModalScreen):
    CSS = RENAME_CSS
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def __init__(self, agent: AgentWindow) -> None:
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
        new_name: str = self.query_one("#rename-input", Input).value.strip()
        if not new_name or new_name == self.agent.name:
            self.dismiss()
            return
        self.dismiss()
        self.zeus.do_rename_agent(self.agent, new_name)


class RenameTmuxScreen(_ZeusScreenMixin, ModalScreen):
    CSS = RENAME_CSS
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def __init__(self, sess: TmuxSession) -> None:
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
        new_name: str = self.query_one("#rename-input", Input).value.strip()
        if not new_name or new_name == self.sess.name:
            self.dismiss()
            return
        self.dismiss()
        self.zeus.do_rename_tmux(self.sess, new_name)


# ── Kill confirmation ─────────────────────────────────────────────────

class ConfirmKillScreen(_ZeusScreenMixin, ModalScreen):
    CSS = CONFIRM_KILL_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "dismiss", "No", show=False),
    ]

    def __init__(self, agent: AgentWindow) -> None:
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
            self.zeus.do_kill_agent(self.agent)
        self.dismiss()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            self.zeus.do_kill_agent(self.agent)
            self.dismiss()
            event.stop()
            event.prevent_default()

    def action_confirm(self) -> None:
        self.zeus.do_kill_agent(self.agent)
        self.dismiss()


class ConfirmKillTmuxScreen(_ZeusScreenMixin, ModalScreen):
    CSS = CONFIRM_KILL_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "dismiss", "No", show=False),
    ]

    def __init__(self, sess: TmuxSession) -> None:
        super().__init__()
        self.sess = sess

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-kill-dialog"):
            yield Label(
                f"Detach and close window for "
                f"[bold]{self.sess.name}[/bold]?"
            )
            with Horizontal(id="confirm-kill-buttons"):
                yield Button("Yes, close", variant="error", id="yes-btn")
                yield Button("No", variant="default", id="no-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes-btn":
            self.zeus.do_kill_tmux(self.sess)
        self.dismiss()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            self.zeus.do_kill_tmux(self.sess)
            self.dismiss()
            event.stop()
            event.prevent_default()

    def action_confirm(self) -> None:
        self.zeus.do_kill_tmux(self.sess)
        self.dismiss()


# ── Help ──────────────────────────────────────────────────────────────

_HELP_BINDINGS: list[tuple[str, str]] = [
    ("", "─── Navigation ───"),
    ("Enter", "Focus interact input"),
    ("Esc", "Back to agent table"),
    ("Ctrl+Enter", "Teleport to agent / open tmux"),
    ("", "─── Interact Panel ───"),
    ("Ctrl+s", "Send message to agent / tmux"),
    ("Ctrl+w", "Queue message (Alt+Enter in pi)"),
    ("Ctrl+y", "Paste text; image clipboard inserts temp file path"),
    ("↑/↓", "When input is empty: browse last 10 messages"),
    ("Ctrl+u", "Clear input"),
    ("", "─── Agent Management ───"),
    ("n", "New agent"),
    ("s", "Spawn sub-agent"),
    ("q", "Stop agent (table focus)"),
    ("Ctrl+q", "Stop agent (works from input too)"),
    ("k", "Kill agent / tmux session"),
    ("p", "Cycle priority (3→1→2→3)"),
    ("r", "Rename agent / tmux"),
    ("", "─── Settings ───"),
    ("F4", "Toggle sort mode (priority / alpha)"),
    ("F5", "Force refresh"),
    ("F6", "Toggle split layout"),
    ("F8", "Toggle interact panel"),
    ("?", "This help"),
    ("F10", "Quit Zeus"),
]


class HelpScreen(ModalScreen):
    CSS = HELP_CSS
    BINDINGS = [Binding("escape", "dismiss", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("⚡ Zeus — Keybindings", classes="help-title")
            for key, desc in _HELP_BINDINGS:
                if not key:
                    yield Label(f"  [dim]{desc}[/]")
                else:
                    yield Label(
                        f"  [bold #00d7d7]{key:<12}[/]  {desc}"
                    )
            yield Label("")
            yield Label(
                "  [dim]Press any key to close[/]",
            )

    def on_key(self, event: events.Key) -> None:
        self.dismiss()
        event.stop()
        event.prevent_default()
