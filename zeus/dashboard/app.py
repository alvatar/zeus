"""Zeus TUI dashboard — main App class."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import textwrap
import threading
import time

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.notifications import SeverityLevel
from textual.timer import Timer
from textual.widgets import DataTable, Static, Label, Input, TextArea, RichLog
from textual.widget import Widget
from rich.style import Style
from rich.text import Text


class SortMode(Enum):
    PRIORITY = "priority"
    ALPHA = "alpha"

from ..config import MESSAGE_TMP_DIR, PRIORITIES_FILE, PANEL_VISIBILITY_FILE
from ..notes import clear_done_tasks, load_agent_tasks, save_agent_tasks
from ..dependencies import load_agent_dependencies, save_agent_dependencies
from ..settings import SETTINGS
from ..models import (
    AgentWindow, TmuxSession, State, UsageData, OpenAIUsageData,
)
from ..input_history import append_history, load_history, prune_histories
from ..process import fmt_bytes, read_process_metrics
from ..kitty import (
    discover_agents, get_screen_text, focus_window, close_window,
    resolve_agent_session_path,
    resolve_agent_session_path_with_source,
    spawn_subagent, load_names, save_names, kitty_cmd,
)
from ..sessions import read_session_text, read_session_user_text
from ..message_queue import (
    OutboundEnvelope,
    ack_envelope,
    claim_envelope,
    enqueue_envelope,
    ensure_queue_dirs,
    list_new_envelopes,
    load_envelope,
    queue_new_dir,
    reclaim_stale_inflight,
    requeue_envelope,
)
from ..message_receipts import (
    has_message_receipt,
    load_message_receipts,
    prune_message_receipts,
    record_message_receipt,
    save_message_receipts,
)
from ..sway import build_pid_workspace_map
from ..tmux import (
    backfill_tmux_owner_options,
    discover_tmux_sessions,
    ensure_tmux_update_environment,
    match_tmux_to_agents,
)
from ..hidden_hippeus import (
    HIDDEN_AGENT_BACKEND,
    capture_hidden_screen_text,
    discover_hidden_agents,
    hidden_agent_row_key,
    is_hidden_tmux_session,
    kill_hidden_session,
    promote_hoplite_to_hidden_hippeus,
    resolve_hidden_session_path,
    send_hidden_escape,
    send_hidden_text,
)
from ..state import detect_state, activity_signature, parse_footer
from ..usage import read_usage, read_openai_usage, time_left
from ..windowing import (
    find_ancestor_pid_by_comm,
    focus_pid,
    kill_pid,
    move_pid_to_workspace_and_focus_later,
)

from .css import APP_CSS
from .stream import (
    kitty_ansi_to_standard,
    strip_pi_input_chrome,
    trim_trailing_blank_lines,
)
from .widgets import ZeusDataTable, ZeusTextArea, UsageBar, SplashOverlay
from .screens import (
    NewAgentScreen,
    AgentTasksScreen,
    AgentMessageScreen,
    LastSentMessageScreen,
    ExpandedOutputScreen,
    DependencySelectScreen,
    SubAgentScreen,
    RenameScreen,
    RenameTmuxScreen,
    ConfirmKillScreen, ConfirmKillTmuxScreen, ConfirmPromoteScreen,
    BroadcastPreparingScreen,
    ConfirmBroadcastScreen,
    ConfirmDirectMessageScreen,
    HelpScreen,
)


@dataclass
class PollResult:
    """Data gathered by the background poll worker."""
    agents: list[AgentWindow] = field(default_factory=list)
    usage: UsageData = field(default_factory=UsageData)
    openai: OpenAIUsageData = field(default_factory=OpenAIUsageData)
    # State tracking deltas computed in the worker
    state_changed_at: dict[str, float] = field(default_factory=dict)
    prev_states: dict[str, State] = field(default_factory=dict)
    idle_since: dict[str, float] = field(default_factory=dict)
    idle_notified: set[str] = field(default_factory=set)


@dataclass
class QueueDeliveryTarget:
    """Resolved queue destination for transport delivery."""

    recipient_key: str
    label: str
    kind: str  # "agent" | "tmux"
    agent: AgentWindow | None = None
    tmux_session: str = ""


def _compact_name(name: str, maxlen: int) -> str:
    """Dash-aware truncation: preserve start + (preferably) end segment."""
    if maxlen <= 1:
        return "…" if name else ""
    if len(name) <= maxlen:
        return name

    parts = name.split("-")
    if len(parts) < 2:
        return name[: maxlen - 1] + "…"

    first, last = parts[0], parts[-1]
    budget = maxlen - 1  # reserve one char for ellipsis

    # If the full last segment fits with at least one char of prefix, keep it.
    if len(last) <= budget - 1:
        prefix_len = max(1, budget - len(last))
        return f"{first[:prefix_len]}…{last}"

    # Otherwise keep a tail slice from the last segment (bias toward tail info).
    suffix_len = min(len(last), max(3, (budget * 3) // 5))
    prefix_len = budget - suffix_len
    if budget >= 4 and prefix_len < 2:
        prefix_len = 2
        suffix_len = budget - prefix_len

    return f"{first[:prefix_len]}…{last[-suffix_len:]}"


def _middle_ellipsis(text: str, maxlen: int) -> str:
    """Clamp text to maxlen using a centered ellipsis."""
    if maxlen <= 0:
        return ""
    if len(text) <= maxlen:
        return text
    if maxlen == 1:
        return "…"
    left = (maxlen - 1) // 2
    right = maxlen - 1 - left
    return f"{text[:left]}…{text[-right:]}"


_MODEL_THINKING_RE = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")
_MODEL_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
_MODEL_FAMILY_ALIASES: dict[str, str] = {
    "opus": "op",
    "sonnet": "sn",
    "haiku": "hk",
    "gpt": "gpt",
    "gemini": "gem",
    "deepseek": "ds",
    "qwen": "qw",
}
_THINKING_SHORT: dict[str, str] = {
    "xhigh": "xh",
    "high": "h",
    "medium": "m",
    "med": "m",
    "low": "l",
}


def _is_model_number(token: str) -> bool:
    return bool(_MODEL_NUMBER_RE.fullmatch(token))


def _compact_model_label(model: str, maxlen: int) -> str:
    """Compact model labels to <family><version> with optional thinking.

    Examples:
      - "anthropic/claude-opus-4-5 (xhigh)" -> "op4.5 (xh)"
      - "openai/gpt-5-3-codex" -> "gpt5.3"
    """
    if maxlen <= 0:
        return ""

    raw = (model or "").strip()
    if not raw:
        return "—"

    thinking = ""
    base = raw
    think_match = _MODEL_THINKING_RE.match(raw)
    if think_match:
        base = think_match.group(1).strip()
        thinking = think_match.group(2).strip().lower()

    normalized = base.lower().replace("_", "-").strip()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    normalized = normalized.replace("claude-", "")
    normalized = normalized.removesuffix("-latest")
    normalized = normalized.removesuffix("-preview")
    normalized = normalized.strip("-")

    tokens = [t for t in normalized.split("-") if t]
    if not tokens:
        return _middle_ellipsis("—", maxlen)

    family = ""
    family_idx = -1
    for idx, token in enumerate(tokens):
        alias = _MODEL_FAMILY_ALIASES.get(token)
        if alias:
            family = alias
            family_idx = idx
            break

    if family_idx < 0:
        family = tokens[0]
        family_idx = 0

    version_tokens: list[str] = []
    for token in tokens[family_idx + 1 :]:
        if _is_model_number(token):
            version_tokens.append(token)
            continue
        if token.isdigit():
            version_tokens.append(token)
            continue
        # Keep at most one contiguous numeric run.
        if version_tokens:
            break

    version = ""
    if version_tokens:
        if len(version_tokens) >= 2 and all(t.isdigit() for t in version_tokens[:2]):
            version = f"{version_tokens[0]}.{version_tokens[1]}"
        else:
            version = version_tokens[0]

    base_label = f"{family}{version}" if version else family
    thinking_short = _THINKING_SHORT.get(thinking, thinking[:2] if thinking else "")
    if thinking_short:
        with_thinking = f"{base_label} ({thinking_short})"
        if len(with_thinking) <= maxlen:
            return with_thinking

    if len(base_label) <= maxlen:
        return base_label

    return _middle_ellipsis(base_label, maxlen)


_URL_RE = re.compile(r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+)")
_URL_TRAILING = ".,;:!?)]}"
_SHARE_MARKER = "%%%%"
_SHARE_FILE_LINE_RE = re.compile(r"ZEUS_MSG_FILE\s*=\s*(\S+)")
_SHARE_FILE_HINT_RE = re.compile(
    r"message\s+is\s+in\s+file\s+(\S+)",
    flags=re.IGNORECASE,
)
_TASK_PENDING_RE = re.compile(r"^(\s*-\s*)\[(?:\s*)\](\s*)(.*)$")
_TASK_HEADER_RE = re.compile(r"^\s*-\s*\[(?:\s*|[xX])\]\s*")


def _iter_url_ranges(text: str) -> list[tuple[int, int, str]]:
    """Find URL spans in plain text and return link targets."""
    out: list[tuple[int, int, str]] = []
    for m in _URL_RE.finditer(text):
        raw = m.group(0)
        trimmed = raw.rstrip(_URL_TRAILING)
        if not trimmed:
            continue
        start = m.start()
        end = start + len(trimmed)
        url = trimmed
        if url.startswith("www."):
            url = f"https://{url}"
        out.append((start, end, url))
    return out


def _linkify_rich_text(text: Text) -> Text:
    """Add clickable hyperlink styles for detected URLs in a Rich Text object."""
    for start, end, url in _iter_url_ranges(text.plain):
        action = f"app.open_url({url!r})"
        text.stylize(
            Style(link=url, underline=True, meta={"@click": action}),
            start,
            end,
        )
    return text


def _extract_share_payload(text: str) -> str | None:
    """Extract payload between the last complete pair of marker lines.

    Markers are lines that equal ``%%%%`` after stripping whitespace.

    Returns None if no complete marker pair exists.
    Returns empty string if pair exists but wrapped block is empty.
    """
    lines = text.splitlines()
    markers = [i for i, line in enumerate(lines) if line.strip() == _SHARE_MARKER]
    if len(markers) < 2:
        return None

    # If count is odd, ignore the trailing unmatched marker.
    if len(markers) % 2 == 1:
        markers = markers[:-1]
        if len(markers) < 2:
            return None

    start = markers[-2]
    end = markers[-1]
    if end <= start:
        return None

    return "\n".join(lines[start + 1:end]).strip()


def _normalize_share_file_candidate(candidate: str) -> str:
    return candidate.strip().strip("\"'").rstrip(".,;:)")


def _extract_share_file_path(text: str) -> str | None:
    """Extract the latest ZEUS_MSG_FILE path from text, if present."""
    for line in reversed(text.splitlines()):
        match = _SHARE_FILE_LINE_RE.search(line)
        if match is not None:
            return _normalize_share_file_candidate(match.group(1))
        hint_match = _SHARE_FILE_HINT_RE.search(line)
        if hint_match is not None:
            return _normalize_share_file_candidate(hint_match.group(1))
    return None


def _read_share_file_payload(path_text: str) -> str | None:
    """Read payload from configured temp-message directory path."""
    if not path_text:
        return None

    try:
        path = Path(os.path.expanduser(path_text)).resolve()
    except OSError:
        return None

    try:
        allowed_root = MESSAGE_TMP_DIR.resolve()
    except OSError:
        return None

    if path != allowed_root and allowed_root not in path.parents:
        return None

    if not path.is_file():
        return None

    try:
        return path.read_text()
    except OSError:
        return None


def _extract_next_task(task_text: str) -> tuple[str, str] | None:
    """Extract next task message from task text and return updated task text.

    Priority:
    1. First unchecked task block (``- []`` or ``- [ ]``), continuing until the
       next task header (unchecked or checked). The selected task is marked
       done in-place as ``- [x]``.
    2. If no checkbox task exists, consume the first non-empty line.
    """
    lines = task_text.splitlines()
    if not lines:
        return None

    pending_index: int | None = None
    pending_match: re.Match[str] | None = None
    for idx, line in enumerate(lines):
        match = _TASK_PENDING_RE.match(line)
        if match is None:
            continue
        pending_index = idx
        pending_match = match
        break

    if pending_index is not None and pending_match is not None:
        end = len(lines)
        for idx in range(pending_index + 1, len(lines)):
            if _TASK_HEADER_RE.match(lines[idx]):
                end = idx
                break

        block = lines[pending_index:end]
        first_content = pending_match.group(3)
        message_lines: list[str] = [first_content] if first_content else []
        message_lines.extend(line.rstrip() for line in block[1:])
        message = "\n".join(message_lines).strip()

        lines[pending_index] = (
            f"{pending_match.group(1)}[x]{pending_match.group(2)}{pending_match.group(3)}"
        )
        updated_task_text = "\n".join(lines).rstrip()
        return message, updated_task_text

    first_non_empty = next((idx for idx, line in enumerate(lines) if line.strip()), None)
    if first_non_empty is None:
        return None

    message = lines[first_non_empty].strip()
    del lines[first_non_empty]
    updated_task_text = "\n".join(lines).rstrip()
    return message, updated_task_text


def _with_tasks_column(order: tuple[str, ...]) -> tuple[str, ...]:
    """Ensure tasks indicator column exists directly after context column."""
    if "■" in order:
        return order
    if "◉" in order:
        idx = order.index("◉") + 1
        return order[:idx] + ("■",) + order[idx:]
    return order + ("■",)


def _format_ram_mb(ram_mb: float) -> str:
    """Render RAM in compact M/G units for narrow table columns."""
    if ram_mb >= 1000:
        gb = ram_mb / 1000.0
        if gb >= 10:
            return f"{gb:.0f}G"
        return f"{gb:.1f}".rstrip("0").rstrip(".") + "G"
    return f"{int(ram_mb)}M"


class ZeusApp(App):
    TITLE = "Zeus"
    DEFAULT_CSS = APP_CSS
    BINDINGS = [
        Binding("q", "stop_agent", "Stop Hippeus"),
        Binding("f10", "quit", "Quit"),
        Binding("tab", "toggle_focus", "Switch focus", show=False),
        Binding("ctrl+p", "promote_selected", "Promote", show=False, priority=True),
        Binding("ctrl+enter", "focus_agent", "Teleport", priority=True),
        Binding("ctrl+o", "open_shell_here", "Open shell", show=False, priority=True),
        Binding("z", "new_agent", "Invoke"),
        Binding("a", "toggle_aegis", "Aegis"),
        Binding("n", "queue_next_task", "Queue Task"),
        Binding("g", "go_ahead", "Go ahead"),
        Binding("t", "agent_tasks", "Tasks"),
        Binding("e", "expand_output", "Expand output", show=False),
        Binding("ctrl+t", "clear_done_tasks", "Clear done tasks", show=False, priority=True),
        Binding("ctrl+k", "kill_tmux_session", "Kill tmux", show=False),
        Binding("d", "toggle_dependency", "Dependency", show=False),
        Binding("s", "spawn_subagent", "Sub-Hippeus"),
        Binding("h", "message_history", "History", show=False),
        Binding("k", "kill_agent", "Kill Hippeus"),
        Binding("p", "cycle_priority", "Priority"),
        Binding("r", "rename", "Rename"),
        Binding("f5", "refresh", "Refresh", show=False),

        Binding("ctrl+s", "send_interact", "Send", show=False, priority=True),
        Binding("ctrl+w", "queue_interact", "Queue", show=False, priority=True),
        Binding("b", "broadcast_summary", "Broadcast", show=False),
        Binding("m", "direct_summary", "Direct Summary", show=False),
        Binding("y", "yank_summary_payload", "Yank", show=False),

        Binding("1", "toggle_interact_input", "Input", show=False, priority=True),
        Binding("2", "toggle_minimap", "Map", show=False, priority=True),
        Binding("3", "toggle_sparklines", "Sparks", show=False, priority=True),
        Binding("4", "toggle_target_band", "Target", show=False, priority=True),
        Binding("f4", "toggle_sort", "Sort"),
        Binding("f6", "toggle_split", "Split"),

        Binding("f8", "toggle_interact_panel", "Panel"),
        Binding("question_mark", "show_help", "?", key_display="?"),
    ]

    _AEGIS_MODE_ARMED = "ARMED"
    _AEGIS_MODE_PENDING_DELAY = "PENDING_DELAY"
    _AEGIS_MODE_POST_CHECK = "POST_CHECK"
    _AEGIS_MODE_HALTED = "HALTED"
    _AEGIS_DELAY_S = 5.0
    _AEGIS_CHECK_S = 60.0
    _AEGIS_ROW_BG = "#ff69b4"
    _AEGIS_ROW_BG_DIM = "#a35c82"
    _BLOCKED_ROW_FG = "#f2e6a7"
    _BLOCKED_NON_STATE_FG = "#666666"
    _AEGIS_PROMPT = (
        "Continue now unless there is a decision here for me to make. "
        "If you decide to continue, save a report in /reports, with an "
        "explanation of why you stopped in first place, and why you "
        "decided to continue without my input on this matter."
    )
    _CELEBRATION_COOLDOWN_S = 3600.0

    agents: list[AgentWindow] = []
    sort_mode: SortMode = SortMode.PRIORITY
    _agent_priorities: dict[str, int] = {}
    _split_mode: bool = True
    _interact_visible: bool = True
    _highlight_timer: Timer | None = None
    _interact_agent_key: str | None = None
    _interact_tmux_name: str | None = None
    _interact_drafts: dict[str, str] = {}
    _action_check_pending: set[str] = set()
    _action_needed: set[str] = set()
    _dopamine_armed: bool = True
    _steady_armed: bool = True
    _celebration_cooldown_started_at: float | None = None
    _sparkline_samples: dict[str, list[str]] = {}  # agent_name → state labels
    _screen_activity_sig: dict[str, str] = {}  # key -> normalized screen signature
    _show_interact_input: bool = True
    _show_minimap: bool = True
    _show_sparklines: bool = True
    _show_target_band: bool = True
    _minimap_agents: list[str] = []
    prev_states: dict[str, State] = {}
    state_changed_at: dict[str, float] = {}
    idle_since: dict[str, float] = {}
    idle_notified: set[str] = set()
    _history_nav_target: str | None = None
    _history_nav_index: int | None = None
    _history_nav_draft: str | None = None
    _broadcast_job_seq: int = 0
    _broadcast_active_job: int | None = None
    _prepare_target_selection: dict[int, str] = {}
    _agent_tasks: dict[str, str] = {}
    _agent_message_drafts: dict[str, str] = {}
    _pending_polemarch_bootstraps: dict[str, str] = {}
    _agent_dependencies: dict[str, str] = {}
    _dependency_missing_polls: dict[str, int] = {}
    _message_queue_draining: bool = False
    _message_queue_inflight_lease_s: float = 30.0
    _message_queue_backoff_max_s: float = 30.0
    _message_receipts_ttl_s: float = 24 * 3600.0
    _message_receipts: dict[str, dict[str, float]] = {}
    _message_queue_watch_thread: threading.Thread | None = None
    _message_queue_watch_stop: threading.Event | None = None
    _message_queue_inotify_proc: subprocess.Popen[str] | None = None
    _message_queue_inotify_enabled: bool = False
    _aegis_enabled: set[str] = set()
    _aegis_modes: dict[str, str] = {}
    _aegis_delay_timers: dict[str, Timer] = {}
    _aegis_check_timers: dict[str, Timer] = {}
    _notifications_enabled: bool = os.environ.get("ZEUS_NOTIFY", "").lower() in {
        "1", "true", "yes", "on",
    }

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Horizontal(
                    Label("⚡ Zeus", id="title-text"),
                    Static("", id="title-clock"),
                    id="title-bar",
                ),
                Horizontal(
                    UsageBar("Claude Session:", classes="usage-item", id="usage-session"),
                    UsageBar("Week:", classes="usage-item", id="usage-week"),
                    id="usage-bar",
                ),
                Horizontal(
                    UsageBar("OpenAI Session:", classes="usage-item", id="openai-session"),
                    UsageBar("Week:", classes="usage-item", id="openai-week"),
                    id="openai-usage-bar",
                ),
                Static("", id="mini-map"),
                Static("", id="sparkline-chart"),
                ZeusDataTable(
                    id="agent-table",
                    cursor_foreground_priority="renderable",
                    cursor_background_priority="renderable",
                    fixed_columns=SETTINGS.columns.fixed,
                ),
                id="table-container",
            ),
            Vertical(
                RichLog(id="interact-stream", wrap=True, markup=False, auto_scroll=True),
                ZeusTextArea(
                    "",
                    id="interact-input",
                ),
                Static("—", id="interact-target"),
                id="interact-panel",
                classes="visible split",
            ),
            id="main-content",
            classes="split",
        )
        yield Static("", id="status-line")
        yield SplashOverlay(id="splash")

    _FULL_COLUMNS = _with_tasks_column(SETTINGS.columns.wide.order)
    _SPLIT_COLUMNS = _with_tasks_column(SETTINGS.columns.split.order)
    _COL_WIDTHS: dict[str, int] = dict(SETTINGS.columns.wide.widths)
    _COL_WIDTHS.setdefault("■", 1)
    _COL_WIDTHS.setdefault("RAM", 4)
    _COL_WIDTHS_SPLIT: dict[str, int] = dict(SETTINGS.columns.split.widths)
    _COL_WIDTHS_SPLIT.setdefault("■", 1)
    _COL_WIDTHS_SPLIT.setdefault("RAM", 4)

    def _setup_table_columns(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.clear(columns=True)
        cols = self._SPLIT_COLUMNS if self._split_mode else self._FULL_COLUMNS
        for col in cols:
            widths = self._COL_WIDTHS_SPLIT if self._split_mode else self._COL_WIDTHS
            w = widths.get(col)
            if w is not None:
                table.add_column(col, width=w)
            else:
                table.add_column(col)

    def on_mount(self) -> None:
        ensure_tmux_update_environment()
        ensure_tmux_update_environment("ZEUS_ROLE")
        self._load_priorities()
        self._load_agent_tasks()
        self._load_agent_dependencies()
        self._load_panel_visibility()
        self._celebration_cooldown_started_at = time.time()
        table = self.query_one("#agent-table", DataTable)
        table.show_row_labels = False
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.query_one("#interact-stream", RichLog).can_focus = False
        self._setup_table_columns()
        self._apply_panel_visibility()
        ensure_queue_dirs()
        self._message_receipts = load_message_receipts()
        self._drain_message_queue()
        self._start_message_queue_watcher()
        self.poll_and_update()
        self.set_interval(SETTINGS.poll_interval, self.poll_and_update)
        self.set_interval(1.0, self.update_clock)
        self.set_interval(1.0, self._update_interact_stream)
        self.set_interval(1.0, self._drain_message_queue)

    def on_unmount(self, event: events.Unmount) -> None:
        self._stop_message_queue_watcher()

    def _start_message_queue_watcher(self) -> None:
        if self._message_queue_watch_thread and self._message_queue_watch_thread.is_alive():
            return

        if shutil.which("inotifywait") is None:
            self._message_queue_inotify_enabled = False
            return

        stop_event = threading.Event()
        self._message_queue_watch_stop = stop_event
        self._message_queue_inotify_enabled = True

        thread = threading.Thread(
            target=self._message_queue_watch_loop,
            args=(stop_event,),
            name="zeus-msg-watch",
            daemon=True,
        )
        self._message_queue_watch_thread = thread
        thread.start()

    def _stop_message_queue_watcher(self) -> None:
        if self._message_queue_watch_stop is not None:
            self._message_queue_watch_stop.set()

        proc = self._message_queue_inotify_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                pass

        thread = self._message_queue_watch_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)

        self._message_queue_watch_thread = None
        self._message_queue_watch_stop = None
        self._message_queue_inotify_proc = None

    def _message_queue_watch_loop(self, stop_event: threading.Event) -> None:
        cmd = [
            "inotifywait",
            "-m",
            "-q",
            "-e",
            "create",
            "-e",
            "moved_to",
            "--format",
            "%w%f",
            str(queue_new_dir()),
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            self._message_queue_inotify_enabled = False
            return

        self._message_queue_inotify_proc = proc
        try:
            out = proc.stdout
            if out is None:
                return
            for _line in out:
                if stop_event.is_set():
                    break
                self.call_from_thread(self._drain_message_queue)
        finally:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
            self._message_queue_inotify_proc = None

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        """Disable toast notifications unless ZEUS_NOTIFY is enabled."""
        if not self._notifications_enabled:
            return
        super().notify(
            message,
            title=title,
            severity=severity,
            timeout=timeout,
            markup=markup,
        )

    def notify_force(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "warning",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        """Show a notification even when ZEUS_NOTIFY is disabled."""
        super().notify(
            message,
            title=title,
            severity=severity,
            timeout=timeout,
            markup=markup,
        )

    @staticmethod
    def _copy_text_to_system_clipboard(text: str) -> bool:
        """Best-effort clipboard copy via wl-copy.

        Some wl-copy setups daemonize and can outlive the caller. We treat a
        short timeout while waiting as success after stdin is written.
        """
        if shutil.which("wl-copy") is None:
            return False

        try:
            proc = subprocess.Popen(
                ["wl-copy"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
        except OSError:
            return False

        if proc.stdin is None:
            return False

        try:
            proc.stdin.write(text)
            proc.stdin.close()
        except (OSError, ValueError):
            try:
                proc.kill()
            except OSError:
                pass
            return False

        try:
            proc.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            return True

        return proc.returncode == 0

    def _pulse_widget(self, selector: str, low_opacity: float) -> None:
        """Run a clearly-visible single-beat opacity pulse on a widget."""
        try:
            widget = self.query_one(selector, Widget)
        except LookupError:
            return

        down = 0.14
        up = 0.24

        widget.styles.opacity = 1.0
        widget.styles.animate(
            "opacity",
            low_opacity,
            duration=down,
            easing="out_cubic",
        )
        self.set_timer(
            down,
            lambda w=widget: w.styles.animate(
                "opacity",
                1.0,
                duration=up,
                easing="in_out_cubic",
            ),
        )

    def _pulse_agent_table(self) -> None:
        self._pulse_widget("#agent-table", low_opacity=0.60)

    def update_clock(self) -> None:
        clock = self.query_one("#title-clock", Static)
        clock.update(f"  {time.strftime('%H:%M:%S')}")

    def poll_and_update(self) -> None:
        """Kick off background data gathering."""
        self._poll_worker()

    @work(thread=True, exclusive=True, group="poll")
    def _poll_worker(self) -> None:
        """Gather all data in a background thread (no UI access)."""
        agents = discover_agents()
        pid_ws: dict[int, str] = build_pid_workspace_map()
        tmux_sessions: list[TmuxSession] = discover_tmux_sessions()
        hidden_agents, visible_tmux_sessions = discover_hidden_agents(
            tmux_sessions,
            name_overrides=load_names(),
        )
        agents.extend(hidden_agents)

        usage = read_usage()
        openai = read_openai_usage()

        # Activity fallback: if content keeps changing without spinner,
        # treat as WORKING until output stabilizes.
        screen_activity_sig = dict(self._screen_activity_sig)

        for a in agents:
            agent_key = self._agent_key(a)
            # Use full extent so state detection isn't affected by manual
            # scrolling/focus changes in the terminal viewport.
            screen: str = self._read_agent_screen_text(a, full=True)
            a._screen_text = screen

            coarse = detect_state(screen)
            sig = activity_signature(screen)
            old_sig = screen_activity_sig.get(agent_key)
            sig_changed = (
                old_sig is not None
                and old_sig != sig
                and bool(old_sig or sig)
            )
            a.state = (
                State.WORKING
                if coarse == State.IDLE and sig_changed
                else coarse
            )
            screen_activity_sig[agent_key] = sig

            a.model, a.ctx_pct, a.tokens_in, a.tokens_out = parse_footer(
                screen
            )
            a.workspace = pid_ws.get(a.kitty_pid, "?")
            metrics_root_pid = a.pid if a.pid > 0 else a.kitty_pid
            a.proc_metrics = read_process_metrics(metrics_root_pid)

        # Read tmux pane metrics in the worker too
        match_tmux_to_agents(agents, visible_tmux_sessions)
        backfill_tmux_owner_options(agents)
        for a in agents:
            for sess in a.tmux_sessions:
                if sess.pane_pid:
                    sess._proc_metrics = read_process_metrics(sess.pane_pid)

        # Compute state tracking (uses mutable app state, but exclusive
        # guarantees only one worker touches these at a time)
        now: float = time.time()
        state_changed_at = dict(self.state_changed_at)
        prev_states = dict(self.prev_states)
        idle_since = dict(self.idle_since)
        idle_notified = set(self.idle_notified)

        for a in agents:
            akey: str = self._agent_key(a)
            old: State | None = prev_states.get(akey)
            if akey not in state_changed_at:
                state_changed_at[akey] = now
            elif old is not None and old != a.state:
                state_changed_at[akey] = now

            if a.state == State.IDLE:
                if old == State.WORKING:
                    idle_since[akey] = now
                    idle_notified.discard(akey)
            else:
                idle_since.pop(akey, None)
                idle_notified.discard(akey)
            prev_states[akey] = a.state

        live_keys = {self._agent_key(a) for a in agents}
        state_changed_at = {
            k: v for k, v in state_changed_at.items() if k in live_keys
        }
        prev_states = {
            k: v for k, v in prev_states.items() if k in live_keys
        }
        idle_since = {k: v for k, v in idle_since.items() if k in live_keys}
        idle_notified &= live_keys
        self._screen_activity_sig = {
            k: v for k, v in screen_activity_sig.items() if k in live_keys
        }

        result = PollResult(
            agents=agents,
            usage=usage,
            openai=openai,
            state_changed_at=state_changed_at,
            prev_states=prev_states,
            idle_since=idle_since,
            idle_notified=idle_notified,
        )
        self.call_from_thread(self._apply_poll_result, result)

    def _apply_poll_result(self, r: PollResult) -> None:
        """Apply gathered data to the UI (runs on the main thread)."""
        old_states = self.prev_states
        self._commit_poll_state(r)
        self._deliver_pending_polemarch_bootstraps()

        state_changed_any = self._any_agent_state_changed(old_states)
        self._update_action_needed(old_states)
        self._process_aegis_state_transitions(old_states)
        self._collect_sparkline_samples()
        self._refresh_interact_if_state_changed(old_states)
        self._update_usage_bars(r.usage, r.openai)

        if not self._render_agent_table_and_status():
            return

        if state_changed_any:
            self._pulse_agent_table()


    def _commit_poll_state(self, result: PollResult) -> None:
        self.agents = result.agents
        self.prev_states = result.prev_states
        self.state_changed_at = result.state_changed_at
        self.idle_since = result.idle_since
        self.idle_notified = result.idle_notified
        self._reconcile_agent_dependencies()
        self._prune_interact_histories()

    def _any_agent_state_changed(self, old_states: dict[str, State]) -> bool:
        return any(
            (
                old_states.get(self._agent_key(a)) is not None
                and old_states.get(self._agent_key(a)) != a.state
            )
            for a in self.agents
        )

    def _update_action_needed(self, old_states: dict[str, State]) -> None:
        # Action-needed checks:
        # - when an agent transitions WORKING -> IDLE
        # - once when an agent is first seen already IDLE (startup/new window)
        live_keys: set[str] = set()
        for a in self.agents:
            key = self._agent_key(a)
            live_keys.add(key)

            if self._is_input_blocked(a):
                self._action_check_pending.discard(key)
                self._action_needed.discard(key)
                continue

            old_state = old_states.get(key)
            just_became_idle = old_state == State.WORKING and a.state == State.IDLE
            first_seen_idle = old_state is None and a.state == State.IDLE
            if (just_became_idle or first_seen_idle) and key not in self._action_check_pending:
                self._action_check_pending.add(key)
                self._check_action_needed(a, key)
            elif a.state == State.WORKING:
                self._action_check_pending.discard(key)
                self._action_needed.discard(key)

        self._action_check_pending &= live_keys
        self._action_needed &= live_keys

    def _cancel_aegis_delay_timer(self, key: str) -> None:
        timer = self._aegis_delay_timers.pop(key, None)
        if timer is not None:
            timer.stop()

    def _cancel_aegis_check_timer(self, key: str) -> None:
        timer = self._aegis_check_timers.pop(key, None)
        if timer is not None:
            timer.stop()

    def _disable_aegis(self, key: str) -> None:
        self._aegis_enabled.discard(key)
        self._aegis_modes.pop(key, None)
        self._cancel_aegis_delay_timer(key)
        self._cancel_aegis_check_timer(key)

    @staticmethod
    def _state_ui_color(label: str) -> str:
        palette = {
            "WORKING": SETTINGS.state_colors.working,
            "WAITING": SETTINGS.state_colors.waiting,
            "IDLE": SETTINGS.state_colors.idle,
        }
        return palette.get(label, "#666666")

    @staticmethod
    def _scale_hex_color(hex_color: str, factor: float) -> str:
        value = hex_color.lstrip("#")
        if len(value) != 6:
            return "#666666"
        try:
            r = int(value[0:2], 16)
            g = int(value[2:4], 16)
            b = int(value[4:6], 16)
        except ValueError:
            return "#666666"

        f = max(0.0, min(1.0, factor))
        rr = max(0, min(255, int(r * f)))
        gg = max(0, min(255, int(g * f)))
        bb = max(0, min(255, int(b * f)))
        return f"#{rr:02x}{gg:02x}{bb:02x}"

    @classmethod
    def _state_minimap_priority_colors(cls, label: str) -> tuple[str, str, str, str]:
        base = cls._state_ui_color(label)
        return (
            base,
            cls._scale_hex_color(base, 0.45),
            cls._scale_hex_color(base, 0.25),
            cls._scale_hex_color(base, 0.15),
        )

    def _aegis_state_bg(self, key: str) -> str:
        if key not in self._aegis_enabled:
            return "#000000"
        mode = self._aegis_modes.get(key, self._AEGIS_MODE_ARMED)
        if mode == self._AEGIS_MODE_HALTED:
            return self._AEGIS_ROW_BG_DIM
        return self._AEGIS_ROW_BG

    def _is_aegis_waiting(self, key: str, agent: AgentWindow) -> bool:
        return agent.state == State.IDLE and key in self._action_needed

    def _is_aegis_idle_or_waiting(self, key: str, agent: AgentWindow) -> bool:
        return agent.state == State.IDLE or self._is_aegis_waiting(key, agent)

    def _reconcile_aegis_agents(self, live_keys: set[str]) -> None:
        live_agents_by_key = {self._agent_key(agent): agent for agent in self.agents}
        for key in list(self._aegis_enabled):
            if key not in live_keys:
                self._disable_aegis(key)
                continue

            agent = live_agents_by_key.get(key)
            if agent is None:
                self._disable_aegis(key)
                continue

            if self._is_input_blocked(agent):
                self._disable_aegis(key)

    def _process_aegis_state_transitions(self, old_states: dict[str, State]) -> None:
        live_keys = {self._agent_key(agent) for agent in self.agents}
        self._reconcile_aegis_agents(live_keys)

        for agent in self.agents:
            key = self._agent_key(agent)
            if key not in self._aegis_enabled:
                continue

            mode = self._aegis_modes.get(key, self._AEGIS_MODE_ARMED)
            if mode != self._AEGIS_MODE_ARMED:
                continue

            old_state = old_states.get(key)
            if old_state != State.WORKING:
                continue
            if not self._is_aegis_idle_or_waiting(key, agent):
                continue

            self._aegis_modes[key] = self._AEGIS_MODE_PENDING_DELAY
            self._cancel_aegis_delay_timer(key)
            self._aegis_delay_timers[key] = self.set_timer(
                self._AEGIS_DELAY_S,
                lambda key=key: self._on_aegis_delay_elapsed(key),
            )

    def _on_aegis_delay_elapsed(self, key: str) -> None:
        self._aegis_delay_timers.pop(key, None)

        if key not in self._aegis_enabled:
            return
        if self._aegis_modes.get(key) != self._AEGIS_MODE_PENDING_DELAY:
            return

        agent = self._get_agent_by_key(key)
        if agent is None:
            self._disable_aegis(key)
            return

        if agent.state == State.WORKING:
            self._aegis_modes[key] = self._AEGIS_MODE_ARMED
            return

        if not self._is_aegis_idle_or_waiting(key, agent):
            self._aegis_modes[key] = self._AEGIS_MODE_HALTED
            return

        self._send_text_to_agent(agent, self._AEGIS_PROMPT)
        self._aegis_modes[key] = self._AEGIS_MODE_POST_CHECK
        self._cancel_aegis_check_timer(key)
        self._aegis_check_timers[key] = self.set_timer(
            self._AEGIS_CHECK_S,
            lambda key=key: self._on_aegis_check_elapsed(key),
        )

    def _on_aegis_check_elapsed(self, key: str) -> None:
        self._aegis_check_timers.pop(key, None)

        if key not in self._aegis_enabled:
            return
        if self._aegis_modes.get(key) != self._AEGIS_MODE_POST_CHECK:
            return

        agent = self._get_agent_by_key(key)
        if agent is None:
            self._disable_aegis(key)
            return

        if agent.state == State.WORKING:
            self._aegis_modes[key] = self._AEGIS_MODE_ARMED
            return

        self._aegis_modes[key] = self._AEGIS_MODE_HALTED

    def _collect_sparkline_samples(self) -> None:
        max_samples = SETTINGS.sparkline.max_samples
        live_names: set[str] = set()
        for a in self.agents:
            if self._is_input_blocked(a):
                continue  # paused/blocked agents are excluded from statistics
            akey = self._agent_key(a)
            live_names.add(a.name)
            waiting = a.state == State.IDLE and akey in self._action_needed
            state_label = "WAITING" if waiting else a.state.value.upper()
            samples = self._sparkline_samples.setdefault(a.name, [])
            samples.append(state_label)
            if len(samples) > max_samples:
                del samples[: len(samples) - max_samples]

        for name in list(self._sparkline_samples):
            if name not in live_names:
                del self._sparkline_samples[name]

    def _refresh_interact_if_state_changed(self, old_states: dict[str, State]) -> None:
        if not self._interact_visible or not self._interact_agent_key:
            return

        key = self._interact_agent_key
        old_state = old_states.get(key)
        new_state = self.prev_states.get(key)
        if old_state is None or new_state is None:
            return
        if old_state != new_state:
            self._refresh_interact_panel()

    def _update_usage_bars(
        self,
        usage: UsageData,
        openai: OpenAIUsageData,
    ) -> None:
        sess_bar = self.query_one("#usage-session", UsageBar)
        week_bar = self.query_one("#usage-week", UsageBar)
        if usage.available:
            sess_bar.pct = usage.session_pct
            sess_left = time_left(usage.session_resets_at)
            sess_bar.extra_text = f"({sess_left})" if sess_left else ""

            week_bar.pct = usage.week_pct
            week_left = time_left(usage.week_resets_at)
            week_bar.extra_text = f"({week_left})" if week_left else ""
        else:
            sess_bar.pct = 0
            sess_bar.extra_text = "(unavailable)"
            week_bar.pct = 0
            week_bar.extra_text = ""

        o_sess = self.query_one("#openai-session", UsageBar)
        o_week = self.query_one("#openai-week", UsageBar)
        if openai.available:
            o_sess.pct = openai.requests_pct
            left = time_left(openai.requests_resets_at)
            o_sess.extra_text = f"({left})" if left else ""
            o_week.pct = openai.tokens_pct
            week_left_openai = time_left(openai.tokens_resets_at)
            o_week.extra_text = f"({week_left_openai})" if week_left_openai else ""
        else:
            o_sess.pct = 0
            o_sess.extra_text = "(unavailable)"
            o_week.pct = 0
            o_week.extra_text = ""

    def _render_agent_table_and_status(self) -> bool:
        # Update table
        table = self.query_one("#agent-table", DataTable)
        _saved_key: str | None = self._get_selected_row_key()
        table.clear()

        if not self.agents:
            status = self.query_one("#status-line", Static)
            status.update(
                "  No tracked Hippeis — press [bold]z[/] to invoke one, "
                "or open a terminal with $mod+Return and type a name"
            )
            return False

        # Separate top-level/sub-agent tree and blocked-dependency tree.
        parent_ids: set[str] = {a.agent_id for a in self.agents if a.agent_id}

        blocked_by_key: dict[str, str] = {}
        blocked_of: dict[str, list[AgentWindow]] = {}
        for a in self.agents:
            blocked_key = self._agent_dependency_key(a)
            blocker_dep_key = self._agent_dependencies.get(blocked_key)
            if not blocker_dep_key:
                continue
            blocker = self._agent_by_dependency_key(blocker_dep_key)
            if blocker is None:
                continue
            blocker_row_key = self._agent_key(blocker)
            blocked_row_key = self._agent_key(a)
            if blocker_row_key == blocked_row_key:
                continue
            blocked_by_key[blocked_row_key] = blocker_row_key
            blocked_of.setdefault(blocker_row_key, []).append(a)

        top_level: list[AgentWindow] = []
        for agent in self.agents:
            if self._agent_key(agent) in blocked_by_key:
                continue
            parent_id = (agent.parent_id or "").strip()
            if (not parent_id) or (parent_id not in parent_ids):
                top_level.append(agent)

        children_of: dict[str, list[AgentWindow]] = {}
        for agent in self.agents:
            if self._agent_key(agent) in blocked_by_key:
                continue
            parent_id = (agent.parent_id or "").strip()
            if parent_id and parent_id in parent_ids:
                children_of.setdefault(parent_id, []).append(agent)

        def _priority_sort_key(
            a: AgentWindow,
        ) -> tuple[int, int, float, str]:
            # Priority first (1=high … 4=paused)
            p = self._get_priority(a.name)
            # State: WAITING (0) → WORKING (1) → IDLE (2) → BLOCKED (3) → PAUSED (4)
            akey: str = self._agent_key(a)
            if self._is_blocked(a):
                st = 3
            elif self._is_paused(a):
                st = 4
            elif a.state == State.IDLE and akey in self._action_needed:
                st = 0  # WAITING
            elif a.state == State.WORKING:
                st = 1
            else:
                st = 2  # IDLE

            changed_at: float = self.state_changed_at.get(akey, time.time())
            # For IDLE ties, newer-idle first and longer-idle lower.
            # This keeps stale idle agents at the bottom of their
            # priority+state bucket.
            if st == 2:
                idle_at = self.idle_since.get(akey, changed_at)
                time_key = -idle_at
            else:
                time_key = changed_at

            return (p, st, time_key, a.name.lower())

        def _alpha_sort_key(a: AgentWindow) -> str:
            return a.name.lower()

        sort_key = (
            _alpha_sort_key
            if self.sort_mode == SortMode.ALPHA
            else _priority_sort_key
        )
        top_level.sort(key=sort_key)
        for kids in children_of.values():
            kids.sort(key=sort_key)
        for blocked in blocked_of.values():
            blocked.sort(key=sort_key)

        def _fmt_duration(seconds: float) -> str:
            s = int(seconds)
            if s < 60:
                return f"{s}s"
            if s < 3600:
                return f"{s // 60}m"
            if s < 86400:
                return f"{s // 3600}h{(s % 3600) // 60}m"
            return f"{s // 86400}d{(s % 86400) // 3600}h"

        from .widgets import _gradient_color, _tmux_metric_gradient_color

        def _ctx_gauge(pct: float) -> Text:
            """Single-character circular context gauge with gradient color."""
            p = max(0.0, min(100.0, pct))
            if p < 12.5:
                ch = "○"
            elif p < 37.5:
                ch = "◔"
            elif p < 62.5:
                ch = "◑"
            elif p < 87.5:
                ch = "◕"
            else:
                ch = "●"
            return Text(ch, style=f"bold {_gradient_color(p)}")

        column_widths = self._COL_WIDTHS_SPLIT if self._split_mode else self._COL_WIDTHS
        state_col_width = column_widths.get("State", 10)
        model_col_width = column_widths.get("Model/Cmd", 21)

        def _add_agent_row(
            a: AgentWindow,
            indent_level: int = 0,
            relation_icon: str | None = None,
        ) -> None:
            akey: str = self._agent_key(a)
            blocked: bool = self._is_blocked(a)
            paused: bool = self._is_paused(a)
            hidden: bool = self._is_hidden_agent(a)
            waiting: bool = (
                (not paused)
                and (not blocked)
                and a.state == State.IDLE
                and akey in self._action_needed
            )
            state_bg = self._aegis_state_bg(akey)

            if blocked:
                icon = "└"
                state_label = "BLOCKED"
                state_color = self._BLOCKED_ROW_FG
                row_style = self._BLOCKED_NON_STATE_FG
            elif paused:
                icon = "⏸"
                state_label = "PAUSED"
                state_color = "#666666"
                row_style = "#666666"
            elif waiting:
                icon = "⏸"
                state_label = "WAITING"
                state_color = self._state_ui_color("WAITING")
                row_style = ""
            elif a.state == State.WORKING:
                icon = "▶"
                state_label = "WORKING"
                state_color = self._state_ui_color("WORKING")
                row_style = ""
            else:
                icon = "⏹"
                state_label = "IDLE"
                state_color = self._state_ui_color("IDLE")
                row_style = ""

            hoplite_count = sum(
                1
                for sess in a.tmux_sessions
                if self._is_hoplite_session_for(a, sess)
            )
            agent_role = (a.role or "").strip().lower()
            is_polemarch_display = agent_role == "polemarch"
            role_marker = "⌁ " if is_polemarch_display else ""
            hidden_marker = "◆ " if hidden else ""
            phalanx_marker = (
                f" [phalanx: {hoplite_count}]" if is_polemarch_display else ""
            )

            if indent_level > 0:
                branch_prefix = f"{'  ' * indent_level}└ "
                if relation_icon:
                    raw_name = (
                        f"{branch_prefix}{relation_icon} "
                        f"{hidden_marker}{role_marker}{a.name}{phalanx_marker}"
                    )
                else:
                    raw_name = (
                        f"{branch_prefix}{hidden_marker}{role_marker}"
                        f"{a.name}{phalanx_marker}"
                    )
            else:
                raw_name = f"{hidden_marker}{role_marker}{a.name}{phalanx_marker}"

            # Always use Text so bracketed labels like "[phalanx: N]" render
            # literally and are not parsed as Rich markup tags.
            name_text = Text(raw_name, style=row_style or "")
            state_cell = f"{icon} {state_label}".ljust(state_col_width)
            state_text = Text(
                state_cell,
                style=f"bold {state_color} on {state_bg}",
            )
            elapsed: float = time.time() - self.state_changed_at.get(
                akey, time.time()
            )
            elapsed_text: str | Text = _fmt_duration(elapsed)
            ctx_cell: str | Text = _ctx_gauge(a.ctx_pct) if a.ctx_pct else "—"
            tok_cell: str | Text = (
                f"↑{a.tokens_in} ↓{a.tokens_out}" if a.tokens_in else "—"
            )
            task_cell: str | Text = (
                Text("■", style="bold #ffaf00")
                if self._has_task_for_agent(a)
                else Text("□", style="#555555")
            )

            pm = a.proc_metrics
            cpu_pct = max(0.0, pm.cpu_pct)
            cpu_label = f"{cpu_pct:.0f}%"
            if cpu_pct <= 0:
                cpu_cell: str | Text = cpu_label
            else:
                cpu_cell = Text(cpu_label, style=_gradient_color(cpu_pct))

            ram_cell: str | Text = _format_ram_mb(pm.ram_mb)

            gpu_pct = max(0.0, pm.gpu_pct)
            gpu_str: str = f"{gpu_pct:.0f}%"
            if pm.gpu_mem_mb > 0:
                gpu_str += f" {pm.gpu_mem_mb:.0f}M"
            if gpu_pct <= 0:
                gpu_cell: str | Text = gpu_str
            else:
                gpu_cell = Text(gpu_str, style=_gradient_color(gpu_pct))

            net_cell: str | Text = (
                f"↓{fmt_bytes(pm.io_read_bps)} "
                f"↑{fmt_bytes(pm.io_write_bps)}"
            )

            if row_style:
                elapsed_text = Text(str(elapsed_text), style=row_style)
                ctx_cell = Text(str(ctx_cell), style=row_style)
                cpu_cell = Text(str(cpu_cell), style=row_style)
                ram_cell = Text(str(ram_cell), style=row_style)
                gpu_cell = Text(str(gpu_cell), style=row_style)
                net_cell = Text(str(net_cell), style=row_style)
                tok_cell = Text(str(tok_cell), style=row_style)
                task_cell = Text(str(task_cell), style=row_style)

            pri_val = self._get_priority(a.name)
            _pri_colors = {1: "#ffffff", 2: "#999999", 3: "#555555", 4: "#333333"}
            pri_style = row_style or _pri_colors[pri_val]
            pri_cell: str | Text = Text(
                str(pri_val), style=f"bold {pri_style}",
            )

            row_key: str = akey
            cells: dict[str, str | Text] = {
                "State": state_text,
                "P": pri_cell,
                "◉": ctx_cell,
                "■": task_cell,
                "Name": name_text,
                "Elapsed": elapsed_text,
                "Model/Cmd": (
                    Text(_compact_model_label(a.model or "—", model_col_width), style=row_style)
                    if row_style
                    else _compact_model_label(a.model or "—", model_col_width)
                ),
                "CPU": cpu_cell,
                "RAM": ram_cell,
                "GPU": gpu_cell,
                "Net": net_cell,
                "WS": Text(a.workspace or "?", style=row_style) if row_style else (a.workspace or "?"),
                "CWD": Text(a.cwd, style=row_style) if row_style else a.cwd,
                "Tokens": tok_cell,
            }
            cols = self._SPLIT_COLUMNS if self._split_mode else self._FULL_COLUMNS
            row = [cells.get(c, "") for c in cols]
            table.add_row(*row, key=row_key)

        def _clean_tmux_cmd(cmd: str) -> str:
            """Strip 'cd ... &&' prefix and surrounding quotes."""
            import re
            c: str = cmd.strip().strip('"').strip("'")
            # Remove leading "cd /path &&" or "cd /path;"
            c = re.sub(r'^cd\s+\S+\s*(?:&&|;)\s*', '', c)
            return c[:40] or "—"

        def _add_tmux_rows(a: AgentWindow, indent_level: int = 1) -> None:
            def _add_tmux_session_row(sess: TmuxSession, *, prefix: str) -> None:
                age_s: int = int(time.time()) - sess.created if sess.created else 0
                age_str = _fmt_duration(float(age_s))

                tmux_name: str | Text
                tmux_cmd: str | Text
                tmux_age: str | Text
                cleaned_cmd: str = _clean_tmux_cmd(sess.command)
                cpu_t: str | Text = ""
                ram_t: str | Text = ""
                gpu_t: str | Text = ""
                net_t: str | Text = ""
                pm = getattr(sess, '_proc_metrics', None)
                if pm:
                    cpu_pct = max(0.0, pm.cpu_pct)
                    cpu_label = f"{cpu_pct:.0f}%"
                    cpu_t = Text(cpu_label, style=_tmux_metric_gradient_color(cpu_pct))

                    ram_t = _format_ram_mb(pm.ram_mb)

                    gpu_pct = max(0.0, pm.gpu_pct)
                    gpu_str: str = f"{gpu_pct:.0f}%"
                    if pm.gpu_mem_mb > 0:
                        gpu_str += f" {pm.gpu_mem_mb:.0f}M"
                    gpu_t = Text(gpu_str, style=_tmux_metric_gradient_color(gpu_pct))

                    net_str: str = (
                        f"↓{fmt_bytes(pm.io_read_bps)} "
                        f"↑{fmt_bytes(pm.io_write_bps)}"
                    )
                    net_t = net_str

                if sess.attached:
                    tmux_name = f"{prefix}{sess.name}"
                    tmux_cmd = cleaned_cmd
                    tmux_age = age_str
                else:
                    dim: str = "#777777"
                    tmux_name = Text(f"{prefix}{sess.name}", style=dim)
                    tmux_cmd = Text(cleaned_cmd, style=dim)
                    tmux_age = Text(age_str, style=dim)

                    # Keep CPU/GPU heat colors visible even for detached sessions;
                    # only dim plain fallback text when no metric style is present.
                    if isinstance(cpu_t, str):
                        cpu_t = Text(cpu_t, style=dim) if cpu_t else ""
                    ram_t = Text(str(ram_t), style=dim) if str(ram_t) else ""
                    if isinstance(gpu_t, str):
                        gpu_t = Text(gpu_t, style=dim) if gpu_t else ""
                    net_t = Text(str(net_t), style=dim) if str(net_t) else ""

                tmux_key: str = f"tmux:{sess.name}"
                state_placeholder = Text(" " * state_col_width, style="on #000000")
                tcells: dict[str, str | Text] = {
                    "State": state_placeholder,
                    "P": "",
                    "◉": "",
                    "■": "",
                    "Name": tmux_name,
                    "Elapsed": tmux_age,
                    "Model/Cmd": tmux_cmd,
                    "CPU": cpu_t,
                    "RAM": ram_t,
                    "GPU": gpu_t,
                    "Net": net_t,
                    "WS": "",
                    "CWD": sess.cwd,
                    "Tokens": "",
                }
                cols = self._SPLIT_COLUMNS if self._split_mode else self._FULL_COLUMNS
                row = [tcells.get(c, "") for c in cols]
                table.add_row(*row, key=tmux_key)

            hoplites = [
                sess
                for sess in a.tmux_sessions
                if self._is_hoplite_session_for(a, sess)
            ]
            viewer_sessions = [
                sess
                for sess in a.tmux_sessions
                if (not self._is_hoplite_session_for(a, sess))
                and (not is_hidden_tmux_session(sess))
            ]

            hoplite_prefix = f"{'  ' * indent_level}└ 🗡 "
            for sess in hoplites:
                _add_tmux_session_row(sess, prefix=hoplite_prefix)

            viewer_prefix = f"{'  ' * indent_level}└ 🔍 "
            for sess in viewer_sessions:
                _add_tmux_session_row(sess, prefix=viewer_prefix)

        rendered_agents: set[str] = set()

        def _render_agent_branch(
            a: AgentWindow,
            indent_level: int = 0,
            relation_icon: str | None = None,
        ) -> None:
            akey = self._agent_key(a)
            if akey in rendered_agents:
                return
            rendered_agents.add(akey)

            _add_agent_row(a, indent_level=indent_level, relation_icon=relation_icon)

            next_level = indent_level + 1
            for blocked in blocked_of.get(akey, []):
                _render_agent_branch(blocked, next_level, relation_icon="🔺")

            for child in children_of.get(a.agent_id, []):
                _render_agent_branch(child, next_level, relation_icon="🧬")

            _add_tmux_rows(a, indent_level=next_level)

        for a in top_level:
            _render_agent_branch(a)

        # Fallback for any non-rendered agent (guards against malformed trees).
        for a in self.agents:
            if self._agent_key(a) not in rendered_agents:
                _render_agent_branch(a)

        # Restore selected row
        if _saved_key:
            for idx, row_key in enumerate(table.rows):
                if row_key.value == _saved_key:
                    table.move_cursor(row=idx)
                    break

        self._update_mini_map()
        self._update_sparkline()

        n_working: int = sum(
            1 for a in self.agents
            if (not self._is_input_blocked(a)) and a.state == State.WORKING
        )
        n_idle: int = sum(
            1 for a in self.agents
            if (not self._is_input_blocked(a)) and a.state == State.IDLE
        )
        status = self.query_one("#status-line", Static)
        sort_label: str = self.sort_mode.value
        status.update(
            f"  {len(self.agents)} Hippeis  │  "
            f"[bold #00d7d7]{n_working} working[/]  "
            f"[bold #d7af00]{n_idle} idle[/]  │  "
            f"Sort: [bold]{sort_label}[/]  │  "
            f"Layout: [bold]{'SPLIT' if self._split_mode else 'WIDE'}[/]  │  "
            f"Poll: {SETTINGS.poll_interval}s"
        )


        return True


    # ── Mini-map ──────────────────────────────────────────────────────

    def _update_mini_map(self) -> None:
        """Render the agent fleet mini-map strip."""
        mini = self.query_one("#mini-map", Static)
        if not self._show_minimap or not self.agents:
            mini.add_class("hidden")
            return
        mini.remove_class("hidden")

        _state_pri_colors: dict[str, tuple[str, str, str, str]] = {
            "WORKING": self._state_minimap_priority_colors("WORKING"),
            "WAITING": self._state_minimap_priority_colors("WAITING"),
            "IDLE": self._state_minimap_priority_colors("IDLE"),
            "BLOCKED": ("#888888", "#666666", "#444444", "#1f1f1f"),
            "PAUSED": ("#777777", "#555555", "#333333", "#1a1a1a"),
        }


        parent_ids: set[str] = {a.agent_id for a in self.agents if a.agent_id}
        top_level: list[AgentWindow] = []
        children_of: dict[str, list[AgentWindow]] = {}
        for agent in self.agents:
            parent_id = (agent.parent_id or "").strip()
            if parent_id and parent_id in parent_ids:
                children_of.setdefault(parent_id, []).append(agent)
            else:
                top_level.append(agent)

        top_level.sort(key=lambda a: self._get_priority(a.name))
        for kids in children_of.values():
            kids.sort(key=lambda a: self._get_priority(a.name))

        def _agent_color(a: AgentWindow) -> str:
            akey = self._agent_key(a)
            if self._is_blocked(a):
                state_label = "BLOCKED"
            elif self._is_paused(a):
                state_label = "PAUSED"
            else:
                waiting = a.state == State.IDLE and akey in self._action_needed
                state_label = "WAITING" if waiting else a.state.value.upper()
            pri = self._get_priority(a.name)
            colors = _state_pri_colors.get(
                state_label, ("#777777", "#555555", "#333333", "#1a1a1a"),
            )
            idx = max(0, min(pri - 1, len(colors) - 1))
            return colors[idx]

        def _agent_state(a: AgentWindow) -> str:
            if self._is_blocked(a):
                return "BLOCKED"
            if self._is_paused(a):
                return "PAUSED"
            akey = self._agent_key(a)
            waiting = a.state == State.IDLE and akey in self._action_needed
            return "WAITING" if waiting else a.state.value.upper()



        # Build groups: list of (parent, [children])
        groups: list[tuple[AgentWindow, list[AgentWindow]]] = []
        for a in top_level:
            groups.append((a, children_of.get(a.agent_id, [])))

        # Render as box cards. Pack by available width and keep each card's
        # label directly under its marker row.
        self._minimap_agents = []
        sep = "  "
        sep_w = len(sep)
        max_w = max(20, int(getattr(getattr(mini, "size", None), "width", 0) or 0))

        cards: list[tuple[str, str, int]] = []
        for parent, kids in groups:
            pc = _agent_color(parent)
            pri = self._get_priority(parent.name)
            style = f"bold {pc}" if pri == 1 else pc
            name = _compact_name(parent.name, SETTINGS.minimap.max_name_length)
            pidx = len(self._minimap_agents)
            self._minimap_agents.append(parent.name)

            # Sub-agents inline
            subs_markup: list[str] = []
            subs_plain: list[str] = []
            for child in kids:
                cc = _agent_color(child)
                cpri = self._get_priority(child.name)
                cs = f"bold {cc}" if cpri == 1 else cc
                cn = _compact_name(child.name, SETTINGS.minimap.max_sub_name_length)
                cidx = len(self._minimap_agents)
                self._minimap_agents.append(child.name)
                subs_markup.append(
                    f"[#333333]┊[/] [@click=app.select_minimap({cidx})][{cs}]{cn}[/][/]"
                )
                subs_plain.append(f"┊ {cn}")

            inner = f"[@click=app.select_minimap({pidx})][{style}]{name}[/][/]"
            if subs_markup:
                inner += f" {' '.join(subs_markup)}"

            bottom_plain = f" {name}"
            if subs_plain:
                bottom_plain += f" {' '.join(subs_plain)}"

            card_w = max(len(bottom_plain), 8)
            top_line = f"[{pc}]{'▄' * card_w}[/]"
            bottom_line = f" {inner}"
            cards.append((top_line, bottom_line, card_w))

        lines: list[str] = []
        row_top: list[str] = []
        row_bot: list[str] = []
        row_w = 0

        def _flush_row() -> None:
            nonlocal row_top, row_bot, row_w
            if not row_top:
                return
            lines.append(sep.join(row_top))
            lines.append(sep.join(row_bot))
            row_top = []
            row_bot = []
            row_w = 0

        for top_line, bottom_line, card_w in cards:
            next_w = card_w if not row_top else row_w + sep_w + card_w
            if row_top and next_w > max_w:
                _flush_row()
                next_w = card_w

            row_top.append(top_line)
            row_bot.append(bottom_line)
            row_w = next_w

        _flush_row()

        mini.update("\n".join(lines))

    def _celebration_ready(self, *, now: float | None = None) -> bool:
        started = self._celebration_cooldown_started_at
        if started is None:
            return False
        current = time.time() if now is None else now
        return (current - started) >= self._CELEBRATION_COOLDOWN_S

    def _mark_celebration_cooldown(self) -> None:
        self._celebration_cooldown_started_at = time.time()

    def _maybe_trigger_celebration(self, eff_pct: float) -> None:
        if eff_pct < 80:
            self._steady_armed = True
        if eff_pct < 60:
            self._dopamine_armed = True

        if not self._celebration_ready():
            return

        if eff_pct >= 80 and self._steady_armed:
            if self._show_steady_lad(eff_pct):
                self._steady_armed = False
            return

        if eff_pct >= 60 and self._dopamine_armed:
            if self._show_dopamine_hit(eff_pct):
                self._dopamine_armed = False

    def _update_sparkline(self) -> None:
        """Render state sparkline charts for all agents."""
        from .widgets import state_sparkline_markup, _gradient_color
        widget = self.query_one("#sparkline-chart", Static)
        if not self._show_sparklines or not self.agents or not self._sparkline_samples:
            widget.add_class("hidden")
            return
        widget.remove_class("hidden")

        parent_ids: set[str] = {a.agent_id for a in self.agents if a.agent_id}

        def _sparkline_parent_sort_key(agent: AgentWindow) -> int:
            parent_id = (agent.parent_id or "").strip()
            if (not parent_id) or (parent_id not in parent_ids):
                return 0
            return 1

        ordered = sorted(
            self.agents,
            key=lambda a: (
                self._get_priority(a.name),
                _sparkline_parent_sort_key(a),
                a.name,
            ),
        )

        # Aggregate efficiency header (weighted by priority)
        _pri_weight = {1: 5, 2: 3, 3: 1, 4: 0}
        w_working = 0.0
        w_waiting = 0.0
        w_total = 0.0
        raw_working = 0
        raw_waiting = 0
        raw_total = 0
        for agent in self.agents:
            if self._is_input_blocked(agent):
                continue
            samples = self._sparkline_samples.get(agent.name, [])
            if not samples:
                continue
            w = _pri_weight.get(self._get_priority(agent.name), 1)
            nw = sum(1 for s in samples if s == "WORKING")
            nwait = sum(1 for s in samples if s == "WAITING")
            w_working += nw * w
            w_waiting += nwait * w
            w_total += len(samples) * w
            raw_working += nw
            raw_waiting += nwait
            raw_total += len(samples)
        total = raw_total
        if total > 0:
            eff_pct = w_working / w_total * 100 if w_total else 0
            work_pct = raw_working / total * 100
            wait_pct = raw_waiting / total * 100
            idle_pct = (total - raw_working - raw_waiting) / total * 100

            self._maybe_trigger_celebration(eff_pct)

            header = (
                f"[#888888]Efficiency: {eff_pct:.0f}%[/]  │  "
                f"[#888888]▶ {work_pct:.0f}%  "
                f"⏸ {wait_pct:.0f}%  "
                f"⏹ {idle_pct:.0f}%[/]"
            )
        else:
            header = "[#555555]Efficiency: —[/]"

        # Divider + per-agent rows
        content_w = max(20, widget.size.width)  # size is already content area
        lines: list[str] = [header, "[#1a3a3a]" + "─" * content_w + "[/]"]
        # Prefix width: "100% " = 5 chars
        prefix_w = 5
        for agent in ordered:
            if self._is_input_blocked(agent):
                continue
            samples = self._sparkline_samples.get(agent.name, [])
            if not samples:
                continue
            name = agent.name
            agent_eff = sum(1 for s in samples if s == "WORKING") / len(samples) * 100
            prefix = f"[#888888]{agent_eff:3.0f}%[/] "
            max_spark_chars = max(5, content_w - len(name) - prefix_w - 1)
            # Floor division: always even sample count so pairings don't shift
            n_chars = min(max_spark_chars, len(samples) // 2)
            chart_markup = state_sparkline_markup(samples, width=n_chars)
            gap = max_spark_chars - n_chars
            lines.append(
                f"{prefix}[#555555]{name}[/] {' ' * gap}{chart_markup}"
            )

        widget.update("\n".join(lines))

    def _dismiss_celebration(self) -> bool:
        """Dismiss any active celebration overlay. Return True if one was dismissed."""
        from .widgets import DopamineOverlay, SteadyLadOverlay
        for sel, cls in (("#dopamine", DopamineOverlay), ("#steady-lad", SteadyLadOverlay)):
            nodes = self.query(sel)
            if nodes:
                for node in nodes:
                    if isinstance(node, (DopamineOverlay, SteadyLadOverlay)):
                        node._dismiss_now()
                return True
        return False

    def _show_steady_lad(self, efficiency: float) -> bool:
        """Mount the steady lad celebration overlay."""
        from .widgets import SteadyLadOverlay
        if self.query("#steady-lad") or self.query("#dopamine"):
            return False
        self.mount(SteadyLadOverlay(efficiency, id="steady-lad"))
        self._mark_celebration_cooldown()
        return True

    def _show_dopamine_hit(self, efficiency: float) -> bool:
        """Mount the dopamine celebration overlay."""
        from .widgets import DopamineOverlay
        # Don't stack multiple
        if self.query("#dopamine") or self.query("#steady-lad"):
            return False
        self.mount(DopamineOverlay(efficiency, id="dopamine"))
        self._mark_celebration_cooldown()
        return True

    def action_select_minimap(self, index: int) -> None:
        """Select an agent by mini-map click index."""
        if index < 0 or index >= len(self._minimap_agents):
            return
        name = self._minimap_agents[index]
        table = self.query_one("#agent-table", DataTable)
        for idx, row_key in enumerate(table.rows):
            agent = self._get_agent_by_key(row_key.value)
            if agent and agent.name == name:
                table.move_cursor(row=idx)
                table.focus()
                if self._interact_visible:
                    self._refresh_interact_panel()
                break

    # ── Selection helpers ─────────────────────────────────────────────

    def _get_selected_row_key(self) -> str | None:
        table = self.query_one("#agent-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(
                table.cursor_coordinate
            )
            return row_key.value
        except (KeyError, IndexError, LookupError):
            return None

    def _get_agent_by_key(self, key_val: str | None) -> AgentWindow | None:
        if not key_val or key_val.startswith("tmux:"):
            return None
        for a in self.agents:
            if self._agent_key(a) == key_val:
                return a
        return None

    def _get_selected_agent(self) -> AgentWindow | None:
        return self._get_agent_by_key(self._get_selected_row_key())

    def _get_selected_tmux(self) -> TmuxSession | None:
        key_val: str | None = self._get_selected_row_key()
        if not key_val or not key_val.startswith("tmux:"):
            return None
        sess_name: str = key_val[5:]
        for a in self.agents:
            for sess in a.tmux_sessions:
                if sess.name == sess_name:
                    return sess
        return None

    def _get_parent_agent_for_tmux(self, sess: TmuxSession) -> AgentWindow | None:
        """Return the agent that owns this tmux session."""
        for a in self.agents:
            if sess in a.tmux_sessions:
                return a
        return None

    @staticmethod
    def _is_hoplite_session_for(agent: AgentWindow, sess: TmuxSession) -> bool:
        """Return True only for Polemarch-owned AGENT hoplite sessions."""
        if (sess.role or "").strip().lower() != "hoplite":
            return False
        if not sess.owner_id or not agent.agent_id or sess.owner_id != agent.agent_id:
            return False
        return bool((sess.phalanx_id or "").strip())

    @staticmethod
    def _is_hidden_agent(agent: AgentWindow) -> bool:
        return (
            (agent.backend or "").strip() == HIDDEN_AGENT_BACKEND
            and bool((agent.tmux_session or "").strip())
        )

    def _read_agent_screen_text(
        self,
        agent: AgentWindow,
        *,
        full: bool = False,
        ansi: bool = False,
    ) -> str:
        if self._is_hidden_agent(agent):
            return capture_hidden_screen_text(
                agent.tmux_session,
                full=full,
                ansi=ansi,
            )
        if ansi:
            return get_screen_text(agent, full=full, ansi=True)
        return get_screen_text(agent, full=full)

    # ── Actions ───────────────────────────────────────────────────────

    def _send_stop_to_selected_agent(self) -> None:
        """Send ESC to the currently selected agent row."""
        if self._has_blocking_modal_open():
            return
        agent = self._get_selected_agent()
        if not agent:
            return

        if self._is_hidden_agent(agent):
            if send_hidden_escape(agent.tmux_session):
                self.notify(f"ESC → {agent.name}", timeout=2)
            else:
                self.notify(f"ESC failed: {agent.name}", timeout=3)
            return

        kitty_cmd(
            agent.socket, "send-text", "--match",
            f"id:{agent.kitty_id}", "\x1b",
        )
        self.notify(f"ESC → {agent.name}", timeout=2)

    def action_stop_agent(self) -> None:
        """Send ESC to selected agent (table-focused safety behavior)."""
        if self._is_text_input_focused():
            return
        self._send_stop_to_selected_agent()

    def action_force_stop_agent(self) -> None:
        """Send ESC to selected agent from any focused widget."""
        self._send_stop_to_selected_agent()

    def action_focus_agent(self) -> None:
        """Ctrl+Enter: teleport to the agent's kitty window or tmux client."""
        tmux = self._get_selected_tmux()
        if tmux:
            if self._focus_tmux_client(tmux):
                return
            # No attached client — open a new kitty window on parent workspace
            parent = self._get_parent_agent_for_tmux(tmux)
            workspace = (parent.workspace if parent else None) or ""
            proc = subprocess.Popen(
                ["kitty", "tmux", "attach-session", "-t", tmux.name],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if workspace and workspace != "?":
                move_pid_to_workspace_and_focus_later(
                    proc.pid,
                    workspace,
                    delay=0.5,
                )
            self.notify(
                f"Opening tmux:{tmux.name}", timeout=2,
            )
            return
        agent = self._get_selected_agent()
        if not agent:
            return
        if self._is_hidden_agent(agent):
            self._focus_hidden_agent(agent)
            return
        focus_window(agent)

    def _focus_hidden_agent(self, agent: AgentWindow) -> None:
        """Focus/attach hidden Hippeus tmux session."""
        sess_name = (agent.tmux_session or "").strip()
        if not sess_name:
            self.notify("Hidden Hippeus session missing", timeout=2)
            return

        tmux_target = TmuxSession(
            name=sess_name,
            command="",
            cwd=agent.cwd,
            attached=self._get_tmux_client_pid(sess_name) is not None,
        )

        if tmux_target.attached:
            if self._focus_tmux_client(tmux_target):
                self.notify(f"Focused: {agent.name}", timeout=2)
            else:
                self.notify(f"Could not find window for {sess_name}", timeout=2)
            return

        proc = subprocess.Popen(
            ["kitty", "tmux", "attach-session", "-t", sess_name],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if agent.workspace and agent.workspace != "?":
            move_pid_to_workspace_and_focus_later(
                proc.pid,
                agent.workspace,
                delay=0.5,
            )
        self.notify(f"Opening tmux:{sess_name}", timeout=2)

    def action_open_shell_here(self) -> None:
        """Ctrl+O: open a plain kitty shell in selected target's directory."""
        if self._has_blocking_modal_open():
            return

        tmux = self._get_selected_tmux()
        if tmux:
            parent = self._get_parent_agent_for_tmux(tmux)
            cwd = (tmux.cwd or "").strip() or (
                (parent.cwd if parent else "") or ""
            ).strip()
            label = f"tmux:{tmux.name}"
        else:
            agent = self._get_selected_agent()
            if not agent:
                self.notify("No selected target", timeout=2)
                return
            cwd = (agent.cwd or "").strip()
            label = agent.name

        if not cwd:
            self.notify("No directory for selected target", timeout=2)
            return

        try:
            subprocess.Popen(
                ["kitty", "--directory", cwd],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as e:
            self.notify(f"Open shell failed: {e}", timeout=3)
            return

        self.notify(f"Shell: {label}", timeout=2)

    def action_open_url(self, url: str) -> None:
        """Open URL from interact stream in default browser."""
        if not url:
            return

        for cmd in (["xdg-open", url], ["gio", "open", url]):
            try:
                subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.notify(f"Opening: {url}", timeout=2)
                return
            except FileNotFoundError:
                continue
            except OSError:
                continue

        try:
            import webbrowser
            if webbrowser.open(url):
                self.notify(f"Opening: {url}", timeout=2)
                return
        except Exception:
            pass

        self.notify("Could not open link", timeout=2)

    @staticmethod
    def _agent_key(agent: AgentWindow) -> str:
        if (
            (agent.backend or "").strip() == HIDDEN_AGENT_BACKEND
            and (agent.agent_id or "").strip()
        ):
            return hidden_agent_row_key(agent.agent_id)
        return f"{agent.socket}:{agent.kitty_id}"

    @staticmethod
    def _normalized_agent_name(name: str) -> str:
        return name.strip().casefold()

    def _is_agent_name_taken(
        self,
        name: str,
        *,
        exclude_key: str | None = None,
    ) -> bool:
        target = self._normalized_agent_name(name)
        if not target:
            return False
        for agent in self.agents:
            if exclude_key and self._agent_key(agent) == exclude_key:
                continue
            if self._normalized_agent_name(agent.name) == target:
                return True
        return False

    @staticmethod
    def _agent_identity_key(agent: AgentWindow) -> str:
        if agent.agent_id:
            return agent.agent_id
        if (agent.backend or "").strip() == HIDDEN_AGENT_BACKEND:
            sess = (agent.tmux_session or "").strip()
            if sess:
                return f"hidden-session:{sess}"
        return f"{agent.socket}:{agent.kitty_id}"

    def _agent_tasks_key(self, agent: AgentWindow) -> str:
        return self._agent_identity_key(agent)

    def _agent_message_draft_key(self, agent: AgentWindow) -> str:
        return self._agent_identity_key(agent)

    @staticmethod
    def _history_key_for_agent(agent: AgentWindow) -> str:
        return f"agent:{agent.name}"

    def _message_draft_for_agent(self, agent: AgentWindow) -> str:
        return self._agent_message_drafts.get(self._agent_message_draft_key(agent), "")

    def do_save_agent_message_draft(self, agent: AgentWindow, draft: str) -> None:
        key = self._agent_message_draft_key(agent)
        if draft:
            self._agent_message_drafts[key] = draft
        else:
            self._agent_message_drafts.pop(key, None)

    def do_clear_agent_message_draft(self, agent: AgentWindow) -> None:
        self._agent_message_drafts.pop(self._agent_message_draft_key(agent), None)

    def _agent_dependency_key(self, agent: AgentWindow) -> str:
        return self._agent_identity_key(agent)

    def _agent_by_dependency_key(self, dep_key: str) -> AgentWindow | None:
        for agent in self.agents:
            if self._agent_dependency_key(agent) == dep_key:
                return agent
        return None

    def _has_promotable_parent(self, agent: AgentWindow) -> bool:
        """Return True when a sub-Hippeus can be promoted to top-level."""
        if not (agent.agent_id or "").strip():
            return False
        return bool((agent.parent_id or "").strip())

    def _task_text_for_agent(self, agent: AgentWindow) -> str:
        return self._agent_tasks.get(self._agent_tasks_key(agent), "")

    def _has_task_for_agent(self, agent: AgentWindow) -> bool:
        return bool(self._task_text_for_agent(agent).strip())

    def _is_blocked(self, agent: AgentWindow) -> bool:
        return self._agent_dependency_key(agent) in self._agent_dependencies

    def _blocking_agent_for(self, agent: AgentWindow) -> AgentWindow | None:
        blocker_key = self._agent_dependencies.get(self._agent_dependency_key(agent))
        if not blocker_key:
            return None
        return self._agent_by_dependency_key(blocker_key)

    def _is_input_blocked(self, agent: AgentWindow) -> bool:
        return self._is_paused(agent) or self._is_blocked(agent)

    def _would_create_dependency_cycle(
        self,
        blocked_dep_key: str,
        blocker_dep_key: str,
    ) -> bool:
        visited: set[str] = {blocked_dep_key}
        cur = blocker_dep_key
        while cur:
            if cur in visited:
                return True
            visited.add(cur)
            cur = self._agent_dependencies.get(cur, "")
        return False

    def _broadcast_recipients(self, source_key: str) -> list[AgentWindow]:
        """Return recipients excluding source and dependency-blocked agents.

        Paused agents are eligible; they are auto-resumed to priority 3 on send.
        """
        recipients: list[AgentWindow] = []
        for agent in self.agents:
            key = self._agent_key(agent)
            if key == source_key:
                continue
            if self._is_blocked(agent):
                continue
            recipients.append(agent)
        return recipients

    def _is_blocked_by_source_key(self, target: AgentWindow, source_key: str) -> bool:
        """Return True when target currently depends on the source agent."""
        source = self._get_agent_by_key(source_key)
        if source is None:
            return False

        target_dep_key = self._agent_dependency_key(target)
        source_dep_key = self._agent_dependency_key(source)
        return self._agent_dependencies.get(target_dep_key) == source_dep_key

    def _clear_dependency_if_blocked_by_source(
        self,
        target: AgentWindow,
        *,
        source_agent_id: str = "",
        source_name: str = "",
    ) -> bool:
        """Clear target dependency only when it is blocked by the message source."""
        target_dep_key = self._agent_dependency_key(target)
        blocker_dep_key = self._agent_dependencies.get(target_dep_key)
        if not blocker_dep_key:
            return False

        source_candidates: set[str] = set()

        source_id = source_agent_id.strip()
        if source_id:
            source_candidates.add(source_id)
            source = self._get_agent_by_id(source_id)
            if source is not None:
                source_candidates.add(self._agent_dependency_key(source))
                source_candidates.add(self._agent_key(source))

        name = source_name.strip()
        if name:
            matches = [agent for agent in self.agents if agent.name == name]
            if len(matches) == 1:
                source = matches[0]
                source_candidates.add(self._agent_dependency_key(source))
                source_candidates.add(self._agent_key(source))

        if blocker_dep_key not in source_candidates:
            return False

        self._agent_dependencies.pop(target_dep_key, None)
        self._dependency_missing_polls.pop(target_dep_key, None)
        self._save_agent_dependencies()
        if getattr(self, "_screen_stack", []):
            self._render_agent_table_and_status()
            if self._interact_visible:
                self._refresh_interact_panel()
        return True

    def _direct_recipients(self, source_key: str) -> list[AgentWindow]:
        """Return direct-send recipients for a source.

        Includes:
        - non-blocked recipients (active or paused), and
        - blocked recipients only when they are blocked by the source.
        """
        recipients: list[AgentWindow] = []
        for agent in self.agents:
            key = self._agent_key(agent)
            if key == source_key:
                continue
            if (not self._is_blocked(agent)) or self._is_blocked_by_source_key(
                agent, source_key
            ):
                recipients.append(agent)
        return recipients

    def _target_options_from_keys(
        self,
        recipient_keys: list[str],
        *,
        source_key: str | None = None,
    ) -> list[tuple[str, str]]:
        """Return direct target options as (name, key).

        Non-blocked targets (active or paused) are always eligible.
        Blocked targets are eligible only when they are blocked by ``source_key``.
        """
        options: list[tuple[str, str]] = []
        for key in recipient_keys:
            agent = self._get_agent_by_key(key)
            if agent is None:
                continue
            if not self._is_blocked(agent):
                options.append((agent.name, key))
                continue
            if source_key and self._is_blocked_by_source_key(agent, source_key):
                options.append((agent.name, key))
        return options

    def _share_payload_for_source(self, source: AgentWindow) -> str | None:
        """Extract share payload from file pointer first, then marker fallback.

        Order matters:
        1) ZEUS_MSG_FILE pointer in session transcript
        2) wrapped %%%% marker block in user transcript
        3) ZEUS_MSG_FILE pointer in full screen text
        4) wrapped %%%% marker block in full screen text
        """
        session_path = resolve_agent_session_path(source)
        if session_path:
            session_all_text = read_session_text(session_path)
            if session_all_text.strip():
                pointer = _extract_share_file_path(session_all_text)
                if pointer:
                    payload = _read_share_file_payload(pointer)
                    if payload is not None:
                        return payload.strip()

            session_user_text = read_session_user_text(session_path)
            if session_user_text.strip():
                payload = _extract_share_payload(session_user_text)
                if payload is not None:
                    return payload

        screen_text = self._read_agent_screen_text(source, full=True)
        if screen_text.strip():
            pointer = _extract_share_file_path(screen_text)
            if pointer:
                payload = _read_share_file_payload(pointer)
                if payload is not None:
                    return payload.strip()
            return _extract_share_payload(screen_text)

        return None

    _SHARE_MARKER_REMINDER = (
        f"No payload found. Provide ZEUS_MSG_FILE={MESSAGE_TMP_DIR}/zeus-msg-<uuid>.md "
        "(file name is arbitrary), "
        f"or wrap text between {_SHARE_MARKER} marker lines."
    )

    def _dismiss_broadcast_preparing_screen(self) -> None:
        if len(self.screen_stack) <= 1:
            return
        top = self.screen_stack[-1]
        if isinstance(top, BroadcastPreparingScreen):
            self.pop_screen()

    def cancel_broadcast_prepare(self, job_id: int) -> None:
        """Cancel an in-flight summary preparation job."""
        if self._broadcast_active_job != job_id:
            return
        self._broadcast_active_job = None
        self._prepare_target_selection.pop(job_id, None)

    def set_prepare_target_selection(self, job_id: int, target_key: str) -> None:
        """Persist target pick made in the preparing modal."""
        if self._broadcast_active_job != job_id:
            return
        self._prepare_target_selection[job_id] = target_key

    def _consume_prepare_target_selection(self, job_id: int) -> str | None:
        return self._prepare_target_selection.pop(job_id, None)

    def _start_summary_prepare(
        self,
        source: AgentWindow,
        recipient_keys: list[str],
        *,
        mode: str,
        title: str,
        target_options: list[tuple[str, str]] | None = None,
        initial_target_key: str | None = None,
    ) -> None:
        self._broadcast_job_seq += 1
        job_id = self._broadcast_job_seq
        self._broadcast_active_job = job_id

        if initial_target_key is not None:
            self._prepare_target_selection[job_id] = initial_target_key

        self.push_screen(
            BroadcastPreparingScreen(
                source_name=source.name,
                recipient_count=len(recipient_keys),
                job_id=job_id,
                title=title,
                target_options=target_options,
                selected_target_key=initial_target_key,
            )
        )
        self._prepare_summary_preview(
            job_id,
            mode,
            self._agent_key(source),
            source.name,
            recipient_keys,
        )

    def action_broadcast_summary(self) -> None:
        """B: share marked block from selected agent to active peers."""
        if self._should_ignore_table_action():
            return

        source = self._get_selected_agent()
        if not source:
            self.notify("Broadcast source must be a Hippeus row", timeout=2)
            return
        if self._is_input_blocked(source):
            self.notify("Selected source is not active; pick another Hippeus", timeout=2)
            return

        source_key = self._agent_key(source)
        recipient_keys = [
            self._agent_key(a) for a in self._broadcast_recipients(source_key)
        ]
        if not recipient_keys:
            self.notify("No eligible recipients (source excluded)", timeout=2)
            return

        self._start_summary_prepare(
            source,
            recipient_keys,
            mode="broadcast",
            title="Preparing broadcast payload…",
        )

    def action_direct_summary(self) -> None:
        """M: share marked block from selected agent to one peer."""
        if self._should_ignore_table_action():
            return

        source = self._get_selected_agent()
        if not source:
            self.notify("Direct-message source must be a Hippeus row", timeout=2)
            return
        if self._is_input_blocked(source):
            self.notify("Selected source is not active; pick another Hippeus", timeout=2)
            return

        source_key = self._agent_key(source)
        recipient_keys = [
            self._agent_key(a) for a in self._direct_recipients(source_key)
        ]
        if not recipient_keys:
            self.notify(
                "No eligible targets (non-blocked peers or your blocked dependents)",
                timeout=2,
            )
            return

        target_options = self._target_options_from_keys(
            recipient_keys,
            source_key=source_key,
        )
        if not target_options:
            self.notify(
                "No eligible targets (non-blocked peers or your blocked dependents)",
                timeout=2,
            )
            return

        self._start_summary_prepare(
            source,
            recipient_keys,
            mode="direct",
            title="Preparing direct payload…",
            target_options=target_options,
            initial_target_key=target_options[0][1],
        )

    def action_yank_summary_payload(self) -> None:
        """Y: yank marked payload from selected Hippeus to system clipboard."""
        if self._should_ignore_table_action():
            return

        source = self._get_selected_agent()
        if not source:
            self.notify("Select a Hippeus row to yank summary payload", timeout=2)
            return

        payload = self._share_payload_for_source(source)
        if payload is None:
            self.notify(self._SHARE_MARKER_REMINDER, timeout=4)
            return

        if not payload:
            self.notify(
                f"Wrapped {_SHARE_MARKER} markers found, but the enclosed block is empty.",
                timeout=4,
            )
            return

        if not self._copy_text_to_system_clipboard(payload):
            self.notify_force(
                "Could not copy payload to clipboard (wl-copy)",
                timeout=3,
            )
            return

        self.notify(f"Yanked payload: {source.name}", timeout=2)

    @work(thread=True, exclusive=True, group="broadcast")
    def _prepare_summary_preview(
        self,
        job_id: int,
        mode: str,
        source_key: str,
        source_name: str,
        recipient_keys: list[str],
    ) -> None:
        if self._broadcast_active_job != job_id:
            return

        source = self._get_agent_by_key(source_key)
        if source is None:
            self.call_from_thread(
                self._summary_prepare_failed,
                job_id,
                "Source Hippeus is no longer available",
                2,
            )
            return

        payload = self._share_payload_for_source(source)
        if payload is None:
            self.call_from_thread(
                self._summary_prepare_failed,
                job_id,
                self._SHARE_MARKER_REMINDER,
                4,
            )
            return

        if not payload:
            self.call_from_thread(
                self._summary_prepare_failed,
                job_id,
                (
                    f"Wrapped {_SHARE_MARKER} markers found, but the enclosed "
                    "block is empty."
                ),
                4,
            )
            return

        message = payload
        if mode == "direct":
            self.call_from_thread(
                self._show_direct_preview,
                job_id,
                source_name,
                recipient_keys,
                message,
                source_key,
            )
            return

        self.call_from_thread(
            self._show_broadcast_preview,
            job_id,
            source_name,
            recipient_keys,
            message,
        )

    def _summary_prepare_failed(
        self,
        job_id: int,
        message: str,
        timeout: float,
    ) -> None:
        if self._broadcast_active_job != job_id:
            return
        self._broadcast_active_job = None
        self._consume_prepare_target_selection(job_id)
        self._dismiss_broadcast_preparing_screen()
        self.notify(message, timeout=timeout)

    def _show_broadcast_preview(
        self,
        job_id: int,
        source_name: str,
        recipient_keys: list[str],
        message: str,
    ) -> None:
        if self._broadcast_active_job != job_id:
            return
        self._broadcast_active_job = None
        self._consume_prepare_target_selection(job_id)
        self._dismiss_broadcast_preparing_screen()

        recipient_names: list[str] = []
        for key in recipient_keys:
            agent = self._get_agent_by_key(key)
            if agent is not None and not self._is_blocked(agent):
                recipient_names.append(agent.name)

        if not recipient_names:
            self.notify("No eligible recipients (source excluded)", timeout=2)
            return

        self.push_screen(
            ConfirmBroadcastScreen(
                source_name=source_name,
                recipient_keys=recipient_keys,
                recipient_names=recipient_names,
                message=message,
            )
        )

    def _show_direct_preview(
        self,
        job_id: int,
        source_name: str,
        recipient_keys: list[str],
        message: str,
        source_key: str | None = None,
    ) -> None:
        if self._broadcast_active_job != job_id:
            return
        self._broadcast_active_job = None
        preferred_target_key = self._consume_prepare_target_selection(job_id)
        self._dismiss_broadcast_preparing_screen()

        target_options = self._target_options_from_keys(
            recipient_keys,
            source_key=source_key,
        )
        if not target_options:
            self.notify(
                "No eligible targets (non-blocked peers or your blocked dependents)",
                timeout=2,
            )
            return

        option_keys = {key for _, key in target_options}
        if preferred_target_key not in option_keys:
            preferred_target_key = target_options[0][1]

        self.push_screen(
            ConfirmDirectMessageScreen(
                source_name=source_name,
                source_key=source_key,
                target_options=target_options,
                message=message,
                initial_target_key=preferred_target_key,
            )
        )

    @staticmethod
    def _queue_retry_delay_s(attempts: int) -> float:
        return min(30.0, float(2 ** max(0, min(attempts, 4))))

    def _get_agent_by_id(self, agent_id: str) -> AgentWindow | None:
        clean = agent_id.strip()
        if not clean:
            return None
        for agent in self.agents:
            if self._agent_identity_key(agent) == clean:
                return agent
        return None

    def _iter_all_tmux_sessions(self) -> list[TmuxSession]:
        sessions: list[TmuxSession] = []
        for agent in self.agents:
            sessions.extend(agent.tmux_sessions)
        return sessions

    def _resolve_queue_targets(self, envelope: OutboundEnvelope) -> list[QueueDeliveryTarget]:
        kind = (envelope.target_kind or "agent").strip().lower()
        targets: list[QueueDeliveryTarget] = []

        if kind == "agent":
            target_id = (envelope.target_ref or envelope.target_agent_id).strip()
            target = self._get_agent_by_id(target_id)
            if target is None:
                return []
            recipient_key = f"agent:{self._agent_identity_key(target)}"
            targets.append(
                QueueDeliveryTarget(
                    recipient_key=recipient_key,
                    label=target.name,
                    kind="agent",
                    agent=target,
                )
            )
            return targets

        sessions = self._iter_all_tmux_sessions()

        if kind == "hoplite":
            hoplite_id = envelope.target_ref.strip()
            for sess in sessions:
                if (sess.role or "").strip().lower() != "hoplite":
                    continue
                if not sess.name.strip():
                    continue
                sess_agent_id = (sess.agent_id or sess.env_agent_id or "").strip()
                if sess_agent_id != hoplite_id:
                    continue
                if envelope.target_owner_id and sess.owner_id != envelope.target_owner_id:
                    continue
                recipient_key = f"tmux:{sess.name}"
                targets.append(
                    QueueDeliveryTarget(
                        recipient_key=recipient_key,
                        label=sess.name,
                        kind="tmux",
                        tmux_session=sess.name,
                    )
                )
                break
            return targets

        if kind == "phalanx":
            phalanx_id = envelope.target_ref.strip()
            if not phalanx_id:
                return []

            for sess in sessions:
                if (sess.role or "").strip().lower() != "hoplite":
                    continue
                if (sess.phalanx_id or "").strip() != phalanx_id:
                    continue
                if envelope.target_owner_id and sess.owner_id != envelope.target_owner_id:
                    continue
                sess_agent_id = (sess.agent_id or "").strip()
                if envelope.source_agent_id and sess_agent_id == envelope.source_agent_id:
                    continue
                if not sess.name.strip():
                    continue
                recipient_key = f"tmux:{sess.name}"
                targets.append(
                    QueueDeliveryTarget(
                        recipient_key=recipient_key,
                        label=sess.name,
                        kind="tmux",
                        tmux_session=sess.name,
                    )
                )

            targets.sort(key=lambda t: t.tmux_session)
            return targets

        return []

    def _deliver_queue_target(
        self,
        target: QueueDeliveryTarget,
        message: str,
        *,
        source_agent_id: str = "",
        source_name: str = "",
    ) -> bool:
        if target.kind == "agent" and target.agent is not None:
            dependency_cleared = self._clear_dependency_if_blocked_by_source(
                target.agent,
                source_agent_id=source_agent_id,
                source_name=source_name,
            )
            if not dependency_cleared:
                self._resume_agent_if_paused(target.agent)
            return self._queue_text_to_agent(target.agent, message)
        if target.kind == "tmux" and target.tmux_session:
            return self._dispatch_tmux_text(target.tmux_session, message, queue=True)
        return False

    def _enqueue_outbound_agent_message(
        self,
        target: AgentWindow,
        message: str,
        *,
        source_name: str,
        source_agent_id: str = "",
    ) -> bool:
        target_id = self._agent_identity_key(target).strip()
        if not target_id:
            return False

        clean = self._normalize_outgoing_text(message)
        if not clean.strip():
            return False

        envelope = OutboundEnvelope.new(
            source_name=source_name,
            source_agent_id=source_agent_id,
            target_kind="agent",
            target_ref=target_id,
            target_agent_id=target_id,
            target_name=target.name,
            message=clean,
        )
        enqueue_envelope(envelope)
        return True

    def _drain_message_queue(self) -> None:
        if self._message_queue_draining:
            return

        self._message_queue_draining = True
        receipts_changed = False
        try:
            now = time.time()
            reclaim_stale_inflight(self._message_queue_inflight_lease_s, now=now)
            receipts_changed |= prune_message_receipts(
                self._message_receipts,
                now=now,
                ttl_seconds=self._message_receipts_ttl_s,
            )

            for path in list_new_envelopes():
                envelope = load_envelope(path)
                if envelope is None:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    continue

                if envelope.next_attempt_at > now:
                    continue

                pre_targets = self._resolve_queue_targets(envelope)
                if not pre_targets:
                    continue

                inflight = claim_envelope(path)
                if inflight is None:
                    continue

                claimed = load_envelope(inflight)
                if claimed is None:
                    ack_envelope(inflight)
                    continue

                targets = self._resolve_queue_targets(claimed)
                if not targets:
                    requeue_envelope(
                        inflight,
                        claimed,
                        now=time.time(),
                        delay_seconds=1.0,
                    )
                    continue

                all_delivered = True
                for target in targets:
                    if has_message_receipt(
                        self._message_receipts,
                        recipient_key=target.recipient_key,
                        message_id=claimed.id,
                        now=time.time(),
                        ttl_seconds=self._message_receipts_ttl_s,
                    ):
                        continue

                    delivered = self._deliver_queue_target(
                        target,
                        claimed.message,
                        source_agent_id=claimed.source_agent_id,
                        source_name=claimed.source_name,
                    )
                    if not delivered:
                        all_delivered = False
                        break

                    record_message_receipt(
                        self._message_receipts,
                        recipient_key=target.recipient_key,
                        message_id=claimed.id,
                        now=time.time(),
                    )
                    receipts_changed = True

                if all_delivered:
                    ack_envelope(inflight)
                    continue

                requeue_envelope(
                    inflight,
                    claimed,
                    now=time.time(),
                    delay_seconds=self._queue_retry_delay_s(claimed.attempts),
                )
        finally:
            if receipts_changed:
                save_message_receipts(self._message_receipts)
            self._message_queue_draining = False

    def do_enqueue_broadcast(
        self,
        source_name: str,
        recipient_keys: list[str],
        message: str,
    ) -> None:
        """Queue broadcast message to recipients (Alt+Enter semantics)."""
        sent = 0
        for key in recipient_keys:
            agent = self._get_agent_by_key(key)
            if agent is None or self._is_blocked(agent):
                continue
            self._resume_agent_if_paused(agent)
            if self._enqueue_outbound_agent_message(
                agent,
                message,
                source_name=source_name,
            ):
                sent += 1

        if sent == 0:
            self.notify("Broadcast aborted: no eligible recipients", timeout=3)
            return

        self._drain_message_queue()
        self.notify(
            f"Broadcast from {source_name} queued to {sent} Hippeis",
            timeout=3,
        )

    def do_enqueue_direct(
        self,
        source_name: str,
        target_key: str,
        message: str,
        *,
        source_key: str | None = None,
    ) -> None:
        """Queue marked message to a single selected direct target.

        Non-blocked targets (active or paused) are always allowed.
        Blocked targets are allowed only when blocked by the source.
        """
        target = self._get_agent_by_key(target_key)
        if target is None:
            self.notify("Target is no longer active", timeout=3)
            return

        blocked_by_source = bool(
            source_key and self._is_blocked_by_source_key(target, source_key)
        )
        if self._is_blocked(target) and not blocked_by_source:
            self.notify("Target is no longer active", timeout=3)
            return

        source_agent_id = ""
        if source_key:
            source_agent = self._get_agent_by_key(source_key)
            if source_agent is not None:
                source_agent_id = self._agent_identity_key(source_agent)

        if not blocked_by_source:
            self._resume_agent_if_paused(target)

        if not self._enqueue_outbound_agent_message(
            target,
            message,
            source_name=source_name,
            source_agent_id=source_agent_id,
        ):
            self.notify("Message is empty", timeout=2)
            return

        self._drain_message_queue()

        if blocked_by_source:
            self.notify(
                f"Message from {source_name} queued to {target.name}; dependency cleared",
                timeout=3,
            )
            return

        self.notify(
            f"Message from {source_name} queued to {target.name}",
            timeout=3,
        )

    def _interact_draft_key(self) -> str | None:
        """Return a key for the current interact target's draft."""
        if self._interact_agent_key:
            return f"agent:{self._interact_agent_key}"
        if self._interact_tmux_name:
            return f"tmux:{self._interact_tmux_name}"
        return None

    def _save_interact_draft(self) -> None:
        """Stash current input text for the current target."""
        key = self._interact_draft_key()
        if key is None:
            return
        ta = self.query_one("#interact-input", ZeusTextArea)
        text = ta.text
        if text.strip():
            self._interact_drafts[key] = text
        else:
            self._interact_drafts.pop(key, None)

    @staticmethod
    def _visual_line_count(ta: TextArea) -> int:
        """Count visual lines including soft-wrapped ones."""
        width = max(1, ta.size.width - 2)  # content width minus padding
        total = 0
        for line in ta.text.split("\n"):
            total += max(1, -(-len(line) // width))  # ceil division
        return total

    @staticmethod
    def _visual_cursor_info(ta: TextArea) -> tuple[int, int]:
        """Return (cursor_visual_line_index, total_visual_lines)."""
        width = max(1, ta.size.width - 2)
        lines = ta.text.split("\n")
        total = 0
        for line in lines:
            total += max(1, -(-len(line) // width))

        row, col = ta.cursor_location
        if not lines:
            return (0, 1)
        row = max(0, min(row, len(lines) - 1))

        cur = 0
        for i, line in enumerate(lines):
            vis = max(1, -(-len(line) // width))
            if i < row:
                cur += vis
                continue
            clamped_col = max(0, min(col, len(line)))
            cur += min(vis - 1, clamped_col // width)
            break

        return (cur, max(1, total))

    def _resize_interact_input(self, ta: TextArea) -> None:
        """Resize interact input to fit visual content (1–8 lines)."""
        lines = self._visual_line_count(ta)
        ta.styles.height = max(1, min(8, lines)) + 2

    def _restore_interact_draft(self) -> None:
        """Restore stashed input text for the current target."""
        key = self._interact_draft_key()
        ta = self.query_one("#interact-input", ZeusTextArea)
        draft = self._interact_drafts.get(key or "", "")
        ta.load_text(draft)
        ta.move_cursor(ta.document.end)
        self._resize_interact_input(ta)

    def _set_interact_target_name(self, name: str) -> None:
        try:
            self.query_one("#interact-target", Static).update(name or "—")
        except LookupError:
            pass

    def _set_interact_editable(self, editable: bool) -> None:
        try:
            ta = self.query_one("#interact-input", ZeusTextArea)
            ta.read_only = not editable
        except LookupError:
            pass

    def _refresh_interact_panel(self) -> None:
        """Refresh the interact panel for the currently selected item."""
        old_agent_key = self._interact_agent_key
        old_tmux_name = self._interact_tmux_name

        tmux = self._get_selected_tmux()
        if tmux:
            self._set_interact_target_name(tmux.name)
            parent = self._find_agent_for_tmux(tmux)
            self._set_interact_editable(
                not (parent is not None and self._is_blocked(parent))
            )
            target_changed = (
                old_agent_key is not None
                or old_tmux_name != tmux.name
            )
            if target_changed:
                self._save_interact_draft()
                self._reset_history_nav()
            self._interact_agent_key = None
            self._interact_tmux_name = tmux.name
            self._update_interact_stream()
            if target_changed:
                self._restore_interact_draft()
            return
        agent = self._get_selected_agent()
        if not agent:
            self._set_interact_target_name("—")
            self._set_interact_editable(True)
            return
        self._set_interact_target_name(agent.name)
        self._set_interact_editable(not self._is_blocked(agent))
        key = self._agent_key(agent)
        target_changed = (
            old_agent_key != key
            or old_tmux_name is not None
        )
        if target_changed:
            self._save_interact_draft()
            self._reset_history_nav()
        self._interact_agent_key = key
        self._interact_tmux_name = None
        self._update_interact_stream()
        if target_changed:
            self._restore_interact_draft()

    def _get_tmux_client_pid(self, sess_name: str) -> int | None:
        """Return PID of first attached tmux client for a session."""
        try:
            r = subprocess.run(
                ["tmux", "list-clients", "-t", sess_name,
                 "-F", "#{client_pid}"],
                capture_output=True, text=True, timeout=2)
            if r.returncode != 0 or not r.stdout.strip():
                return None
            return int(r.stdout.strip().splitlines()[0])
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return None

    def _focus_tmux_client(self, sess: TmuxSession) -> bool:
        """Focus the sway window running an attached tmux session."""
        client_pid = self._get_tmux_client_pid(sess.name)
        if client_pid is None:
            return False

        kitty_pid = find_ancestor_pid_by_comm(client_pid, "kitty")
        if kitty_pid is None:
            return False
        return focus_pid(kitty_pid)

    def _find_agent_for_tmux(
        self, sess: TmuxSession
    ) -> AgentWindow | None:
        for a in self.agents:
            for s in a.tmux_sessions:
                if s.name == sess.name:
                    return a
        return None

    def _attach_tmux(self, sess: TmuxSession) -> None:
        """Handle Enter on a tmux row."""
        if sess.attached:
            if self._focus_tmux_client(sess):
                self.notify(f"Focused: {sess.name}", timeout=2)
            else:
                self.notify(
                    f"Could not find window for {sess.name}", timeout=2
                )
        else:
            parent: AgentWindow | None = self._find_agent_for_tmux(sess)
            parent_ws: str = parent.workspace if parent else ""
            proc = subprocess.Popen(
                ["kitty", "tmux", "attach", "-t", sess.name],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if parent_ws and parent_ws != "?":
                move_pid_to_workspace_and_focus_later(
                    proc.pid,
                    parent_ws,
                    delay=0.5,
                )
            self.notify(f"Attached: {sess.name}", timeout=2)

    # ── Interact input history ───────────────────────────────────────

    def _history_target_key(self) -> str | None:
        """Return history key for current interact target (agent-name based)."""
        if self._interact_agent_key:
            agent = self._get_agent_by_key(self._interact_agent_key)
            if agent:
                return self._history_key_for_agent(agent)
        if self._interact_tmux_name:
            for agent in self.agents:
                if any(s.name == self._interact_tmux_name for s in agent.tmux_sessions):
                    return self._history_key_for_agent(agent)
        return None

    def _reset_history_nav(self) -> None:
        self._history_nav_target = None
        self._history_nav_index = None
        self._history_nav_draft = None

    def _set_interact_input_text(self, text: str, *, cursor_end: bool = False) -> None:
        ta = self.query_one("#interact-input", ZeusTextArea)
        if text:
            ta.load_text(text)
        else:
            ta.clear()
        if cursor_end:
            ta.move_cursor(ta.document.end)
        self._resize_interact_input(ta)

    def _handle_interact_history_nav(self, key: str) -> bool:
        """Handle Up/Down history traversal for interact input.

        - Up/Down first navigate within current multiline entry.
        - History item switching happens only at visual top/bottom boundaries.
        - When leaving history at the bottom, restore pre-history draft.
        """
        target = self._history_target_key()
        if not target:
            return False

        ta = self.query_one("#interact-input", ZeusTextArea)
        entries = load_history(target)
        if not entries:
            return False

        if self._history_nav_target != target:
            self._history_nav_target = target
            self._history_nav_index = None
            self._history_nav_draft = None

        cur_vline, total_vlines = self._visual_cursor_info(ta)
        at_top = cur_vline == 0
        at_bottom = cur_vline >= total_vlines - 1

        if key == "up":
            # Let TextArea handle normal cursor movement first.
            if not at_top:
                return False

            if self._history_nav_index is None:
                self._history_nav_draft = ta.text
                self._history_nav_index = len(entries) - 1
            elif self._history_nav_index > 0:
                self._history_nav_index -= 1

            up_idx = self._history_nav_index
            if up_idx is None:
                return False
            self._set_interact_input_text(entries[up_idx])
            return True

        if key == "down":
            down_idx = self._history_nav_index
            if down_idx is None:
                return False

            # Let TextArea handle normal cursor movement first.
            if not at_bottom:
                return False

            if down_idx < len(entries) - 1:
                next_idx = down_idx + 1
                self._history_nav_index = next_idx
                self._set_interact_input_text(entries[next_idx])
            else:
                self._history_nav_index = None
                draft = self._history_nav_draft
                self._history_nav_draft = None
                self._set_interact_input_text(draft or "", cursor_end=True)
            return True

        return False

    def _append_interact_history(self, text: str) -> None:
        target = self._history_target_key()
        if not target:
            return
        append_history(target, text)

    def _prune_interact_histories(self) -> None:
        """Delete history files for agent names that are no longer present."""
        live_targets: set[str] = {self._history_key_for_agent(a) for a in self.agents}
        prune_histories(live_targets)

    # ── Agent priorities / tasks / dependencies ───────────────────

    def _load_agent_tasks(self) -> None:
        self._agent_tasks = load_agent_tasks()

    def _save_agent_tasks(self) -> None:
        save_agent_tasks(self._agent_tasks)

    def _load_agent_dependencies(self) -> None:
        self._agent_dependencies = load_agent_dependencies()

    def _save_agent_dependencies(self) -> None:
        save_agent_dependencies(self._agent_dependencies)

    def _reconcile_agent_dependencies(self) -> None:
        """Clear stale blockers only after consecutive missing polls."""
        if not self._agent_dependencies:
            self._dependency_missing_polls.clear()
            return

        live_dep_keys = {
            self._agent_dependency_key(agent)
            for agent in self.agents
        }

        changed = False
        for blocked_dep_key, blocker_dep_key in list(self._agent_dependencies.items()):
            if blocked_dep_key == blocker_dep_key:
                self._agent_dependencies.pop(blocked_dep_key, None)
                self._dependency_missing_polls.pop(blocked_dep_key, None)
                changed = True
                continue

            # If the blocked agent is not currently present, keep dependency.
            if blocked_dep_key not in live_dep_keys:
                self._dependency_missing_polls.pop(blocked_dep_key, None)
                continue

            if blocker_dep_key in live_dep_keys:
                self._dependency_missing_polls.pop(blocked_dep_key, None)
                continue

            misses = self._dependency_missing_polls.get(blocked_dep_key, 0) + 1
            self._dependency_missing_polls[blocked_dep_key] = misses
            if misses < 2:
                continue

            blocked_agent = self._agent_by_dependency_key(blocked_dep_key)
            blocked_name = blocked_agent.name if blocked_agent else blocked_dep_key
            self._agent_dependencies.pop(blocked_dep_key, None)
            self._dependency_missing_polls.pop(blocked_dep_key, None)
            self.notify(
                f"Dependency cleared for {blocked_name}: blocker missing",
                timeout=3,
            )
            changed = True

        if changed:
            self._save_agent_dependencies()

    @staticmethod
    def _read_json_dict(path: Path) -> dict[str, object] | None:
        """Best-effort JSON-dict loader."""
        import json

        try:
            raw = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    @staticmethod
    def _write_json_dict(path: Path, data: Mapping[str, object]) -> None:
        """Persist a JSON dictionary to disk."""
        import json

        path.write_text(json.dumps(data))

    def _load_priorities(self) -> None:
        """Load priorities from disk."""
        data = self._read_json_dict(PRIORITIES_FILE)
        if data is None:
            return
        self._agent_priorities = {
            k: v for k, v in data.items()
            if isinstance(k, str) and isinstance(v, int) and 1 <= v <= 4
        }

    def _save_priorities(self) -> None:
        """Persist priorities to disk."""
        self._write_json_dict(PRIORITIES_FILE, self._agent_priorities)

    # ── Panel visibility ───────────────────────────────────────────

    def _load_panel_visibility(self) -> None:
        """Load panel toggle states from disk."""
        data = self._read_json_dict(PANEL_VISIBILITY_FILE)
        if data is None:
            return

        self._show_interact_input = bool(data.get("interact_input", True))
        self._show_minimap = bool(data.get("minimap", True))
        self._show_sparklines = bool(data.get("sparklines", True))
        self._show_target_band = bool(data.get("target_band", True))

        # Migrate legacy "table" flag away (table is always visible now).
        if "table" in data:
            try:
                self._write_json_dict(
                    PANEL_VISIBILITY_FILE,
                    {
                        "interact_input": self._show_interact_input,
                        "minimap": self._show_minimap,
                        "sparklines": self._show_sparklines,
                        "target_band": self._show_target_band,
                    },
                )
            except OSError:
                pass

    def _save_panel_visibility(self) -> None:
        """Persist panel toggle states to disk."""
        self._write_json_dict(
            PANEL_VISIBILITY_FILE,
            {
                "interact_input": self._show_interact_input,
                "minimap": self._show_minimap,
                "sparklines": self._show_sparklines,
                "target_band": self._show_target_band,
            },
        )

    def _apply_panel_visibility(self) -> None:
        """Apply current panel visibility flags to widgets."""
        mini = self.query_one("#mini-map", Static)
        spark = self.query_one("#sparkline-chart", Static)
        target = self.query_one("#interact-target", Static)
        interact_input = self.query_one("#interact-input", ZeusTextArea)

        if self._show_interact_input:
            interact_input.remove_class("hidden")
        else:
            interact_input.add_class("hidden")
            if self.focused is interact_input:
                self.query_one("#agent-table", DataTable).focus()

        if self._show_minimap:
            mini.remove_class("hidden")
        else:
            mini.add_class("hidden")

        if self._show_sparklines:
            spark.remove_class("hidden")
        else:
            spark.add_class("hidden")

        # Keep target band visually coupled to interact input visibility.
        if self._show_target_band and self._show_interact_input:
            target.remove_class("hidden")
        else:
            target.add_class("hidden")

    def _get_priority(self, agent_name: str) -> int:
        """Return priority for an agent (1=high … 4=paused, default=3)."""
        return self._agent_priorities.get(agent_name, 3)

    def _is_paused(self, agent: AgentWindow) -> bool:
        return self._get_priority(agent.name) == 4

    def _is_text_input_focused(self) -> bool:
        return isinstance(self.focused, (Input, TextArea, ZeusTextArea))

    def _has_modal_open(self) -> bool:
        return len(self.screen_stack) > 1

    def _has_blocking_modal_open(self) -> bool:
        """Return True for modal dialogs that should block table actions."""
        if not self._has_modal_open():
            return False
        return not isinstance(self.screen, ExpandedOutputScreen)

    def _should_ignore_table_action(self) -> bool:
        """Return True when table-centric actions should be ignored."""
        return self._is_text_input_focused() or self._has_blocking_modal_open()

    def action_noop(self) -> None:
        """Deliberately ignore key presses bound to no-op actions."""
        return

    def action_cycle_priority(self) -> None:
        """Cycle priority 3→2→1→4→3 for the selected agent."""
        if self._should_ignore_table_action():
            return
        agent = self._get_selected_agent()
        if not agent:
            return
        cur = self._get_priority(agent.name)
        nxt = {4: 3, 3: 2, 2: 1, 1: 4}[cur]
        if nxt == 3:
            self._agent_priorities.pop(agent.name, None)
        else:
            self._agent_priorities[agent.name] = nxt
        self._save_priorities()
        self.poll_and_update()
        if self._interact_visible:
            self._refresh_interact_panel()

    # ── Event handlers ────────────────────────────────────────────────

    def _dismiss_splash(self) -> bool:
        """Dismiss splash if present. Returns True if dismissed."""
        for splash in self.query(SplashOverlay):
            splash.dismiss()
            return True
        return False

    def on_app_focus(self, event: events.AppFocus | None = None) -> None:
        """Restore table focus when the Zeus window regains app focus."""
        if self._has_modal_open():
            return
        try:
            self.query_one("#agent-table", DataTable).focus()
        except LookupError:
            return

    def on_key(self, event: events.Key) -> None:
        """Intercept special keys."""
        if self._dismiss_splash():
            event.prevent_default()
            event.stop()
            return

        if self._dismiss_celebration():
            event.prevent_default()
            event.stop()
            return

        if event.key == "enter" and isinstance(self.focused, DataTable):
            event.prevent_default()
            event.stop()
            # Focus interact input when available; otherwise open message dialog.
            if self._interact_visible and self._show_interact_input:
                self.query_one("#interact-input", ZeusTextArea).focus()
            elif not self._show_interact_input:
                self.action_agent_message()
            return

        if event.key in {"up", "down"} and isinstance(self.focused, ZeusTextArea):
            ta = self.query_one("#interact-input", ZeusTextArea)
            if self.focused is ta and self._handle_interact_history_nav(event.key):
                event.prevent_default()
                event.stop()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Resize interact input to fit content (1 line min, 8 max)."""
        ta = event.text_area
        if ta.id != "interact-input":
            return
        self._resize_interact_input(ta)

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        # Cancel previous timer
        if self._highlight_timer is not None:
            self._highlight_timer.stop()
        # Schedule interact refresh after 0.5s
        self._highlight_timer = self.set_timer(
            0.3, self._on_highlight_settled,
        )

    def _on_highlight_settled(self) -> None:
        """Called 0.5s after row highlight settles."""
        self._highlight_timer = None
        if self._interact_visible:
            self._refresh_interact_panel()

    def on_data_table_row_selected(
        self, event: DataTable.RowSelected
    ) -> None:
        # Click/Enter: immediate refresh + focus input
        if self._interact_visible:
            self._refresh_interact_panel()
            if self._show_interact_input:
                self.query_one("#interact-input", ZeusTextArea).focus()

    _last_kill_time: float = 0.0

    def _activate_selected_row(self) -> None:
        if time.time() - self._last_kill_time < 1.0:
            return
        if self._interact_visible:
            self._refresh_interact_panel()
            return
        tmux = self._get_selected_tmux()
        if tmux:
            self._attach_tmux(tmux)
            return
        agent = self._get_selected_agent()
        if not agent:
            return
        if self._is_hidden_agent(agent):
            self._focus_hidden_agent(agent)
            return
        focus_window(agent)
        self.notify(f"Focused: {agent.name}", timeout=2)

    def on_click(self, event: events.Click) -> None:
        if self._dismiss_splash():
            return
        if event.chain < 2:
            return
        table = self.query_one("#agent-table", DataTable)
        w = event.widget
        if w is None:
            return
        if w is not table and table not in w.ancestors:
            return
        self.set_timer(0.05, self._activate_selected_row)

    # ── Kill ──────────────────────────────────────────────────────────

    def action_kill_agent(self) -> None:
        if self._should_ignore_table_action():
            return
        agent = self._get_selected_agent()
        if agent:
            self.push_screen(ConfirmKillScreen(agent))
            return
        tmux = self._get_selected_tmux()
        if tmux:
            self.push_screen(ConfirmKillTmuxScreen(tmux))

    def action_kill_tmux_session(self) -> None:
        """Ctrl+K: hard-kill selected tmux session process."""
        if self._should_ignore_table_action():
            return
        tmux = self._get_selected_tmux()
        if not tmux:
            self.notify("Select a tmux row to kill session", timeout=2)
            return
        self.do_kill_tmux_session(tmux)

    def do_kill_agent(self, agent: AgentWindow) -> None:
        if self._is_hidden_agent(agent):
            sess_name = (agent.tmux_session or "").strip()
            if not sess_name:
                self.notify(f"Kill failed: {agent.name}", timeout=3)
                return
            ok, detail = kill_hidden_session(sess_name)
            if ok:
                self.notify(f"Killed: {agent.name}", timeout=2)
            else:
                reason = detail or agent.name
                self.notify(f"Kill failed: {reason}", timeout=3)
            self.poll_and_update()
            return

        close_window(agent)
        self.notify(f"Killed: {agent.name}", timeout=2)
        self.poll_and_update()

    def do_kill_tmux(self, sess: TmuxSession) -> None:
        """Detach tmux session and close the kitty window hosting it."""
        self._last_kill_time = time.time()
        kitty_pid: int | None = None
        client_pid = self._get_tmux_client_pid(sess.name)
        if client_pid is not None:
            kitty_pid = find_ancestor_pid_by_comm(client_pid, "kitty")

        try:
            subprocess.run(
                ["tmux", "detach-client", "-s", sess.name, "-a"],
                capture_output=True, timeout=3)
            subprocess.run(
                ["tmux", "detach-client", "-s", sess.name],
                capture_output=True, timeout=3)

            if kitty_pid:
                kill_pid(kitty_pid)

            self.notify(f"Detached: {sess.name}", timeout=2)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            self.notify(f"Detach failed: {e}", timeout=3)
        self.poll_and_update()

    def do_kill_tmux_session(self, sess: TmuxSession) -> None:
        """Kill tmux session process and close the kitty client when possible."""
        self._last_kill_time = time.time()
        kitty_pid: int | None = None
        client_pid = self._get_tmux_client_pid(sess.name)
        if client_pid is not None:
            kitty_pid = find_ancestor_pid_by_comm(client_pid, "kitty")

        try:
            result = subprocess.run(
                ["tmux", "kill-session", "-t", sess.name],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                if detail:
                    self.notify(f"Kill tmux failed: {detail}", timeout=3)
                else:
                    self.notify(f"Kill tmux failed: {sess.name}", timeout=3)
                return

            if kitty_pid:
                kill_pid(kitty_pid)

            self.notify(f"Killed tmux: {sess.name}", timeout=2)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            self.notify(f"Kill tmux failed: {e}", timeout=3)
        finally:
            self.poll_and_update()

    # ── New / Sub-agent / Rename ──────────────────────────────────────

    def schedule_polemarch_bootstrap(self, agent_id: str, requested_name: str) -> None:
        """Queue a one-time bootstrap message for a newly invoked Polemarch."""
        clean_id = agent_id.strip()
        if not clean_id:
            return
        self._pending_polemarch_bootstraps[clean_id] = requested_name.strip() or clean_id

    def _polemarch_bootstrap_message(self, polemarch_name: str) -> str:
        msg_file_hint = f"{MESSAGE_TMP_DIR}/zeus-msg-<uuid>.md"
        return textwrap.dedent(
            f"""
            You are the agent named {polemarch_name}.

            Role identity:
            - Your current role is: polemarch.
            - A polemarch is a coordinator role in Zeus, not your personal name.
            - There can be multiple polemarch agents in different sessions.

            Introduction context:
            - This message is onboarding only.
            - The Oracle (the user) will send your concrete task in the following message.
            - Do not execute task work until that Oracle instruction arrives.

            Polemarch responsibilities:
            - Analyze the global problem.
            - Split it into independent parallel work packets.
            - Instantiate Hoplites for each packet.
            - Coordinate outputs and synthesize final results.

            Hoplite instantiation contract (use exactly this):

            POLEMARCH_ID="${{ZEUS_AGENT_ID:?missing ZEUS_AGENT_ID}}"
            PHALANX_ID="phalanx-${{POLEMARCH_ID}}"
            HOPLITE_ID="$(python - <<'PY'
            import uuid; print(uuid.uuid4().hex)
            PY
            )"
            SESSION="hoplite-${{HOPLITE_ID:0:8}}"
            HOPLITE_NAME="hoplite-${{HOPLITE_ID:0:4}}"

            tmux new-session -d -s "$SESSION" -c "$PWD" \
              "ZEUS_AGENT_NAME=$HOPLITE_NAME ZEUS_AGENT_ID=$HOPLITE_ID ZEUS_PARENT_ID=$POLEMARCH_ID ZEUS_PHALANX_ID=$PHALANX_ID ZEUS_ROLE=hoplite exec pi"

            tmux set-option -t "$SESSION" @zeus_owner "$POLEMARCH_ID"
            tmux set-option -t "$SESSION" @zeus_agent "$HOPLITE_ID"
            tmux set-option -t "$SESSION" @zeus_role "hoplite"
            tmux set-option -t "$SESSION" @zeus_phalanx "$PHALANX_ID"

            Important:
            - Only AGENT-based tmux sessions initialized with this contract are Hoplites.
            - Generic tmux viewer sessions are not Hoplites and not part of your Phalanx.

            Canonical communication contract (MANDATORY):
            - Use ONLY the canonical tool: zeus-msg send.
            - This applies to Polemarch -> Hoplite, Hoplite -> Polemarch,
              and Hoplite -> Hoplite messages.
            - Write payload to a message-tmp file, then send with exactly one of:
              zeus-msg send --to phalanx --file {msg_file_hint}
              zeus-msg send --to polemarch --file {msg_file_hint}
              zeus-msg send --to hoplite:<ZEUS_AGENT_ID> --file {msg_file_hint}
            - DO NOT use any non-canonical transport (tmux send-keys,
              kitty send-text, manual copy/paste, ad-hoc shared files,
              or any custom relay script) for agent-to-agent communication.
            - DO NOT poll message-tmp files as a communication protocol.
            - Delivery is at-least-once transport-ack; keep payloads idempotent.
            """
        ).strip()

    def _deliver_pending_polemarch_bootstraps(self) -> None:
        if not self._pending_polemarch_bootstraps:
            return

        agents_by_id = {a.agent_id: a for a in self.agents if a.agent_id}
        for agent_id in list(self._pending_polemarch_bootstraps.keys()):
            polemarch = agents_by_id.get(agent_id)
            if polemarch is None:
                continue

            self._send_text_to_agent(
                polemarch,
                self._polemarch_bootstrap_message(polemarch.name),
            )
            self.notify(f"Polemarch bootstrap sent: {polemarch.name}", timeout=3)
            self._pending_polemarch_bootstraps.pop(agent_id, None)

    def action_new_agent(self) -> None:
        self.push_screen(NewAgentScreen())

    def action_agent_tasks(self) -> None:
        if self._has_blocking_modal_open():
            return
        agent = self._get_selected_agent()
        if not agent:
            self.notify("Select a Hippeus row to edit tasks", timeout=2)
            return
        self.push_screen(AgentTasksScreen(agent, self._task_text_for_agent(agent)))

    def do_save_agent_tasks(self, agent: AgentWindow, task_text: str) -> None:
        key = self._agent_tasks_key(agent)
        clean = task_text.rstrip()
        if clean.strip():
            self._agent_tasks[key] = clean
            self.notify(f"Saved tasks: {agent.name}", timeout=2)
        else:
            self._agent_tasks.pop(key, None)
            self.notify(f"Cleared tasks: {agent.name}", timeout=2)
        self._save_agent_tasks()
        self.poll_and_update()

    def action_expand_output(self) -> None:
        if self._should_ignore_table_action():
            return
        agent = self._get_selected_agent()
        if not agent:
            self.notify("Select a Hippeus row to expand output", timeout=2)
            return
        self.push_screen(ExpandedOutputScreen(agent))

    def action_agent_message(self) -> None:
        if self._should_ignore_table_action():
            return
        agent = self._get_selected_agent()
        if not agent:
            self.notify("Select a Hippeus row to message", timeout=2)
            return
        self.push_screen(AgentMessageScreen(agent, self._message_draft_for_agent(agent)))

    def action_message_history(self) -> None:
        if self._should_ignore_table_action():
            return
        agent = self._get_selected_agent()
        if not agent:
            self.notify("Select a Hippeus row to show history", timeout=2)
            return

        entries = load_history(self._history_key_for_agent(agent))
        self.push_screen(LastSentMessageScreen(agent, entries))

    def action_go_ahead(self) -> None:
        """G: queue fixed 'go ahead' message for selected Hippeus."""
        if self._should_ignore_table_action():
            return

        agent = self._get_selected_agent()
        if not agent:
            self.notify("Select a Hippeus row to queue go ahead", timeout=2)
            return

        prepared = self._prepare_message_dialog_send(agent, "go ahead")
        if prepared is None:
            return

        live, clean = prepared
        self._queue_text_to_agent_interact(live, clean)
        self.notify(f"Queued go ahead: {live.name}", timeout=2)

    def _resume_agent_if_paused(self, agent: AgentWindow) -> bool:
        """Set paused agents back to default priority (3)."""
        if not self._is_paused(agent):
            return False
        self._agent_priorities.pop(agent.name, None)
        self._save_priorities()
        return True

    def _message_dialog_block_reason(self, agent: AgentWindow) -> str | None:
        if self._is_blocked(agent):
            return "Hippeus is BLOCKED by dependency; input disabled"
        return None

    def _prepare_message_dialog_send(
        self,
        agent: AgentWindow,
        text: str,
    ) -> tuple[AgentWindow, str] | None:
        clean = text.strip()
        if not clean:
            return None

        live = self._get_agent_by_key(self._agent_key(agent))
        if live is None:
            self.notify("Target is no longer active", timeout=2)
            return None

        block_reason = self._message_dialog_block_reason(live)
        if block_reason:
            self.notify(block_reason, timeout=2)
            return None

        self._resume_agent_if_paused(live)
        return live, clean

    def do_send_agent_message(self, agent: AgentWindow, text: str) -> bool:
        prepared = self._prepare_message_dialog_send(agent, text)
        if prepared is None:
            return False

        live, clean = prepared
        self._send_text_to_agent(live, clean)
        self.do_clear_agent_message_draft(live)
        return True

    def do_queue_agent_message(self, agent: AgentWindow, text: str) -> bool:
        prepared = self._prepare_message_dialog_send(agent, text)
        if prepared is None:
            return False

        live, clean = prepared
        self._queue_text_to_agent_interact(live, clean)
        self.do_clear_agent_message_draft(live)
        return True

    @staticmethod
    def _task_entry_from_message_text(text: str) -> str | None:
        clean = text.strip()
        if not clean:
            return None

        lines = clean.splitlines()
        first = lines[0].strip()
        task_entry = f"- [ ] {first}"
        if len(lines) > 1:
            task_entry += "\n" + "\n".join(lines[1:])
        return task_entry

    def do_add_agent_message_task(self, agent: AgentWindow, text: str) -> bool:
        task_entry = self._task_entry_from_message_text(text)
        if task_entry is None:
            return False

        key = self._agent_tasks_key(agent)
        existing = self._agent_tasks.get(key, "").rstrip()
        updated = f"{existing}\n{task_entry}" if existing else task_entry

        self._agent_tasks[key] = updated
        self._save_agent_tasks()
        self.do_clear_agent_message_draft(agent)
        self.notify(f"Added task: {agent.name}", timeout=2)
        self._render_agent_table_and_status()
        if self._interact_visible:
            self._refresh_interact_panel()
        return True

    def do_prepend_agent_message_task(self, agent: AgentWindow, text: str) -> bool:
        task_entry = self._task_entry_from_message_text(text)
        if task_entry is None:
            return False

        key = self._agent_tasks_key(agent)
        existing = self._agent_tasks.get(key, "").rstrip()
        updated = f"{task_entry}\n{existing}" if existing else task_entry

        self._agent_tasks[key] = updated
        self._save_agent_tasks()
        self.do_clear_agent_message_draft(agent)
        self.notify(f"Added task at start: {agent.name}", timeout=2)
        self._render_agent_table_and_status()
        if self._interact_visible:
            self._refresh_interact_panel()
        return True

    def action_queue_next_task(self) -> None:
        """N: queue next task from selected Hippeus tasks."""
        if self._should_ignore_table_action():
            return

        agent = self._get_selected_agent()
        if not agent:
            self.notify("Select a Hippeus row to queue next task", timeout=2)
            return

        key = self._agent_tasks_key(agent)
        task_text = self._agent_tasks.get(key, "")
        extracted = _extract_next_task(task_text)
        if extracted is None:
            self.notify(f"No task found for {agent.name}", timeout=2)
            return

        message, updated_task_text = extracted
        if not message.strip():
            self.notify("Next task is empty; nothing queued", timeout=2)
            return

        self._queue_text_to_agent(agent, message)

        if updated_task_text.strip():
            self._agent_tasks[key] = updated_task_text
        else:
            self._agent_tasks.pop(key, None)

        self._save_agent_tasks()
        self.notify(f"Queued next task: {agent.name}", timeout=3)
        self._render_agent_table_and_status()
        if self._interact_visible:
            self._refresh_interact_panel()

    def action_clear_done_tasks(self) -> None:
        """Ctrl+T: clear all done tasks for selected Hippeus."""
        if self._has_blocking_modal_open():
            return

        agent = self._get_selected_agent()
        if not agent:
            self.notify("Select a Hippeus row to clear done tasks", timeout=2)
            return

        key = self._agent_tasks_key(agent)
        task_text = self._agent_tasks.get(key, "")
        updated_task_text, removed = clear_done_tasks(task_text)
        if removed <= 0:
            self.notify(f"No done tasks to clear for {agent.name}", timeout=2)
            return

        if updated_task_text.strip():
            self._agent_tasks[key] = updated_task_text
        else:
            self._agent_tasks.pop(key, None)

        self._save_agent_tasks()
        suffix = "" if removed == 1 else "s"
        self.notify(f"Cleared {removed} done task{suffix}: {agent.name}", timeout=2)
        self._render_agent_table_and_status()
        if self._interact_visible:
            self._refresh_interact_panel()

    def action_toggle_aegis(self) -> None:
        """A: toggle Aegis automation for the selected Hippeus row."""
        if self._should_ignore_table_action():
            return

        agent = self._get_selected_agent()
        if not agent:
            self.notify("Select a Hippeus row to toggle Aegis", timeout=2)
            return

        key = self._agent_key(agent)
        if key in self._aegis_enabled:
            self._disable_aegis(key)
            self.notify(f"Aegis disabled: {agent.name}", timeout=2)
            self._render_agent_table_and_status()
            if self._interact_visible:
                self._refresh_interact_panel()
            return

        if self._is_input_blocked(agent):
            self.notify(
                f"Aegis unavailable for blocked/paused Hippeus: {agent.name}",
                timeout=2,
            )
            return

        self._aegis_enabled.add(key)
        self._aegis_modes[key] = self._AEGIS_MODE_ARMED
        self.notify(f"Aegis enabled: {agent.name}", timeout=2)

        self._render_agent_table_and_status()
        if self._interact_visible:
            self._refresh_interact_panel()

    def action_toggle_dependency(self) -> None:
        """D: toggle blocked dependency for selected agent."""
        if self._has_blocking_modal_open():
            return

        blocked_agent = self._get_selected_agent()
        if not blocked_agent:
            self.notify("Select a Hippeus row to set dependency", timeout=2)
            return

        blocked_dep_key = self._agent_dependency_key(blocked_agent)
        if blocked_dep_key in self._agent_dependencies:
            self._agent_dependencies.pop(blocked_dep_key, None)
            self._dependency_missing_polls.pop(blocked_dep_key, None)
            self._save_agent_dependencies()
            self.notify(f"Dependency cleared: {blocked_agent.name}", timeout=2)
            self.poll_and_update()
            if self._interact_visible:
                self._refresh_interact_panel()
            return

        options: list[tuple[str, str]] = []
        blocked_row_key = self._agent_key(blocked_agent)
        for candidate in sorted(self.agents, key=lambda a: a.name.lower()):
            if self._agent_key(candidate) == blocked_row_key:
                continue
            options.append((candidate.name, self._agent_dependency_key(candidate)))

        if not options:
            self.notify("No other Hippeis available as dependency targets", timeout=2)
            return

        self.push_screen(DependencySelectScreen(blocked_agent, options))

    def do_set_dependency(
        self,
        blocked_agent: AgentWindow,
        blocker_dep_key: str,
    ) -> None:
        blocked_dep_key = self._agent_dependency_key(blocked_agent)
        live_blocked = self._agent_by_dependency_key(blocked_dep_key)
        if live_blocked is None:
            self.notify("Selected blocked Hippeus is no longer active", timeout=2)
            return

        if blocker_dep_key == blocked_dep_key:
            self.notify("A Hippeus cannot depend on itself", timeout=2)
            return

        blocker = self._agent_by_dependency_key(blocker_dep_key)
        if blocker is None:
            self.notify("Selected dependency target is no longer active", timeout=2)
            return

        if self._would_create_dependency_cycle(blocked_dep_key, blocker_dep_key):
            self.notify("Dependency rejected: would create cycle", timeout=3)
            return

        self._agent_dependencies[blocked_dep_key] = blocker_dep_key
        self._dependency_missing_polls.pop(blocked_dep_key, None)
        self._save_agent_dependencies()
        self.notify(f"{live_blocked.name} blocked by {blocker.name}", timeout=3)
        self.poll_and_update()
        if self._interact_visible:
            self._refresh_interact_panel()

    def action_promote_selected(self) -> None:
        if self._should_ignore_table_action():
            return

        tmux = self._get_selected_tmux()
        if tmux is not None:
            parent = self._get_parent_agent_for_tmux(tmux)
            if parent is None or not self._is_hoplite_session_for(parent, tmux):
                self.notify("Select a Hoplite tmux row to promote", timeout=3)
                return
            self.push_screen(ConfirmPromoteScreen(sess=tmux))
            return

        agent = self._get_selected_agent()
        if not agent:
            self.notify("No Hippeus selected", timeout=2)
            return

        if self._is_hidden_agent(agent):
            self.notify(f"{agent.name} is already a Hidden Hippeus", timeout=3)
            return

        if not self._has_promotable_parent(agent):
            self.notify(f"{agent.name} is already a top-level Hippeus", timeout=3)
            return

        self.push_screen(ConfirmPromoteScreen(agent=agent))

    def do_promote_sub_hippeus(self, agent: AgentWindow) -> bool:
        agent_id = (agent.agent_id or "").strip()
        if not agent_id:
            self.notify(f"Cannot promote {agent.name}: missing agent id", timeout=3)
            return False

        if not self._has_promotable_parent(agent):
            self.notify(f"{agent.name} is already a top-level Hippeus", timeout=3)
            return False

        session_path, source = resolve_agent_session_path_with_source(agent)

        if source == "cwd":
            same_cwd = [a for a in self.agents if a.cwd == agent.cwd]
            if len(same_cwd) > 1:
                self.notify(
                    "Cannot reliably promote this legacy sub-Hippeus: multiple "
                    "Hippeis share the same cwd without pinned sessions. "
                    "Restart the sub-Hippeus and try again.",
                    timeout=4,
                )
                return False

        if not session_path or not os.path.isfile(session_path):
            if source == "env":
                self.notify(
                    f"Pinned session path is stale for {agent.name}. "
                    "Run /reload in that Hippeus, then retry.",
                    timeout=4,
                )
            else:
                self.notify(f"No session found for {agent.name}", timeout=3)
            return False

        close_window(agent)

        env: dict[str, str] = os.environ.copy()
        env["ZEUS_AGENT_NAME"] = agent.name
        env["ZEUS_AGENT_ID"] = agent_id
        env["ZEUS_ROLE"] = "hippeus"
        env["ZEUS_SESSION_PATH"] = session_path
        env.pop("ZEUS_PARENT_ID", None)
        env.pop("ZEUS_PHALANX_ID", None)

        try:
            proc = subprocess.Popen(
                [
                    "kitty",
                    "--directory",
                    agent.cwd,
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
        except (FileNotFoundError, OSError) as exc:
            self.notify(f"Promote failed for {agent.name}: {exc}", timeout=3)
            return False

        if agent.workspace and agent.workspace != "?":
            move_pid_to_workspace_and_focus_later(
                proc.pid,
                agent.workspace,
                delay=0.5,
            )

        self.notify(f"Promoted sub-Hippeus to Hippeus: {agent.name}", timeout=3)
        self.set_timer(1.0, self.poll_and_update)
        if self._interact_visible:
            self._refresh_interact_panel()
        return True

    def do_promote_hoplite_tmux(self, sess: TmuxSession) -> bool:
        parent = self._get_parent_agent_for_tmux(sess)
        if parent is None or not self._is_hoplite_session_for(parent, sess):
            self.notify("Selected tmux row is not a Hoplite", timeout=3)
            return False

        ok, detail = promote_hoplite_to_hidden_hippeus(sess)
        if not ok:
            self.notify(f"Promote failed for {sess.name}: {detail}", timeout=3)
            return False

        self.notify(f"Promoted Hoplite to Hidden Hippeus: {sess.name}", timeout=3)
        self.poll_and_update()
        if self._interact_visible:
            self._refresh_interact_panel()
        return True

    def action_spawn_subagent(self) -> None:
        if self._should_ignore_table_action():
            return
        agent = self._get_selected_agent()
        if not agent:
            self.notify("No Hippeus selected", timeout=2)
            return

        if self._is_hidden_agent(agent) and not agent.session_path:
            recovered = resolve_hidden_session_path(agent.tmux_session)
            if recovered:
                agent.session_path = recovered

        session, source = resolve_agent_session_path_with_source(agent)

        if source == "cwd":
            same_cwd = [a for a in self.agents if a.cwd == agent.cwd]
            if len(same_cwd) > 1:
                self.notify(
                    "Cannot reliably fork this legacy Hippeus: multiple Hippeis "
                    "share the same cwd without pinned sessions. "
                    "Restart the parent Hippeus and try again.",
                    timeout=4,
                )
                return

        if not session or not os.path.isfile(session):
            if source == "env":
                self.notify(
                    f"Pinned session path is stale for {agent.name}. "
                    "Run /reload in that Hippeus, then retry.",
                    timeout=4,
                )
            else:
                self.notify(
                    f"No session found for {agent.name}", timeout=3
                )
            return

        if source == "runtime" and not agent.session_path:
            agent.session_path = session

        self.push_screen(SubAgentScreen(agent))

    def do_spawn_subagent(self, agent: AgentWindow, name: str) -> None:
        clean_name = name.strip()
        if self._is_agent_name_taken(clean_name):
            self.notify(f"Name already exists: {clean_name}", timeout=3)
            return

        result: str | None = spawn_subagent(
            agent, clean_name, workspace=agent.workspace
        )
        if result:
            self.notify(f"🧬 Spawned: {clean_name}", timeout=3)
            self.set_timer(1.5, self.poll_and_update)
        else:
            self.notify(
                f"Failed to fork session for {agent.name}", timeout=3
            )

    def action_rename(self) -> None:
        if self._should_ignore_table_action():
            return
        agent = self._get_selected_agent()
        if agent:
            self.push_screen(RenameScreen(agent))
            return
        tmux = self._get_selected_tmux()
        if tmux:
            self.push_screen(RenameTmuxScreen(tmux))

    def do_rename_agent(self, agent: AgentWindow, new_name: str) -> bool:
        clean_name = new_name.strip()
        old_name = agent.name
        key = self._agent_key(agent)

        if not clean_name:
            return False
        if clean_name == old_name:
            return False
        if self._is_agent_name_taken(clean_name, exclude_key=key):
            self.notify(f"Name already exists: {clean_name}", timeout=3)
            return False

        overrides: dict[str, str] = load_names()
        overrides[key] = clean_name
        save_names(overrides)

        if old_name in self._agent_priorities:
            preserved_priority = self._agent_priorities.pop(old_name)
            self._agent_priorities[clean_name] = preserved_priority
            self._save_priorities()

        self.notify(f"Renamed: {old_name} → {clean_name}", timeout=3)
        self.poll_and_update()
        return True

    def do_rename_tmux(self, sess: TmuxSession, new_name: str) -> None:
        try:
            subprocess.run(
                ["tmux", "rename-session", "-t", sess.name, new_name],
                capture_output=True, timeout=3)
            self.notify(f"Renamed: {sess.name} → {new_name}", timeout=3)
            self.poll_and_update()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            self.notify(f"Rename failed: {e}", timeout=3)

    # ── Log panel ─────────────────────────────────────────────────────

    def action_show_help(self) -> None:
        if self._has_blocking_modal_open():
            return
        self.push_screen(HelpScreen())

    def action_toggle_interact_input(self) -> None:
        if self._has_blocking_modal_open():
            return
        self._show_interact_input = not self._show_interact_input
        self._apply_panel_visibility()
        self._save_panel_visibility()

    def action_toggle_minimap(self) -> None:
        if self._has_blocking_modal_open():
            return
        self._show_minimap = not self._show_minimap
        self._apply_panel_visibility()
        self._save_panel_visibility()

    def action_toggle_sparklines(self) -> None:
        if self._has_blocking_modal_open():
            return
        self._show_sparklines = not self._show_sparklines
        self._apply_panel_visibility()
        self._save_panel_visibility()

    def action_toggle_target_band(self) -> None:
        if self._has_blocking_modal_open():
            return
        self._show_target_band = not self._show_target_band
        self._apply_panel_visibility()
        self._save_panel_visibility()

    def action_toggle_split(self) -> None:
        self._split_mode = not self._split_mode
        panel = self.query_one("#interact-panel", Vertical)
        main = self.query_one("#main-content", Container)
        if self._split_mode:
            panel.add_class("split")
            main.add_class("split")
        else:
            panel.remove_class("split")
            main.remove_class("split")
        self._setup_table_columns()
        self.poll_and_update()
        if self._interact_visible:
            self._refresh_interact_panel()

    def action_toggle_sort(self) -> None:
        if self._should_ignore_table_action():
            return
        if self.sort_mode == SortMode.PRIORITY:
            self.sort_mode = SortMode.ALPHA
        else:
            self.sort_mode = SortMode.PRIORITY
        self.poll_and_update()

    def action_toggle_focus(self) -> None:
        """Tab: toggle focus between agent table and interact input."""
        if isinstance(self.focused, (ZeusTextArea, TextArea)):
            self.query_one("#agent-table", DataTable).focus()
        else:
            if self._interact_visible and self._show_interact_input:
                self.query_one("#interact-input", ZeusTextArea).focus()

    def action_toggle_interact_panel(self) -> None:
        """F8: toggle interact panel visibility."""
        panel = self.query_one("#interact-panel", Vertical)
        if self._interact_visible:
            self._interact_visible = False
            self._interact_agent_key = None
            self._interact_tmux_name = None
            self._set_interact_target_name("—")
            self._set_interact_editable(True)
            self._reset_history_nav()
            panel.remove_class("visible")
            self.query_one("#agent-table", DataTable).focus()
        else:
            self._interact_visible = True
            panel.add_class("visible")
            self._refresh_interact_panel()

    # ── Action-needed detection ─────────────────────────────────────

    _ACTION_PROMPT = (
        "You are a triage classifier. An AI coding agent is currently IDLE. "
        "Reply YES only if it is explicitly blocked and waiting for human "
        "input/approval/decision RIGHT NOW. Reply NO if it is done, standing "
        "by, acknowledged, or otherwise not waiting for human action. "
        "Prioritize the newest lines; older questions may be superseded by "
        "later messages. Reply with a SINGLE word: YES or NO.\n\n"
        "Terminal output (oldest to newest):\n"
    )

    def _get_screen_context(self, agent: AgentWindow) -> str:
        # Full extent keeps classification stable even if user scrolls kitty.
        text = self._read_agent_screen_text(agent, full=True)
        lines = text.splitlines()
        recent = [l for l in lines if l.strip()][-24:]
        return "\n".join(recent)

    @work(thread=True, group="action_check")
    def _check_action_needed(self, agent: AgentWindow, key: str) -> None:
        """Check if an idle agent needs human input."""
        context = self._get_screen_context(agent)
        if not context.strip():
            self.call_from_thread(self._finalize_action_check, key, False)
            return
        prompt = self._ACTION_PROMPT + context
        try:
            r = subprocess.run(
                ["pi", "--print", "--no-session", "--no-tools",
                 "--model", SETTINGS.summary_model, prompt],
                capture_output=True, text=True, timeout=30,
            )
            answer = r.stdout.strip().upper() if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            answer = ""
        needs_action = "YES" in answer and "NO" not in answer
        self.call_from_thread(self._finalize_action_check, key, needs_action)

    def _finalize_action_check(self, key: str, needs_action: bool) -> None:
        """Store action-needed result."""
        self._action_check_pending.discard(key)
        agent = self._get_agent_by_key(key)
        if not agent or agent.state != State.IDLE or self._is_input_blocked(agent):
            self._action_needed.discard(key)
            return
        if needs_action:
            self._action_needed.add(key)
        else:
            self._action_needed.discard(key)

    def _update_interact_stream(self) -> None:
        """Kick off background fetch for interact stream."""
        if not self._interact_visible:
            return
        if self._interact_tmux_name:
            self._fetch_interact_tmux_stream(self._interact_tmux_name)
            return
        agent = self._get_agent_by_key(self._interact_agent_key)
        if not agent:
            return
        self._fetch_interact_stream(agent)

    @work(thread=True, exclusive=True, group="interact_stream")
    def _fetch_interact_tmux_stream(self, sess_name: str) -> None:
        """Fetch tmux pane content in background thread."""
        try:
            r = subprocess.run(
                ["tmux", "capture-pane", "-t", sess_name,
                 "-p", "-e", "-S", "-200"],
                capture_output=True, text=True, timeout=3,
            )
            text = r.stdout if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            text = ""
        self.call_from_thread(self._apply_tmux_stream, sess_name, text)

    def _apply_tmux_stream(self, requested_name: str, screen_text: str) -> None:
        """Apply tmux pane content (no pi separator trimming)."""
        if not self._interact_visible:
            return
        if requested_name != self._interact_tmux_name:
            return
        stream = self.query_one("#interact-stream", RichLog)
        content = trim_trailing_blank_lines(screen_text)
        if not content.strip():
            stream.clear()
            stream.write(f"  [tmux:{requested_name}] (no output)")
            return
        raw = kitty_ansi_to_standard(content)
        stream.clear()
        stream.write(_linkify_rich_text(Text.from_ansi(raw)))

    @work(thread=True, exclusive=True, group="interact_stream")
    def _fetch_interact_stream(self, agent: AgentWindow) -> None:
        """Fetch screen text with ANSI formatting in background thread."""
        screen_text = self._read_agent_screen_text(agent, ansi=True)
        agent_key = self._agent_key(agent)
        self.call_from_thread(
            self._apply_interact_stream,
            agent_key,
            agent.name,
            screen_text,
        )

    def _apply_interact_stream(
        self,
        requested_agent_key: str,
        name: str,
        screen_text: str,
    ) -> None:
        """Apply fetched stream content on the main thread."""
        if not self._interact_visible:
            return
        if requested_agent_key != self._interact_agent_key:
            return

        stream = self.query_one("#interact-stream", RichLog)
        content = trim_trailing_blank_lines(strip_pi_input_chrome(screen_text))
        if not content.strip():
            stream.clear()
            stream.write(f"  [{name}] (no output)")
            return

        raw = kitty_ansi_to_standard(content)
        stream.clear()
        stream.write(_linkify_rich_text(Text.from_ansi(raw)))

    def _interact_target_agent(self) -> AgentWindow | None:
        """Resolve the agent that owns the current interact target."""
        if self._interact_agent_key:
            return self._get_agent_by_key(self._interact_agent_key)

        if self._interact_tmux_name:
            for agent in self.agents:
                if any(s.name == self._interact_tmux_name for s in agent.tmux_sessions):
                    return agent
        return None

    def _current_interact_block_reason(self) -> str | None:
        """Return reason text when interact input must be disabled."""
        agent = self._interact_target_agent()
        if agent and self._is_blocked(agent):
            return "Hippeus is BLOCKED by dependency; input disabled"
        return None

    @staticmethod
    def _normalize_outgoing_text(text: str) -> str:
        """Normalize outgoing text for terminal send-text compatibility."""
        return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")

    _QUEUE_SEQUENCE_DEFAULT: tuple[str, ...] = ("\x1b[13;3u", "\x03", "\x15")
    _QUEUE_SEQUENCE_LEGACY_W: tuple[str, ...] = ("\x1b[13;3u", "\x15", "\x15")

    def _dispatch_agent_text(
        self,
        agent: AgentWindow,
        text: str,
        *,
        queue_sequence: tuple[str, ...] | None = None,
    ) -> bool:
        """Send text to an agent either as plain Enter or queue sequence."""
        clean = self._normalize_outgoing_text(text)

        if self._is_hidden_agent(agent):
            ok = send_hidden_text(
                agent.tmux_session,
                clean,
                queue=queue_sequence is not None,
            )
            if ok:
                append_history(self._history_key_for_agent(agent), clean)
            return ok

        match = f"id:{agent.kitty_id}"

        if queue_sequence is None:
            result = kitty_cmd(
                agent.socket,
                "send-text",
                "--match",
                match,
                clean + "\r",
            )
            if result is not None:
                append_history(self._history_key_for_agent(agent), clean)
            return bool(result)

        if kitty_cmd(agent.socket, "send-text", "--match", match, clean) is None:
            return False

        for key in queue_sequence:
            if kitty_cmd(agent.socket, "send-text", "--match", match, key) is None:
                return False

        append_history(self._history_key_for_agent(agent), clean)
        return True

    def _dispatch_tmux_text(
        self,
        sess_name: str,
        text: str,
        *,
        queue: bool,
    ) -> bool:
        """Send text to tmux target as Enter or Alt+Enter queue."""
        wire_text = self._normalize_outgoing_text(text)
        key = "M-Enter" if queue else "Enter"
        try:
            r = subprocess.run(
                ["tmux", "send-keys", "-t", sess_name, wire_text, key],
                capture_output=True,
                timeout=3,
            )
            return r.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _send_text_to_agent(self, agent: AgentWindow, text: str) -> bool:
        """Send text to agent backend followed by Enter."""
        return self._dispatch_agent_text(agent, text)

    def _queue_text_to_agent(self, agent: AgentWindow, text: str) -> bool:
        """Queue cross-agent text and clear remote editor robustly."""
        return self._dispatch_agent_text(
            agent,
            text,
            queue_sequence=self._QUEUE_SEQUENCE_DEFAULT,
        )

    def _queue_text_to_agent_interact(self, agent: AgentWindow, text: str) -> bool:
        """Queue via Ctrl+W path (kept as legacy known-good behavior)."""
        return self._dispatch_agent_text(
            agent,
            text,
            queue_sequence=self._QUEUE_SEQUENCE_LEGACY_W,
        )

    def action_send_interact(self) -> None:
        """Send text from interact input to the agent/tmux (Ctrl+s)."""
        if self._has_modal_open():
            modal = self.screen
            if isinstance(modal, AgentMessageScreen):
                modal.action_send()
                return
            if isinstance(modal, AgentTasksScreen):
                modal.action_save()
            return

        if not self._interact_visible or not self._show_interact_input:
            return
        block_reason = self._current_interact_block_reason()
        if block_reason:
            self.notify(block_reason, timeout=2)
            return
        ta = self.query_one("#interact-input", ZeusTextArea)
        text = ta.text.strip()
        if not text:
            return
        self._append_interact_history(text)
        target_agent = self._interact_target_agent()
        if target_agent is not None:
            self._resume_agent_if_paused(target_agent)

        if self._interact_tmux_name:
            self._dispatch_tmux_text(self._interact_tmux_name, text, queue=False)
            ta.clear()
            ta.styles.height = 3
            self._reset_history_nav()
            return

        agent = self._get_agent_by_key(self._interact_agent_key)
        if not agent:
            self.notify("Hippeus no longer available", timeout=2)
            return
        self._send_text_to_agent(agent, text)
        ta.clear()
        ta.styles.height = 3
        self._reset_history_nav()

    def action_queue_interact(self) -> None:
        """Send text + Alt+Enter (queue in pi) to agent/tmux."""
        if self._has_modal_open():
            modal = self.screen
            if isinstance(modal, AgentMessageScreen):
                modal.action_queue()
            return

        if not self._interact_visible or not self._show_interact_input:
            return
        block_reason = self._current_interact_block_reason()
        if block_reason:
            self.notify(block_reason, timeout=2)
            return
        ta = self.query_one("#interact-input", ZeusTextArea)
        text = ta.text.strip()
        if not text:
            return
        self._append_interact_history(text)
        target_agent = self._interact_target_agent()
        if target_agent is not None:
            self._resume_agent_if_paused(target_agent)

        if self._interact_tmux_name:
            self._dispatch_tmux_text(self._interact_tmux_name, text, queue=True)
            ta.clear()
            ta.styles.height = 3
            self._reset_history_nav()
            return

        agent = self._get_agent_by_key(self._interact_agent_key)
        if not agent:
            self.notify("Hippeus no longer available", timeout=2)
            return
        # Keep Ctrl+W semantics on the long-standing queue path.
        self._queue_text_to_agent_interact(agent, text)
        ta.clear()
        ta.styles.height = 3
        self._reset_history_nav()

    def action_refresh(self) -> None:
        self.poll_and_update()


def cmd_dashboard(args: argparse.Namespace | None = None) -> None:
    app = ZeusApp()
    app.run()
