"""Modal screens: new agent, sub-agent, rename, confirm kill, help."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
from typing import TYPE_CHECKING, Literal, cast

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    Static,
)

from .widgets import ZeusTextArea

from ..kitty import generate_agent_id
from ..stygian_hippeus import launch_stygian_hippeus
from ..models import AgentWindow, TmuxSession
from ..notes import clear_done_tasks
from ..sessions import make_new_session_path
from .css import (
    NEW_AGENT_CSS,
    AGENT_TASKS_CSS,
    AGENT_MESSAGE_CSS,
    PREMADE_MESSAGE_CSS,
    LAST_SENT_MESSAGE_CSS,
    EXPANDED_OUTPUT_CSS,
    DEPENDENCY_SELECT_CSS,
    SUBAGENT_CSS,
    RENAME_CSS,
    CONFIRM_KILL_CSS,
    CONFIRM_PROMOTE_CSS,
    AEGIS_CONFIG_CSS,
    SNAPSHOT_SAVE_CSS,
    SNAPSHOT_RESTORE_CSS,
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
    from textual.timer import Timer

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
    _DIR_SUGGESTION_LIMIT = 12

    def __init__(self) -> None:
        super().__init__()
        self._dir_suggestion_values: list[str] = []
        self._dir_cycle_seed: str | None = None
        self._dir_cycle_index: int = -1
        self._dir_programmatic_change: bool = False

    def compose(self) -> ComposeResult:
        with Vertical(id="new-agent-dialog"):
            yield Label("Invoke")
            yield Label("Name:")
            yield Input(placeholder="e.g. fix-auth-bug", id="agent-name")
            yield Label("Type:")
            yield RadioSet(
                RadioButton("Hippeus", value=True, id="invoke-role-hippeus"),
                RadioButton("Stygian Hippeus", id="invoke-role-stygian-hippeus"),
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
            yield OptionList(id="agent-dir-suggestions", classes="hidden", compact=True)

    @staticmethod
    def _display_dir_path(path: str) -> str:
        home = os.path.expanduser("~")
        if path == home:
            return "~"
        if path.startswith(home + os.sep):
            return "~" + path[len(home):]
        return path

    def _dir_suggestions(self, raw_value: str) -> list[str]:
        value = raw_value.strip() or "~"
        expanded = os.path.expanduser(value)

        if expanded.endswith(os.sep):
            parent = expanded
            prefix = ""
        else:
            parent, prefix = os.path.split(expanded)
            if not parent:
                parent = "."

        parent = os.path.abspath(parent)

        try:
            with os.scandir(parent) as entries:
                directory_names = [
                    entry.name
                    for entry in entries
                    if entry.is_dir(follow_symlinks=False)
                ]
        except OSError:
            return []

        prefix_fold = prefix.casefold()
        suggestions: list[str] = []
        for name in sorted(directory_names, key=lambda n: (n.startswith("."), n.casefold())):
            if prefix and not name.casefold().startswith(prefix_fold):
                continue
            candidate = os.path.join(parent, name)
            if not candidate.endswith(os.sep):
                candidate += os.sep
            suggestions.append(self._display_dir_path(candidate))
            if len(suggestions) >= self._DIR_SUGGESTION_LIMIT:
                break

        return suggestions

    def _position_dir_suggestions(self) -> None:
        options = self.query_one("#agent-dir-suggestions", OptionList)
        dialog = self.query_one("#new-agent-dialog", Vertical)
        directory_input = self.query_one("#agent-dir", Input)

        rel_x = max(0, directory_input.region.x - dialog.region.x)
        rel_y = max(
            0,
            directory_input.region.y - dialog.region.y + directory_input.region.height,
        )

        options.styles.offset = (rel_x, rel_y)
        options.styles.width = directory_input.region.width

    def _refresh_dir_suggestions(self, raw_value: str) -> None:
        options = self.query_one("#agent-dir-suggestions", OptionList)
        self._dir_suggestion_values = self._dir_suggestions(raw_value)

        options.clear_options()
        if not self._dir_suggestion_values:
            options.add_class("hidden")
            return

        self._position_dir_suggestions()
        options.add_options(self._dir_suggestion_values)
        options.highlighted = 0
        options.remove_class("hidden")

    def _set_directory_input_value(
        self,
        value: str,
        *,
        cursor_position: int | None = None,
    ) -> None:
        directory_input = self.query_one("#agent-dir", Input)
        self._dir_programmatic_change = True
        directory_input.value = value
        directory_input.cursor_position = (
            len(value) if cursor_position is None else max(0, cursor_position)
        )

    def _apply_dir_suggestion(self, suggestion: str) -> None:
        self._set_directory_input_value(suggestion)
        self._dir_cycle_seed = None
        self._dir_cycle_index = -1
        self._refresh_dir_suggestions(suggestion)

    def _cycle_dir_suggestion(self, *, forward: bool) -> bool:
        options = self.query_one("#agent-dir-suggestions", OptionList)
        directory_input = self.query_one("#agent-dir", Input)

        started_cycle = False
        if self._dir_cycle_seed is None:
            self._dir_cycle_seed = directory_input.value
            self._refresh_dir_suggestions(self._dir_cycle_seed)
            self._dir_cycle_index = -1 if forward else 0
            started_cycle = True

        if "hidden" in options.classes or not self._dir_suggestion_values:
            seed = self._dir_cycle_seed or directory_input.value
            self._refresh_dir_suggestions(seed)
            if "hidden" in options.classes or not self._dir_suggestion_values:
                self._dir_cycle_seed = None
                self._dir_cycle_index = -1
                return False

        if not started_cycle:
            idx = options.highlighted
            if idx is not None and 0 <= idx < len(self._dir_suggestion_values):
                self._dir_cycle_index = idx

        delta = 1 if forward else -1
        self._dir_cycle_index = (
            self._dir_cycle_index + delta
        ) % len(self._dir_suggestion_values)
        suggestion = self._dir_suggestion_values[self._dir_cycle_index]
        options.highlighted = self._dir_cycle_index
        self._set_directory_input_value(suggestion)
        return True

    def _delete_dir_segment_left(self) -> bool:
        directory_input = self.query_one("#agent-dir", Input)
        value = directory_input.value
        cursor = max(0, min(directory_input.cursor_position, len(value)))
        left = value[:cursor]
        right = value[cursor:]

        if not left or left in {"/", "~/"}:
            return False

        cut = len(left)
        while cut > 0 and left[cut - 1] == os.sep:
            cut -= 1
        while cut > 0 and left[cut - 1] != os.sep:
            cut -= 1

        if cut == cursor:
            return False

        new_value = value[:cut] + right
        self._set_directory_input_value(new_value, cursor_position=cut)

        self._dir_cycle_seed = None
        self._dir_cycle_index = -1
        self._refresh_dir_suggestions(new_value)
        return True

    def _apply_highlighted_dir_suggestion(
        self,
        *,
        only_if_different: bool,
    ) -> bool:
        options = self.query_one("#agent-dir-suggestions", OptionList)
        idx = options.highlighted
        if idx is None or idx < 0 or idx >= len(self._dir_suggestion_values):
            return False

        suggestion = self._dir_suggestion_values[idx]
        directory_input = self.query_one("#agent-dir", Input)
        if only_if_different and directory_input.value.strip() == suggestion:
            return False

        self._apply_dir_suggestion(suggestion)
        return True

    def on_mount(self) -> None:
        self.query_one("#agent-dir-suggestions", OptionList).add_class("hidden")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "agent-dir":
            return

        if self._dir_programmatic_change:
            self._dir_programmatic_change = False
            return

        self._dir_cycle_seed = None
        self._dir_cycle_index = -1
        self._refresh_dir_suggestions(event.value)

    def on_input_blurred(self, event: Input.Blurred) -> None:
        if event.input.id == "agent-dir":
            self.query_one("#agent-dir-suggestions", OptionList).add_class("hidden")
            self._dir_cycle_seed = None
            self._dir_cycle_index = -1

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "agent-dir-suggestions":
            return

        index = event.option_index
        if index < 0 or index >= len(self._dir_suggestion_values):
            return

        self._apply_dir_suggestion(self._dir_suggestion_values[index])
        self.query_one("#agent-dir", Input).focus()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if event.key not in {
            "up",
            "down",
            "tab",
            "alt+backspace",
        }:
            return

        directory_input = self.query_one("#agent-dir", Input)
        if self.focused is not directory_input:
            return

        options = self.query_one("#agent-dir-suggestions", OptionList)
        if event.key == "tab":
            handled = self._cycle_dir_suggestion(forward=True)
            if handled:
                event.prevent_default()
                event.stop()
            return

        if event.key == "alt+backspace":
            handled = self._delete_dir_segment_left()
            if handled:
                event.prevent_default()
                event.stop()
            return

        if "hidden" in options.classes or not self._dir_suggestion_values:
            self._refresh_dir_suggestions(directory_input.value)
        if "hidden" in options.classes or not self._dir_suggestion_values:
            return

        if event.key == "down":
            options.action_cursor_down()
            event.prevent_default()
            event.stop()
            return

        if event.key == "up":
            options.action_cursor_up()
            event.prevent_default()
            event.stop()

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
        if pressed is not None and pressed.id == "invoke-role-stygian-hippeus":
            return "stygian-hippeus"
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

        if role == "stygian-hippeus":
            try:
                launch_stygian_hippeus(
                    name=name,
                    directory=directory,
                    agent_id=agent_id,
                )
            except (RuntimeError, ValueError) as exc:
                self.zeus.notify(
                    f"Failed to invoke Stygian Hippeus: {exc}",
                    timeout=3,
                )
                return

            self.zeus.notify(f"Invoked Stygian Hippeus: {name}", timeout=3)
            self.dismiss()
            self.zeus.set_timer(1.5, self.zeus.poll_and_update)
            return

        session_path = make_new_session_path(directory)

        env: dict[str, str] = os.environ.copy()
        env["ZEUS_AGENT_NAME"] = name
        env["ZEUS_AGENT_ID"] = agent_id
        env["ZEUS_ROLE"] = role
        env["ZEUS_SESSION_PATH"] = session_path
        if role == "polemarch":
            env["ZEUS_PHALANX_ID"] = f"phalanx-{agent_id}"

        subprocess.Popen(
            [
                "kitty",
                "--directory",
                directory,
                "--hold",
                "bash",
                "-lc",
                f"pi --session {shlex.quote(session_path)}",
            ],
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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

    def __init__(
        self,
        agent: AgentWindow,
        draft: str = "",
        *,
        compact_for_expanded_output: bool = False,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.draft = draft
        self.compact_for_expanded_output = compact_for_expanded_output
        if self.compact_for_expanded_output:
            self.add_class("from-expanded-output")

    def compose(self) -> ComposeResult:
        dialog_classes = "from-expanded-output" if self.compact_for_expanded_output else ""
        with Vertical(id="agent-message-dialog", classes=dialog_classes):
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

    def _expanded_output_underlay(self) -> ExpandedOutputScreen | None:
        stack = list(self.app.screen_stack)
        if len(stack) < 2:
            return None
        for screen in reversed(stack[:-1]):
            if isinstance(screen, ExpandedOutputScreen):
                return screen
        return None

    def _scroll_expanded_output(self, key: str) -> bool:
        expanded = self._expanded_output_underlay()
        if expanded is None:
            return False
        return expanded._scroll_stream_by_key(key)

    def _pointer_inside_dialog(self, screen_x: int, screen_y: int) -> bool:
        dialog = self.query_one("#agent-message-dialog", Vertical)
        return dialog.region.contains(screen_x, screen_y)

    def _forward_scroll_to_expanded_output(
        self,
        key: str,
        event: events.MouseEvent,
    ) -> bool:
        if self._pointer_inside_dialog(event.screen_x, event.screen_y):
            return False
        if not self._scroll_expanded_output(key):
            return False
        event.stop()
        event.prevent_default()
        return True

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self._forward_scroll_to_expanded_output("up", event)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self._forward_scroll_to_expanded_output("down", event)


class PremadeMessageScreen(_ZeusScreenMixin, ModalScreen):
    CSS = PREMADE_MESSAGE_CSS
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "send", "Send", show=False),
        Binding("ctrl+w", "queue", "Queue", show=False),
    ]

    def __init__(self, agent: AgentWindow, templates: list[tuple[str, str]]) -> None:
        super().__init__()
        self.agent = agent

        seen_titles: set[str] = set()
        normalized_templates: list[tuple[str, str]] = []
        for title, body in templates:
            clean_title = title.strip()
            if not clean_title or clean_title in seen_titles:
                continue
            seen_titles.add(clean_title)
            normalized_templates.append((clean_title, body))

        if not normalized_templates:
            normalized_templates = [
                ("Self-review", "Review your output against your own claims again")
            ]

        self._template_options = normalized_templates
        self._message_by_title: dict[str, str] = {
            title: body for title, body in self._template_options
        }
        self._selected_title = self._template_options[0][0]

    def compose(self) -> ComposeResult:
        with Vertical(id="premade-message-dialog"):
            with Horizontal(id="premade-message-title-row"):
                yield Label(
                    f"Message [bold]{self.agent.name}[/bold]",
                    id="premade-message-title",
                )
                yield Label("", id="premade-message-title-spacer")
                yield Label(
                    "(Control-S send | Control-W queue)",
                    id="premade-message-shortcuts-hint",
                )
            yield Label("Preset:")
            yield Select(
                [(title, title) for title, _body in self._template_options],
                allow_blank=False,
                value=self._selected_title,
                id="premade-message-template-select",
            )
            yield ZeusTextArea(
                self._message_by_title[self._selected_title],
                id="premade-message-input",
            )

    def on_mount(self) -> None:
        self.query_one("#premade-message-template-select", Select).focus()

    def _selected_template_title(self) -> str:
        value = self.query_one("#premade-message-template-select", Select).value
        if value is Select.BLANK:
            return self._selected_title
        return str(value)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "premade-message-template-select":
            return
        if event.value is Select.BLANK:
            return

        text_area = self.query_one("#premade-message-input", ZeusTextArea)
        self._message_by_title[self._selected_title] = text_area.text

        self._selected_title = str(event.value)
        text_area.load_text(self._message_by_title[self._selected_title])
        text_area.move_cursor(text_area.document.end)

    def action_send(self) -> None:
        title = self._selected_template_title()
        text = self.query_one("#premade-message-input", ZeusTextArea).text
        self._message_by_title[title] = text
        if self.zeus.do_send_agent_message(self.agent, text):
            self.dismiss()

    def action_queue(self) -> None:
        title = self._selected_template_title()
        text = self.query_one("#premade-message-input", ZeusTextArea).text
        self._message_by_title[title] = text
        if self.zeus.do_queue_agent_message(self.agent, text):
            self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


class LastSentMessageScreen(_ZeusScreenMixin, ModalScreen):
    CSS = LAST_SENT_MESSAGE_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("up", "older", "Older", show=False),
        Binding("down", "newer", "Newer", show=False),
        Binding("y", "yank", "Yank", show=False),
    ]

    def __init__(self, agent: AgentWindow, history_entries: list[str]) -> None:
        super().__init__()
        self.agent = agent
        cleaned = [entry.rstrip() for entry in history_entries if entry.strip()]
        self.history_entries = cleaned if cleaned else ["(no sent message recorded yet)"]
        self.history_offset = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="last-sent-message-dialog"):
            with Horizontal(id="last-sent-message-title-row"):
                yield Label(
                    f"History [bold]{self.agent.name}[/bold]",
                    id="last-sent-message-title",
                )
                yield Label("", id="last-sent-message-title-spacer")
                yield Label(
                    "(↑ older | ↓ newer | y yank | Esc close)",
                    id="last-sent-message-shortcuts-hint",
                )
            yield Label("", id="last-sent-message-position")
            yield RichLog(
                id="last-sent-message-body",
                wrap=True,
                markup=False,
                auto_scroll=False,
            )

    def _current_history_entry(self) -> str:
        return self.history_entries[-1 - self.history_offset]

    def _history_label(self) -> str:
        if self.history_offset == 0:
            return "latest"
        if self.history_offset == 1:
            return "previous"
        return f"previous-{self.history_offset}"

    def _render_history_entry(self) -> None:
        body = self.query_one("#last-sent-message-body", RichLog)
        body.clear()
        body.write(Text(self._current_history_entry()))

        total = len(self.history_entries)
        self.query_one("#last-sent-message-position", Label).update(
            f"History: {self._history_label()} • {self.history_offset + 1}/{total} (newest→oldest)"
        )

    def on_mount(self) -> None:
        body = self.query_one("#last-sent-message-body", RichLog)
        body.can_focus = True
        body.focus()
        self._render_history_entry()

    def action_older(self) -> None:
        if self.history_offset >= len(self.history_entries) - 1:
            return
        self.history_offset += 1
        self._render_history_entry()

    def action_newer(self) -> None:
        if self.history_offset <= 0:
            return
        self.history_offset -= 1
        self._render_history_entry()

    def action_yank(self) -> None:
        entry = self._current_history_entry()
        if not self.zeus._copy_text_to_system_clipboard(entry):
            self.zeus.notify_force(
                "Could not copy history entry to clipboard (wl-copy)",
                timeout=3,
            )
            return
        self.zeus.notify(f"Yanked history: {self.agent.name}", timeout=2)


class ExpandedOutputScreen(_ZeusScreenMixin, ModalScreen):
    CSS = EXPANDED_OUTPUT_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("e", "dismiss", "Close", show=False),
        Binding("f5", "refresh", "Refresh", show=False),
        Binding("g", "go_ahead", "Go ahead", show=False),
        Binding("enter", "message", "Message", show=False),
    ]
    _SCROLL_FLASH_DURATION_S = 0.35

    def __init__(self, agent: AgentWindow) -> None:
        super().__init__()
        self.agent = agent
        self._scroll_flash_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="expanded-output-dialog"):
            with Horizontal(id="expanded-output-title-row"):
                yield Label(
                    f"Expanded output [bold]{self.agent.name}[/bold]",
                    id="expanded-output-title",
                )
                yield Label("", id="expanded-output-title-spacer")
                yield Label(
                    "(Enter message | G go ahead | F5 refresh | Esc close)",
                    id="expanded-output-hint",
                )
            yield RichLog(
                id="expanded-output-stream",
                wrap=True,
                markup=False,
                auto_scroll=False,
            )
            yield Static("", id="expanded-output-scroll-flash", classes="hidden")
            yield Label(
                "↑/↓ PgUp/PgDn Home/End scroll",
                id="expanded-output-footer",
            )

    def on_mount(self) -> None:
        stream = self.query_one("#expanded-output-stream", RichLog)
        stream.can_focus = True
        stream.focus()
        self._hide_scroll_flash()
        self._fetch_output()

    def on_unmount(self) -> None:
        if self._scroll_flash_timer is not None:
            self._scroll_flash_timer.stop()
            self._scroll_flash_timer = None

    @work(thread=True, exclusive=True, group="expanded_output_stream")
    def _fetch_output(self) -> None:
        screen_text = self.zeus._read_agent_screen_text(
            self.agent,
            full=True,
            ansi=True,
        )
        self.zeus.call_from_thread(self._apply_output, screen_text)

    def _apply_output(self, screen_text: str) -> None:
        if not self.is_attached:
            return
        stream = self.query_one("#expanded-output-stream", RichLog)
        content = trim_trailing_blank_lines(strip_pi_input_chrome(screen_text))
        stream.clear()
        self._hide_scroll_flash()
        if not content.strip():
            stream.write(f"[{self.agent.name}] (no output)")
            return
        raw = kitty_ansi_to_standard(content)
        stream.write(Text.from_ansi(raw))
        stream.scroll_end(animate=False)

    def _hide_scroll_flash(self) -> None:
        self._scroll_flash_timer = None
        try:
            flash = self.query_one("#expanded-output-scroll-flash", Static)
        except Exception:
            return
        flash.add_class("hidden")

    def _refresh_scroll_flash_geometry(self) -> bool:
        stream = self.query_one("#expanded-output-stream", RichLog)
        flash = self.query_one("#expanded-output-scroll-flash", Static)
        dialog = self.query_one("#expanded-output-dialog", Vertical)

        viewport_h = int(getattr(stream.size, "height", 0) or 0)
        max_scroll = float(getattr(stream, "max_scroll_y", 0.0) or 0.0)
        if viewport_h <= 0 or max_scroll <= 0.0:
            flash.add_class("hidden")
            return False

        scroll_y = float(getattr(stream, "scroll_y", 0.0) or 0.0)
        scroll_y = max(0.0, min(scroll_y, max_scroll))
        content_h = float(viewport_h) + max_scroll
        thumb_h = max(
            1,
            min(viewport_h, int(round((viewport_h * viewport_h) / max(content_h, 1.0)))),
        )
        track_h = max(0, viewport_h - thumb_h)
        ratio = 0.0 if max_scroll <= 0.0 else (scroll_y / max_scroll)
        thumb_top = int(round(track_h * ratio))

        stream_top = max(0, stream.region.y - dialog.region.y)
        flash.styles.offset = (0, stream_top + thumb_top)
        flash.styles.height = thumb_h
        flash.update("\n".join("▐▐" for _ in range(thumb_h)))
        return True

    def _show_scroll_flash(self) -> None:
        if not self.is_attached:
            return
        if not self._refresh_scroll_flash_geometry():
            return

        flash = self.query_one("#expanded-output-scroll-flash", Static)
        flash.remove_class("hidden")

        if self._scroll_flash_timer is not None:
            self._scroll_flash_timer.stop()
        self._scroll_flash_timer = self.set_timer(
            self._SCROLL_FLASH_DURATION_S,
            self._hide_scroll_flash,
        )

    def _scroll_stream_by_key(self, key: str) -> bool:
        stream = self.query_one("#expanded-output-stream", RichLog)
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
            return False

        self._show_scroll_flash()
        return True

    def action_refresh(self) -> None:
        self._fetch_output()

    def action_message(self) -> None:
        self.zeus.push_screen(
            AgentMessageScreen(
                self.agent,
                self.zeus._message_draft_for_agent(self.agent),
                compact_for_expanded_output=True,
            )
        )

    def action_go_ahead(self) -> None:
        self.dismiss()
        self.zeus.action_go_ahead()

    def on_key(self, event: events.Key) -> None:
        if not self._scroll_stream_by_key(event.key):
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


class ConfirmPromoteScreen(_ZeusScreenMixin, ModalScreen):
    CSS = CONFIRM_PROMOTE_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "dismiss", "No", show=False),
    ]

    def __init__(
        self,
        *,
        agent: AgentWindow | None = None,
        sess: TmuxSession | None = None,
        promote_to: Literal["hippeus", "polemarch", "stygian-hippeus"] = "hippeus",
    ) -> None:
        super().__init__()
        if (agent is None) == (sess is None):
            raise ValueError("provide exactly one promotion target")

        self.agent = agent
        self.sess = sess

        target = (promote_to or "").strip().lower()
        if agent is not None:
            if target not in {"hippeus", "polemarch"}:
                raise ValueError("invalid promotion target for agent")
            self.promote_to = cast(
                Literal["hippeus", "polemarch", "stygian-hippeus"],
                target,
            )
        else:
            self.promote_to = "stygian-hippeus"

    def _prompt_text(self) -> str:
        if self.agent is not None and self.promote_to == "hippeus":
            return f"Promote sub-Hippeus [bold]{self.agent.name}[/bold] to Hippeus?"
        if self.agent is not None and self.promote_to == "polemarch":
            return f"Promote Hippeus [bold]{self.agent.name}[/bold] to Polemarch?"
        if self.sess is not None:
            return f"Promote Hoplite [bold]{self.sess.name}[/bold] to Stygian Hippeus?"
        return "Promote selected target?"

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-promote-dialog"):
            yield Label(self._prompt_text())
            with Horizontal(id="confirm-promote-buttons"):
                yield Button("Yes, promote", variant="warning", id="yes-btn")
                yield Button("No", variant="default", id="no-btn")

    def on_mount(self) -> None:
        self.query_one("#yes-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes-btn":
            self.action_confirm()
            return
        self.dismiss()
        event.stop()

    def action_confirm(self) -> None:
        if self.agent is not None and self.promote_to == "hippeus":
            self.zeus.do_promote_sub_hippeus(self.agent)
        elif self.agent is not None and self.promote_to == "polemarch":
            self.zeus.do_promote_hippeus_to_polemarch(self.agent)
        elif self.sess is not None:
            self.zeus.do_promote_hoplite_tmux(self.sess)
        self.dismiss()


class AegisConfigureScreen(_ZeusScreenMixin, ModalScreen):
    CSS = AEGIS_CONFIG_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("enter", "confirm", "Enable", show=False),
    ]

    def __init__(
        self,
        agent: AgentWindow,
        *,
        continue_prompt: str,
        iterate_prompt: str,
        completion_prompt: str,
    ) -> None:
        super().__init__()
        self.agent = agent
        self._mode = "continue"
        self._prompt_by_mode: dict[str, str] = {
            "continue": continue_prompt,
            "iterate": iterate_prompt,
            "completion": completion_prompt,
        }

    def compose(self) -> ComposeResult:
        with Vertical(id="aegis-config-dialog"):
            yield Label(f"Configure Aegis for [bold]{self.agent.name}[/bold]")
            yield Label("Behavior:")
            yield RadioSet(
                RadioButton("Continue", value=True, id="aegis-config-continue"),
                RadioButton("Iterate", id="aegis-config-iterate"),
                RadioButton("Completion", id="aegis-config-completion"),
                id="aegis-config-mode",
                compact=False,
            )
            yield Label("Message (editable):")
            yield ZeusTextArea(
                self._prompt_by_mode["continue"],
                id="aegis-config-prompt",
            )
            with Horizontal(id="aegis-config-buttons"):
                yield Button("Cancel", variant="default", id="aegis-config-cancel")
                yield Button("Enable", variant="primary", id="aegis-config-enable")

    def on_mount(self) -> None:
        self.query_one("#aegis-config-mode", RadioSet).focus()

    def _selected_mode(self) -> str:
        mode_set = self.query_one("#aegis-config-mode", RadioSet)
        pressed = mode_set.pressed_button
        if pressed is not None and pressed.id == "aegis-config-iterate":
            return "iterate"
        if pressed is not None and pressed.id == "aegis-config-completion":
            return "completion"
        return "continue"

    def _current_prompt(self) -> str:
        return self.query_one("#aegis-config-prompt", ZeusTextArea).text

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "aegis-config-mode":
            return

        prompt = self.query_one("#aegis-config-prompt", ZeusTextArea)
        self._prompt_by_mode[self._mode] = prompt.text

        self._mode = self._selected_mode()
        prompt.load_text(self._prompt_by_mode[self._mode])
        prompt.move_cursor(prompt.document.end)
        self.query_one("#aegis-config-mode", RadioSet).focus()

    def action_confirm(self) -> None:
        mode = self._selected_mode()
        prompt_text = self._current_prompt()

        if not prompt_text.strip():
            self.zeus.notify_force("Aegis message cannot be empty", timeout=3)
            self.query_one("#aegis-config-prompt", ZeusTextArea).focus()
            return

        self._prompt_by_mode[mode] = prompt_text
        if self.zeus.do_enable_aegis(self.agent, prompt_text):
            self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "aegis-config-enable":
            self.action_confirm()
            event.stop()
            return

        self.dismiss()
        event.stop()


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


class SaveSnapshotScreen(_ZeusScreenMixin, ModalScreen):
    CSS = SNAPSHOT_SAVE_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("enter", "confirm", "Save", show=False),
    ]

    def __init__(self, *, default_name: str) -> None:
        super().__init__()
        self.default_name = default_name

    def compose(self) -> ComposeResult:
        with Vertical(id="snapshot-save-dialog"):
            yield Label("Save snapshot")
            yield Label("Snapshot name:")
            yield Input(value=self.default_name, id="snapshot-save-name")
            yield Checkbox(
                "Close all agents after saving",
                value=False,
                id="snapshot-save-close-all",
                compact=False,
            )
            with Horizontal(id="snapshot-save-buttons"):
                yield Button("Cancel", variant="default", id="snapshot-save-cancel")
                yield Button("Save", variant="primary", id="snapshot-save-confirm")

    def on_mount(self) -> None:
        inp = self.query_one("#snapshot-save-name", Input)
        inp.focus()
        inp.action_select_all()

    def _close_all_value(self) -> bool:
        return self.query_one("#snapshot-save-close-all", Checkbox).value

    def _name_value(self) -> str:
        return self.query_one("#snapshot-save-name", Input).value.strip()

    def action_confirm(self) -> None:
        name = self._name_value()
        if not name:
            self.zeus.notify_force("Snapshot name cannot be empty", timeout=3)
            self.query_one("#snapshot-save-name", Input).focus()
            return

        ok = self.zeus.do_save_snapshot(name, close_all=self._close_all_value())
        if ok:
            self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "snapshot-save-confirm":
            self.action_confirm()
            event.stop()
            return

        self.dismiss()
        event.stop()


class RestoreSnapshotScreen(_ZeusScreenMixin, ModalScreen):
    CSS = SNAPSHOT_RESTORE_CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("enter", "confirm", "Restore", show=False),
    ]

    def __init__(self, *, snapshot_files: list[Path]) -> None:
        super().__init__()
        self.snapshot_files = snapshot_files

    def compose(self) -> ComposeResult:
        options = [(path.name, str(path)) for path in self.snapshot_files]
        default_snapshot = options[0][1] if options else Select.BLANK

        with Vertical(id="snapshot-restore-dialog"):
            yield Label("Restore snapshot")
            yield Label("Snapshot file:")
            yield Select(
                options,
                allow_blank=False,
                value=default_snapshot,
                id="snapshot-restore-file",
            )
            yield Label("Workspace placement:")
            yield Select(
                [
                    ("Original workspaces", "original"),
                    ("Current workspace", "current"),
                ],
                allow_blank=False,
                value="original",
                id="snapshot-restore-workspace",
            )
            yield Label("If agent id already running:")
            yield Select(
                [
                    ("Error", "error"),
                    ("Skip", "skip"),
                    ("Replace", "replace"),
                ],
                allow_blank=False,
                value="error",
                id="snapshot-restore-running",
            )
            with Horizontal(id="snapshot-restore-buttons"):
                yield Button("Cancel", variant="default", id="snapshot-restore-cancel")
                yield Button("Restore", variant="warning", id="snapshot-restore-confirm")

    def on_mount(self) -> None:
        self.query_one("#snapshot-restore-file", Select).focus()

    def _selected_value(self, selector: str) -> str | None:
        value = self.query_one(selector, Select).value
        if value is Select.BLANK:
            return None
        return str(value)

    def action_confirm(self) -> None:
        snapshot_path = self._selected_value("#snapshot-restore-file")
        workspace_mode = self._selected_value("#snapshot-restore-workspace")
        if_running = self._selected_value("#snapshot-restore-running")

        if not snapshot_path or not workspace_mode or not if_running:
            self.zeus.notify_force("Restore settings are incomplete", timeout=3)
            return

        ok = self.zeus.do_restore_snapshot(
            snapshot_path,
            workspace_mode=workspace_mode,
            if_running=if_running,
        )
        if ok:
            self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "snapshot-restore-confirm":
            self.action_confirm()
            event.stop()
            return

        self.dismiss()
        event.stop()


# ── Help ──────────────────────────────────────────────────────────────

_HELP_BINDINGS: list[tuple[str, str]] = [
    ("", "─── Hippeis Management ───"),
    ("q", "Stop Hippeus (table focus)"),
    ("e", "Expand output for selected Hippeus"),
    ("r", "Rename Hippeus / tmux"),
    ("t", "Edit tasks for selected Hippeus"),
    ("y", "Yank block between %%%% markers for selected Hippeus"),
    ("Ctrl+t", "Clear done tasks for selected Hippeus"),
    ("p", "Cycle priority (3→2→1→4→3)"),
    ("a", "Bring Hippeus under the Aegis"),
    ("s", "Spawn sub-Hippeus"),
    ("Ctrl+p", "Promote selected sub-Hippeus / Hippeus / Hoplite"),
    ("d", "Set/remove blocking dependency for selected Hippeus"),
    ("g", "Queue 'go ahead' for selected Hippeus"),
    ("Ctrl+g", "Open preset message dialog for selected Hippeus"),
    ("h", "History for selected Hippeus"),
    ("k", "Kill Hippeus / tmux session"),
    ("Ctrl+k (tmux row)", "Kill tmux session process"),
    ("z", "Invoke Hippeus / Stygian Hippeus / Polemarch"),
    ("Ctrl+r", "Save snapshot of all restorable agents"),
    ("Ctrl+Shift+r", "Restore snapshot"),
    ("b", "Broadcast latest share payload (ZEUS_MSG_FILE or %%%% block)"),
    ("n", "Queue next task for selected Hippeus"),
    (
        "m",
        "Direct-send latest share payload (ZEUS_MSG_FILE or %%%% block)",
    ),
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
    ("Ctrl+s (message dialog)", "Send message in Hippeus Message / Preset dialog"),
    ("Ctrl+w (message dialog)", "Queue message in Hippeus Message / Preset dialog"),
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
