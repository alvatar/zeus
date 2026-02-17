"""Modal screens: new agent, sub-agent, rename, confirm kill, help."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
)

from .widgets import ZeusTextArea

from ..kitty import generate_agent_id, get_screen_text
from ..models import AgentWindow, TmuxSession
from ..notes import clear_done_tasks
from .css import (
    NEW_AGENT_CSS,
    AGENT_TASKS_CSS,
    AGENT_MESSAGE_CSS,
    EXPANDED_OUTPUT_CSS,
    DEPENDENCY_SELECT_CSS,
    SUBAGENT_CSS,
    RENAME_CSS,
    CONFIRM_KILL_CSS,
    BROADCAST_PREPARING_CSS,
    BROADCAST_CONFIRM_CSS,
    DIRECT_MESSAGE_CONFIRM_CSS,
    HELP_CSS,
)
from .stream import (
    kitty_ansi_to_standard,
    strip_pi_input_chrome,
    trim_trailing_blank_lines,
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
            yield Label("Invoke")
            yield Label("Name:")
            yield Input(placeholder="e.g. fix-auth-bug", id="agent-name")
            yield Label("Type:")
            yield RadioSet(
                RadioButton("Hippeus", value=True, id="invoke-role-hippeus"),
                RadioButton("Polemarch", id="invoke-role-polemarch"),
                id="invoke-role",
                compact=False,
            )
            yield Label("Directory:")
            yield Input(
                placeholder="e.g. /home/user/projects/backend",
                value="~/code",
                id="agent-dir",
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "agent-name":
            self.query_one("#agent-dir", Input).focus()
        elif event.input.id == "agent-dir":
            self._launch()

    def _selected_role(self) -> str:
        role_set = self.query_one("#invoke-role", RadioSet)
        pressed = role_set.pressed_button
        if pressed is not None and pressed.id == "invoke-role-polemarch":
            return "polemarch"
        return "hippeus"

    def _launch(self) -> None:
        name: str = self.query_one("#agent-name", Input).value.strip()
        directory: str = (
            self.query_one("#agent-dir", Input).value.strip() or "."
        )
        if not name:
            self.query_one("#agent-name", Input).focus()
            return
        if self.zeus._is_agent_name_taken(name):
            self.zeus.notify(f"Name already exists: {name}", timeout=3)
            self.query_one("#agent-name", Input).focus()
            return

        role = self._selected_role()
        agent_id = generate_agent_id()
        directory = os.path.expanduser(directory)
        env: dict[str, str] = os.environ.copy()
        env["AGENTMON_NAME"] = name
        env["ZEUS_AGENT_ID"] = agent_id
        env["ZEUS_ROLE"] = role
        if role == "polemarch":
            env["ZEUS_PHALANX_ID"] = f"phalanx-{agent_id}"

        subprocess.Popen(
            ["kitty", "--directory", directory, "--hold",
             "bash", "-lc", "pi"],
            env=env, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if role == "polemarch":
            self.zeus.schedule_polemarch_bootstrap(agent_id, name)
            self.zeus.notify(f"Invoked Polemarch: {name}", timeout=3)
        else:
            self.zeus.notify(f"Invoked Hippeus: {name}", timeout=3)
        self.dismiss()
        self.zeus.set_timer(1.5, self.zeus.poll_and_update)


class AgentTasksScreen(_ZeusScreenMixin, ModalScreen):
    CSS = AGENT_TASKS_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    def __init__(self, agent: AgentWindow, task_text: str) -> None:
        super().__init__()
        self.agent = agent
        self.task_text = task_text

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-tasks-dialog"):
            yield Label(f"Tasks: [bold]{self.agent.name}[/bold]")
            yield Label(
                "Format: '- [] task' or '- [ ] task' (multiline continues until "
                "next task header)."
            )
            yield ZeusTextArea(self.task_text, id="agent-tasks-input")
            with Horizontal(id="agent-tasks-buttons"):
                yield Button(
                    "Clear done [x]",
                    variant="warning",
                    id="agent-tasks-clear-done-btn",
                )
                yield Label("", id="agent-tasks-buttons-spacer")
                yield Button("Save", variant="primary", id="agent-tasks-save-btn")

    def on_mount(self) -> None:
        ta = self.query_one("#agent-tasks-input", ZeusTextArea)
        ta.focus()
        ta.move_cursor(ta.document.end)

    def _save(self) -> None:
        task_text = self.query_one("#agent-tasks-input", ZeusTextArea).text
        self.dismiss()
        self.zeus.do_save_agent_tasks(self.agent, task_text)

    def _clear_done_tasks(self) -> None:
        ta = self.query_one("#agent-tasks-input", ZeusTextArea)
        updated, removed = clear_done_tasks(ta.text)
        ta.load_text(updated)
        ta.move_cursor(ta.document.end)
        if removed:
            suffix = "" if removed == 1 else "s"
            self.zeus.notify(f"Cleared {removed} done task{suffix}", timeout=2)
        else:
            self.zeus.notify("No done tasks to clear", timeout=2)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "agent-tasks-save-btn":
            self._save()
        elif event.button.id == "agent-tasks-clear-done-btn":
            self._clear_done_tasks()
        event.stop()

    def action_save(self) -> None:
        self._save()


class AgentMessageScreen(_ZeusScreenMixin, ModalScreen):
    CSS = AGENT_MESSAGE_CSS
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "send", "Send", show=False),
        Binding("ctrl+w", "queue", "Queue", show=False),
    ]

    def __init__(self, agent: AgentWindow, draft: str = "") -> None:
        super().__init__()
        self.agent = agent
        self.draft = draft

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-message-dialog"):
            with Horizontal(id="agent-message-title-row"):
                yield Label(f"Message [bold]{self.agent.name}[/bold]", id="agent-message-title")
                yield Label("", id="agent-message-title-spacer")
                yield Label(
                    "(Control-S send | Control-W queue)",
                    id="agent-message-shortcuts-hint",
                )
            yield ZeusTextArea(self.draft, id="agent-message-input")
            with Horizontal(id="agent-message-buttons"):
                yield Button(
                    "append as task",
                    variant="warning",
                    id="agent-message-add-task-btn",
                )
                yield Button(
                    "prepend as task",
                    variant="warning",
                    id="agent-message-add-task-first-btn",
                )

    def on_mount(self) -> None:
        ta = self.query_one("#agent-message-input", ZeusTextArea)
        ta.focus()
        ta.move_cursor(ta.document.end)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "agent-message-add-task-btn":
            self.action_add_task()
        elif event.button.id == "agent-message-add-task-first-btn":
            self.action_add_task_first()
        event.stop()

    def action_send(self) -> None:
        text = self.query_one("#agent-message-input", ZeusTextArea).text
        if self.zeus.do_send_agent_message(self.agent, text):
            self.dismiss()

    def action_queue(self) -> None:
        text = self.query_one("#agent-message-input", ZeusTextArea).text
        if self.zeus.do_queue_agent_message(self.agent, text):
            self.dismiss()

    def action_add_task(self) -> None:
        text = self.query_one("#agent-message-input", ZeusTextArea).text
        if self.zeus.do_add_agent_message_task(self.agent, text):
            self.dismiss()

    def action_add_task_first(self) -> None:
        text = self.query_one("#agent-message-input", ZeusTextArea).text
        if self.zeus.do_prepend_agent_message_task(self.agent, text):
            self.dismiss()

    def action_cancel(self) -> None:
        draft = self.query_one("#agent-message-input", ZeusTextArea).text
        self.zeus.do_save_agent_message_draft(self.agent, draft)
        self.dismiss()


class ExpandedOutputScreen(_ZeusScreenMixin, ModalScreen):
    CSS = EXPANDED_OUTPUT_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("e", "dismiss", "Close", show=False),
        Binding("f5", "refresh", "Refresh", show=False),
        Binding("enter", "message", "Message", show=False),
    ]

    def __init__(self, agent: AgentWindow) -> None:
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        with Vertical(id="expanded-output-dialog"):
            with Horizontal(id="expanded-output-title-row"):
                yield Label(
                    f"Expanded output [bold]{self.agent.name}[/bold]",
                    id="expanded-output-title",
                )
                yield Label("", id="expanded-output-title-spacer")
                yield Label(
                    "(Enter message | F5 refresh | Esc close)",
                    id="expanded-output-hint",
                )
            yield RichLog(
                id="expanded-output-stream",
                wrap=True,
                markup=False,
                auto_scroll=False,
            )
            yield Label(
                "↑/↓ PgUp/PgDn Home/End scroll",
                id="expanded-output-footer",
            )

    def on_mount(self) -> None:
        stream = self.query_one("#expanded-output-stream", RichLog)
        stream.can_focus = True
        stream.focus()
        self._fetch_output()

    @work(thread=True, exclusive=True, group="expanded_output_stream")
    def _fetch_output(self) -> None:
        screen_text = get_screen_text(self.agent, full=True, ansi=True)
        self.zeus.call_from_thread(self._apply_output, screen_text)

    def _apply_output(self, screen_text: str) -> None:
        if not self.is_attached:
            return
        stream = self.query_one("#expanded-output-stream", RichLog)
        content = trim_trailing_blank_lines(strip_pi_input_chrome(screen_text))
        stream.clear()
        if not content.strip():
            stream.write(f"  [{self.agent.name}] (no output)")
            return
        raw = kitty_ansi_to_standard(content)
        stream.write(Text.from_ansi(raw))

    def action_refresh(self) -> None:
        self._fetch_output()

    def action_message(self) -> None:
        self.zeus.push_screen(
            AgentMessageScreen(
                self.agent,
                self.zeus._message_draft_for_agent(self.agent),
            )
        )

    def on_key(self, event: events.Key) -> None:
        stream = self.query_one("#expanded-output-stream", RichLog)
        key = event.key
        if key == "up":
            stream.scroll_up(animate=False)
        elif key == "down":
            stream.scroll_down(animate=False)
        elif key == "pageup":
            stream.scroll_page_up(animate=False)
        elif key == "pagedown":
            stream.scroll_page_down(animate=False)
        elif key == "home":
            stream.scroll_home(animate=False)
        elif key == "end":
            stream.scroll_end(animate=False)
        else:
            return

        event.stop()
        event.prevent_default()


class DependencySelectScreen(_ZeusScreenMixin, ModalScreen):
    CSS = DEPENDENCY_SELECT_CSS
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def __init__(
        self,
        blocked_agent: AgentWindow,
        options: list[tuple[str, str]],
    ) -> None:
        super().__init__()
        self.blocked_agent = blocked_agent
        self.options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="dependency-select-dialog"):
            yield Label(
                f"Set blocking dependency for [bold]{self.blocked_agent.name}[/bold]"
            )
            yield Label("Blocked by:")
            yield Select(self.options, id="dependency-select")
            with Horizontal(id="dependency-select-buttons"):
                yield Button("Cancel", variant="default", id="dependency-cancel-btn")
                yield Button("Set dependency", variant="primary", id="dependency-save-btn")

    def on_mount(self) -> None:
        self.query_one("#dependency-select", Select).focus()

    def _selected_dependency_key(self) -> str | None:
        select = self.query_one("#dependency-select", Select)
        value = select.value
        if value is Select.BLANK:
            return None
        return str(value)

    def _confirm(self) -> None:
        dep_key = self._selected_dependency_key()
        if not dep_key:
            self.zeus.notify("Select a dependency target", timeout=2)
            return
        self.dismiss()
        self.zeus.do_set_dependency(self.blocked_agent, dep_key)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dependency-save-btn":
            self._confirm()
        else:
            self.dismiss()
        event.stop()


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
                f"🧬 Fork sub-Hippeus from [bold]{self.agent.name}[/bold]"
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
            yield Label(f"Rename Hippeus [bold]{self.agent.name}[/bold]")
            yield Label("New name:")
            yield Input(value=self.agent.name, id="rename-input")
            yield Label("", id="rename-error")

    def on_mount(self) -> None:
        inp = self.query_one("#rename-input", Input)
        inp.focus()
        inp.action_select_all()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "rename-input":
            self.query_one("#rename-error", Label).update("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_rename()

    def _do_rename(self) -> None:
        new_name: str = self.query_one("#rename-input", Input).value.strip()
        if not new_name or new_name == self.agent.name:
            self.dismiss()
            return

        exclude_key = self.zeus._agent_key(self.agent)
        if self.zeus._is_agent_name_taken(new_name, exclude_key=exclude_key):
            self.query_one("#rename-error", Label).update(
                "Name already exists. Choose a unique Hippeus name."
            )
            self.query_one("#rename-input", Input).focus()
            return

        if self.zeus.do_rename_agent(self.agent, new_name):
            self.dismiss()


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

    def on_mount(self) -> None:
        inp = self.query_one("#rename-input", Input)
        inp.focus()
        inp.action_select_all()

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
            yield Label(f"Kill Hippeus [bold]{self.agent.name}[/bold]?")
            with Horizontal(id="confirm-kill-buttons"):
                yield Button("Yes, kill", variant="error", id="yes-btn")
                yield Button("No", variant="default", id="no-btn")

    def on_mount(self) -> None:
        self.query_one("#yes-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes-btn":
            self.zeus.do_kill_agent(self.agent)
        self.dismiss()
        event.stop()

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

    def on_mount(self) -> None:
        self.query_one("#yes-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes-btn":
            self.zeus.do_kill_tmux(self.sess)
        self.dismiss()
        event.stop()

    def action_confirm(self) -> None:
        self.zeus.do_kill_tmux(self.sess)
        self.dismiss()


class BroadcastPreparingScreen(_ZeusScreenMixin, ModalScreen):
    CSS = BROADCAST_PREPARING_CSS
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(
        self,
        source_name: str,
        recipient_count: int,
        job_id: int,
        title: str = "Preparing broadcast payload…",
        target_options: list[tuple[str, str]] | None = None,
        selected_target_key: str | None = None,
    ) -> None:
        super().__init__()
        self.source_name = source_name
        self.recipient_count = recipient_count
        self.job_id = job_id
        self.prep_title = title
        self.target_options = target_options or []

        self.selected_target_key: str | None = None
        option_keys = {key for _, key in self.target_options}
        if selected_target_key in option_keys:
            self.selected_target_key = selected_target_key
        elif self.target_options:
            self.selected_target_key = self.target_options[0][1]

    def compose(self) -> ComposeResult:
        with Vertical(id="broadcast-preparing"):
            with Vertical(id="broadcast-preparing-dialog"):
                yield Label(self.prep_title)
                yield Label(f"Source: {self.source_name}")
                yield Label(f"Recipients: {self.recipient_count}")
                if self.target_options:
                    yield Label("Target Hippeus (choose while preparing):")
                    yield Select(
                        [(name, key) for name, key in self.target_options],
                        allow_blank=False,
                        value=self.selected_target_key,
                        id="broadcast-preparing-target-select",
                    )
                yield Label("Extracting content between wrapped %%%% markers. You can cancel.")
                with Horizontal(id="broadcast-preparing-buttons"):
                    yield Button("Cancel", variant="default", id="broadcast-preparing-cancel-btn")

    def on_mount(self) -> None:
        if self.target_options:
            self.query_one("#broadcast-preparing-target-select", Select).focus()
            return
        self.query_one("#broadcast-preparing-cancel-btn", Button).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "broadcast-preparing-target-select":
            return
        if event.value is Select.BLANK:
            return
        self.zeus.set_prepare_target_selection(self.job_id, str(event.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "broadcast-preparing-cancel-btn":
            self.zeus.cancel_broadcast_prepare(self.job_id)
        self.dismiss()
        event.stop()

    def action_cancel(self) -> None:
        self.zeus.cancel_broadcast_prepare(self.job_id)
        self.dismiss()


class ConfirmBroadcastScreen(_ZeusScreenMixin, ModalScreen):
    CSS = BROADCAST_CONFIRM_CSS
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        source_name: str,
        recipient_keys: list[str],
        recipient_names: list[str],
        message: str,
    ) -> None:
        super().__init__()
        self.source_name = source_name
        self.recipient_keys = recipient_keys
        self.recipient_names = recipient_names
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="broadcast-dialog"):
            yield Label(
                f"Broadcast marked block from [bold]{self.source_name}[/bold]?"
            )
            names = ", ".join(self.recipient_names[:6])
            extra = len(self.recipient_names) - 6
            if extra > 0:
                names = f"{names}, +{extra} more"
            yield Label(f"Recipients ({len(self.recipient_names)}): {names}")
            yield Label("Message (editable):")
            yield ZeusTextArea(self.message, id="broadcast-preview")
            with Horizontal(id="broadcast-buttons"):
                yield Button("Cancel", variant="default", id="broadcast-cancel-btn")
                yield Button("Broadcast", variant="primary", id="broadcast-send-btn")

    def on_mount(self) -> None:
        preview = self.query_one("#broadcast-preview", ZeusTextArea)
        preview.focus()
        preview.move_cursor(preview.document.end)

    def _current_message(self) -> str:
        return self.query_one("#broadcast-preview", ZeusTextArea).text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "broadcast-send-btn":
            self.zeus.do_enqueue_broadcast(
                self.source_name,
                self.recipient_keys,
                self._current_message(),
            )
        self.dismiss()
        event.stop()

    def action_confirm(self) -> None:
        self.zeus.do_enqueue_broadcast(
            self.source_name,
            self.recipient_keys,
            self._current_message(),
        )
        self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


class ConfirmDirectMessageScreen(_ZeusScreenMixin, ModalScreen):
    CSS = DIRECT_MESSAGE_CONFIRM_CSS
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        source_name: str,
        target_options: list[tuple[str, str]],
        message: str,
        initial_target_key: str | None = None,
        source_key: str | None = None,
    ) -> None:
        super().__init__()
        self.source_name = source_name
        self.source_key = source_key
        self.target_options = target_options
        self.message = message

        option_keys = {key for _, key in self.target_options}
        if initial_target_key in option_keys:
            self.initial_target_key = initial_target_key
        else:
            self.initial_target_key = self.target_options[0][1]

    def compose(self) -> ComposeResult:
        with Vertical(id="direct-dialog"):
            yield Label(
                f"Send marked block from [bold]{self.source_name}[/bold]"
            )
            yield Label("Target Hippeus:")
            yield Select(
                [(name, key) for name, key in self.target_options],
                allow_blank=False,
                value=self.initial_target_key,
                id="direct-target-select",
            )
            yield Label("Message (editable):")
            yield ZeusTextArea(self.message, id="direct-preview")
            with Horizontal(id="direct-buttons"):
                yield Button("Cancel", variant="default", id="direct-cancel-btn")
                yield Button("Send", variant="primary", id="direct-send-btn")

    def on_mount(self) -> None:
        select = self.query_one("#direct-target-select", Select)
        select.focus()

    def _current_message(self) -> str:
        return self.query_one("#direct-preview", ZeusTextArea).text

    def _selected_target_key(self) -> str | None:
        select = self.query_one("#direct-target-select", Select)
        value = select.value
        if value is Select.BLANK:
            return None
        return str(value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "direct-send-btn":
            target_key = self._selected_target_key()
            if not target_key:
                self.zeus.notify("No target selected", timeout=2)
                return
            self.zeus.do_enqueue_direct(
                self.source_name,
                target_key,
                self._current_message(),
                source_key=self.source_key,
            )
        self.dismiss()
        event.stop()

    def action_confirm(self) -> None:
        target_key = self._selected_target_key()
        if not target_key:
            self.zeus.notify("No target selected", timeout=2)
            return
        self.zeus.do_enqueue_direct(
            self.source_name,
            target_key,
            self._current_message(),
            source_key=self.source_key,
        )
        self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


# ── Help ──────────────────────────────────────────────────────────────

_HELP_BINDINGS: list[tuple[str, str]] = [
    ("", "─── Hippeis Management ───"),
    ("z", "Invoke Hippeus / Polemarch"),
    ("a", "Bring Hippeus under the Aegis"),
    ("n", "Queue next task for selected Hippeus"),
    ("g", "Queue 'go ahead' for selected Hippeus"),
    ("t", "Edit tasks for selected Hippeus"),
    ("e", "Expand output for selected Hippeus"),
    ("Ctrl+t", "Clear done tasks for selected Hippeus"),
    ("i", "Set/remove blocking dependency for selected Hippeus"),
    ("s", "Spawn sub-Hippeus"),
    ("q", "Stop Hippeus (table focus)"),
    ("Ctrl+b", "Broadcast block between %%%% markers to active Hippeis"),
    (
        "Ctrl+m",
        "Send text between %%%% markers to selected target",
    ),
    ("Ctrl+k (tmux row)", "Kill tmux session process"),
    ("k", "Kill Hippeus / tmux session"),
    ("p", "Cycle priority (3→2→1→4→3)"),
    ("r", "Rename Hippeus / tmux"),
    ("", "─── Navigation ───"),
    ("Enter", "Focus interact input"),
    ("Esc", "Back to Hippeis table"),
    ("Tab", "Toggle focus between table and interact input"),
    ("Ctrl+Enter", "Teleport to Hippeus / open tmux"),
    ("Ctrl+o", "Open kitty shell in selected target directory"),
    ("", "─── Interact Panel ───"),
    ("Ctrl+s", "Send message to Hippeus / tmux"),
    ("Ctrl+w", "Queue message (Alt+Enter in pi)"),
    ("Ctrl+k", "Kill to end-of-line (or delete line if empty)"),
    ("Ctrl+u", "Clear input"),
    ("Ctrl+y", "Yank killed text (system clipboard, fallback local kill buffer)"),
    ("Ctrl+a / Ctrl+e", "Move to line start/end; at edge jump to prev/next line"),
    ("Alt+b / Alt+f", "Move cursor one word left / right"),
    ("Alt+d / Alt+Backspace", "Delete word right / left"),
    ("↑/↓", "Cursor up/down; at visual top/bottom browse history"),
    ("", "─── Dialogs ───"),
    ("Esc (dialog)", "Close/cancel active dialog"),
    ("Ctrl+s (tasks dialog)", "Save tasks in Hippeus Tasks dialog"),
    ("Ctrl+s (message dialog)", "Send message in Hippeus Message dialog"),
    ("Ctrl+w (message dialog)", "Queue message in Hippeus Message dialog"),
    ("y / n / Enter (kill confirm)", "Confirm or cancel kill confirmation dialogs"),
    ("", "─── Settings ───"),
    ("F4", "Toggle sort mode (priority / alpha)"),
    ("F5", "Force refresh"),
    ("F6", "Toggle split layout"),
    ("F8", "Toggle interact panel"),
    ("?", "This help"),
    ("F10", "Quit Zeus"),
    ("", "─── Global ───"),
    ("1", "Toggle interact input area"),
    ("2", "Toggle mini-map"),
    ("3", "Toggle sparkline charts"),
    ("4", "Toggle interact target band"),
]


class HelpScreen(ModalScreen):
    CSS = HELP_CSS
    BINDINGS = [Binding("escape", "dismiss", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("⚡ Zeus — Keybindings", classes="help-title")
            with VerticalScroll(id="help-bindings-scroll"):
                for key, desc in _HELP_BINDINGS:
                    if not key:
                        yield Label(desc, classes="help-section")
                        continue
                    with Horizontal(classes="help-row"):
                        yield Label(key, classes="help-key")
                        yield Label(desc, classes="help-desc")
            yield Label(
                "↑/↓ PgUp/PgDn scroll • Esc closes",
                classes="help-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#help-bindings-scroll", VerticalScroll).focus()

    def on_key(self, event: events.Key) -> None:
        scroller = self.query_one("#help-bindings-scroll", VerticalScroll)
        key = event.key
        if key == "up":
            scroller.scroll_up(animate=False)
        elif key == "down":
            scroller.scroll_down(animate=False)
        elif key == "pageup":
            scroller.scroll_page_up(animate=False)
        elif key == "pagedown":
            scroller.scroll_page_down(animate=False)
        elif key == "home":
            scroller.scroll_home(animate=False)
        elif key == "end":
            scroller.scroll_end(animate=False)
        else:
            return

        event.stop()
        event.prevent_default()
