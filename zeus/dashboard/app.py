"""Zeus TUI dashboard — main App class."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from enum import Enum
import subprocess
import time

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Static, Label, Input, TextArea, RichLog
from textual.widget import Widget
from rich.text import Text


class SortMode(Enum):
    PRIORITY = "priority"
    ALPHA = "alpha"

from ..config import PRIORITIES_FILE
from ..settings import SETTINGS
from ..models import (
    AgentWindow, TmuxSession, State, UsageData, OpenAIUsageData,
)
from ..input_history import append_history, load_history, prune_histories
from ..process import fmt_bytes, read_process_metrics
from ..kitty import (
    discover_agents, get_screen_text, focus_window, close_window,
    spawn_subagent, load_names, save_names, kitty_cmd,
)
from ..sessions import find_current_session
from ..sway import build_pid_workspace_map
from ..tmux import (
    backfill_tmux_owner_options,
    discover_tmux_sessions,
    ensure_tmux_update_environment,
    match_tmux_to_agents,
)
from ..state import detect_state, parse_footer
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
    NewAgentScreen, SubAgentScreen,
    RenameScreen, RenameTmuxScreen,
    ConfirmKillScreen, ConfirmKillTmuxScreen,
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


def _compact_name(name: str, maxlen: int) -> str:
    """Dash-aware truncation: keep first + last segment."""
    if len(name) <= maxlen:
        return name
    parts = name.split("-")
    if len(parts) < 2:
        return name[: maxlen - 1] + "…"
    first, last = parts[0], parts[-1]
    joined = f"{first}…{last}"
    if len(joined) <= maxlen:
        return joined
    avail = maxlen - len(last) - 1  # 1 for …
    if avail >= 1:
        return f"{first[:avail]}…{last}"
    return name[: maxlen - 1] + "…"


class ZeusApp(App):
    TITLE = "Zeus"
    DEFAULT_CSS = APP_CSS
    BINDINGS = [
        Binding("q", "stop_agent", "Stop Agent"),
        Binding("ctrl+q", "force_stop_agent", "Stop Agent", show=False, priority=True),
        Binding("f10", "quit", "Quit"),
        Binding("tab", "toggle_focus", "Switch focus", show=False),
        Binding("ctrl+enter", "focus_agent", "Teleport", priority=True),
        Binding("n", "new_agent", "New Agent"),
        Binding("s", "spawn_subagent", "Sub-Agent"),
        Binding("k", "kill_agent", "Kill Agent"),
        Binding("p", "cycle_priority", "Priority"),
        Binding("r", "rename", "Rename"),
        Binding("f5", "refresh", "Refresh", show=False),

        Binding("ctrl+s", "send_interact", "Send", show=False, priority=True),
        Binding("ctrl+w", "queue_interact", "Queue", show=False, priority=True),


        Binding("1", "toggle_table", "Table", show=False),
        Binding("2", "toggle_minimap", "Map", show=False),
        Binding("3", "toggle_sparklines", "Sparks", show=False),
        Binding("f4", "toggle_sort", "Sort"),
        Binding("f6", "toggle_split", "Split"),

        Binding("f8", "toggle_interact_panel", "Panel"),
        Binding("question_mark", "show_help", "?", key_display="?"),
    ]

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
    _sparkline_samples: dict[str, list[str]] = {}  # agent_name → state labels
    _minimap_agents: list[str] = []
    prev_states: dict[str, State] = {}
    state_changed_at: dict[str, float] = {}
    idle_since: dict[str, float] = {}
    idle_notified: set[str] = set()
    _history_nav_target: str | None = None
    _history_nav_index: int | None = None

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
                    UsageBar("Extra:", classes="usage-item", id="usage-extra"),
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
                id="interact-panel",
                classes="visible split",
            ),
            id="main-content",
            classes="split",
        )
        yield Static("", id="status-line")
        yield SplashOverlay(id="splash")

    _FULL_COLUMNS = SETTINGS.columns.wide.order
    _SPLIT_COLUMNS = SETTINGS.columns.split.order
    _COL_WIDTHS: dict[str, int] = SETTINGS.columns.wide.widths
    _COL_WIDTHS_SPLIT: dict[str, int] = SETTINGS.columns.split.widths

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
        self._load_priorities()
        table = self.query_one("#agent-table", DataTable)
        table.show_row_labels = False
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.query_one("#interact-stream", RichLog).can_focus = False
        self._setup_table_columns()
        self.poll_and_update()
        self.set_interval(SETTINGS.poll_interval, self.poll_and_update)
        self.set_interval(1.0, self.update_clock)
        self.set_interval(1.0, self._update_interact_stream)

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

        usage = read_usage()
        openai = read_openai_usage()

        for a in agents:
            screen: str = get_screen_text(a)
            a._screen_text = screen
            a.state = detect_state(screen)
            a.model, a.ctx_pct, a.tokens_in, a.tokens_out = parse_footer(
                screen
            )
            a.workspace = pid_ws.get(a.kitty_pid, "?")
            a.proc_metrics = read_process_metrics(a.kitty_pid)

        # Read tmux pane metrics in the worker too
        match_tmux_to_agents(agents, tmux_sessions)
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
            akey: str = f"{a.socket}:{a.kitty_id}"
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

        live_keys = {f"{a.socket}:{a.kitty_id}" for a in agents}
        state_changed_at = {
            k: v for k, v in state_changed_at.items() if k in live_keys
        }
        prev_states = {
            k: v for k, v in prev_states.items() if k in live_keys
        }
        idle_since = {k: v for k, v in idle_since.items() if k in live_keys}
        idle_notified &= live_keys

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
        # Commit state tracking
        self.agents = r.agents
        self.prev_states = r.prev_states
        self.state_changed_at = r.state_changed_at
        self.idle_since = r.idle_since
        self.idle_notified = r.idle_notified
        self._prune_interact_histories()

        state_changed_any = any(
            (
                old_states.get(f"{a.socket}:{a.kitty_id}") is not None
                and old_states.get(f"{a.socket}:{a.kitty_id}") != a.state
            )
            for a in self.agents
        )

        # Pre-compute summaries only when an agent transitions WORKING -> IDLE
        live_keys: set[str] = set()
        for a in self.agents:
            key = f"{a.socket}:{a.kitty_id}"
            live_keys.add(key)
            old_state = old_states.get(key)
            just_became_idle = (
                old_state == State.WORKING
                and a.state == State.IDLE
            )
            if just_became_idle and key not in self._action_check_pending:
                self._action_check_pending.add(key)
                self._check_action_needed(a, key)
            elif a.state == State.WORKING:
                self._action_check_pending.discard(key)
                self._action_needed.discard(key)
        self._action_check_pending &= live_keys
        self._action_needed &= live_keys

        # Collect sparkline state samples
        max_s = SETTINGS.sparkline.max_samples
        live_names: set[str] = set()
        for a in self.agents:
            akey = f"{a.socket}:{a.kitty_id}"
            live_names.add(a.name)
            waiting = a.state == State.IDLE and akey in self._action_needed
            state_label = "WAITING" if waiting else a.state.value.upper()
            samples = self._sparkline_samples.setdefault(a.name, [])
            samples.append(state_label)
            if len(samples) > max_s:
                del samples[: len(samples) - max_s]
        for k in list(self._sparkline_samples):
            if k not in live_names:
                del self._sparkline_samples[k]

        # Refresh interact panel if the viewed agent changed state
        if self._interact_visible and self._interact_agent_key:
            ikey = self._interact_agent_key
            old_st = old_states.get(ikey)
            new_st = r.prev_states.get(ikey)
            if old_st is not None and new_st is not None \
                    and old_st != new_st:
                self._refresh_interact_panel()

        # Update Claude usage bars
        if r.usage.available:
            sess_bar = self.query_one("#usage-session", UsageBar)
            sess_bar.pct = r.usage.session_pct
            sess_left: str = time_left(r.usage.session_resets_at)
            sess_bar.extra_text = f"({sess_left})" if sess_left else ""

            week_bar = self.query_one("#usage-week", UsageBar)
            week_bar.pct = r.usage.week_pct

            extra_bar = self.query_one("#usage-extra", UsageBar)
            extra_bar.pct = r.usage.extra_pct
            if r.usage.extra_limit > 0:
                extra_bar.extra_text = (
                    f"${r.usage.extra_used / 100:.2f}"
                    f"/${r.usage.extra_limit / 100:.2f}"
                )

        # Update OpenAI usage bars
        o_sess = self.query_one("#openai-session", UsageBar)
        o_week = self.query_one("#openai-week", UsageBar)
        if r.openai.available:
            o_sess.pct = r.openai.requests_pct
            left: str = time_left(r.openai.requests_resets_at)
            o_sess.extra_text = f"({left})" if left else ""
            o_week.pct = r.openai.tokens_pct
            o_week.extra_text = ""
        else:
            o_sess.pct = 0
            o_sess.extra_text = "(unavailable)"
            o_week.pct = 0
            o_week.extra_text = ""

        # Update table
        table = self.query_one("#agent-table", DataTable)
        _saved_key: str | None = self._get_selected_row_key()
        table.clear()

        if not self.agents:
            status = self.query_one("#status-line", Static)
            status.update(
                "  No tracked agents — press [bold]n[/] to create one, "
                "or open a terminal with $mod+Return and type a name"
            )
            return

        # Separate top-level agents from sub-agents
        parent_names: set[str] = {a.name for a in self.agents}
        top_level: list[AgentWindow] = [
            a for a in self.agents
            if not a.parent_name or a.parent_name not in parent_names
        ]
        children_of: dict[str, list[AgentWindow]] = {}
        for a in self.agents:
            if a.parent_name and a.parent_name in parent_names:
                children_of.setdefault(a.parent_name, []).append(a)

        def _priority_sort_key(
            a: AgentWindow,
        ) -> tuple[int, int, float, str]:
            # Priority first (1=high … 3=low)
            p = self._get_priority(a.name)
            # State: WAITING (0) → WORKING (1) → IDLE (2)
            akey: str = f"{a.socket}:{a.kitty_id}"
            if a.state == State.IDLE and akey in self._action_needed:
                st = 0  # WAITING
            elif a.state == State.WORKING:
                st = 1
            else:
                st = 2  # IDLE
            changed_at: float = self.state_changed_at.get(akey, time.time())
            return (p, st, changed_at, a.name.lower())

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

        def _fmt_duration(seconds: float) -> str:
            s = int(seconds)
            if s < 60:
                return f"{s}s"
            if s < 3600:
                return f"{s // 60}m"
            if s < 86400:
                return f"{s // 3600}h{(s % 3600) // 60}m"
            return f"{s // 86400}d{(s % 86400) // 3600}h"

        from .widgets import _gradient_color

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

        state_col_width = (
            self._COL_WIDTHS_SPLIT if self._split_mode else self._COL_WIDTHS
        ).get("State", 10)

        def _add_agent_row(a: AgentWindow, indent: str = "") -> None:
            akey: str = f"{a.socket}:{a.kitty_id}"
            waiting: bool = (
                a.state == State.IDLE and akey in self._action_needed
            )

            if waiting:
                icon = "⏸"
                state_label = "WAITING"
                state_color = "#d7af00"
                row_bg = ""
            elif a.state == State.WORKING:
                icon = "▶"
                state_label = "WORKING"
                state_color = "#00d700"
                row_bg = ""
            else:
                icon = "⏹"
                state_label = "IDLE"
                state_color = "#ff3333"
                row_bg = ""

            raw_name: str = f"{indent}🧬 {a.name}" if indent else a.name
            name_text = Text(raw_name, style=row_bg) if row_bg else raw_name
            state_cell = f"{icon} {state_label}".ljust(state_col_width)
            state_text = Text(
                state_cell,
                style=f"bold {state_color} on #000000",
            )
            elapsed: float = time.time() - self.state_changed_at.get(
                akey, time.time()
            )
            elapsed_text: str | Text = _fmt_duration(elapsed)
            ctx_cell: str | Text = _ctx_gauge(a.ctx_pct) if a.ctx_pct else "—"
            tok_cell: str | Text = (
                f"↑{a.tokens_in} ↓{a.tokens_out}" if a.tokens_in else "—"
            )

            pm = a.proc_metrics
            cpu_cell: str | Text = Text(
                f"{pm.cpu_pct:.0f}%",
                style=_gradient_color(pm.cpu_pct),
            )
            ram_cell: str | Text = f"{pm.ram_mb:.0f}M"
            gpu_str: str = f"{pm.gpu_pct:.0f}%"
            if pm.gpu_mem_mb > 0:
                gpu_str += f" {pm.gpu_mem_mb:.0f}M"
            gpu_cell: str | Text = Text(
                gpu_str, style=_gradient_color(pm.gpu_pct),
            )
            net_cell: str | Text = (
                f"↓{fmt_bytes(pm.io_read_bps)} "
                f"↑{fmt_bytes(pm.io_write_bps)}"
            )

            if row_bg:
                elapsed_text = Text(str(elapsed_text), style=row_bg)
                ctx_cell = Text(str(ctx_cell), style=row_bg)
                cpu_cell = Text(str(cpu_cell), style=row_bg)
                ram_cell = Text(str(ram_cell), style=row_bg)
                gpu_cell = Text(str(gpu_cell), style=row_bg)
                net_cell = Text(str(net_cell), style=row_bg)
                tok_cell = Text(str(tok_cell), style=row_bg)

            pri_val = self._get_priority(a.name)
            _pri_colors = {1: "#ffffff", 2: "#999999", 3: "#555555"}
            pri_cell: str | Text = Text(
                str(pri_val), style=f"bold {_pri_colors[pri_val]}",
            )

            row_key: str = akey
            cells: dict[str, str | Text] = {
                "State": state_text,
                "P": pri_cell,
                "◉": ctx_cell,
                "Name": name_text,
                "Elapsed": elapsed_text,
                "Model/Cmd": Text(a.model or "—", style=row_bg) if row_bg else (a.model or "—"),
                "CPU": cpu_cell,
                "RAM": ram_cell,
                "GPU": gpu_cell,
                "Net": net_cell,
                "WS": Text(a.workspace or "?", style=row_bg) if row_bg else (a.workspace or "?"),
                "CWD": Text(a.cwd, style=row_bg) if row_bg else a.cwd,
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

        def _add_tmux_rows(a: AgentWindow) -> None:
            for sess in a.tmux_sessions:
                age_s: int = (
                    int(time.time()) - sess.created if sess.created else 0
                )
                if age_s >= 3600:
                    age_str = f"{age_s // 3600}h{(age_s % 3600) // 60}m"
                elif age_s >= 60:
                    age_str = f"{age_s // 60}m"
                else:
                    age_str = f"{age_s}s"
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
                    cpu_t = Text(
                        f"{pm.cpu_pct:.0f}%",
                        style=_gradient_color(pm.cpu_pct),
                    )
                    ram_t = f"{pm.ram_mb:.0f}M"
                    gpu_str: str = f"{pm.gpu_pct:.0f}%"
                    if pm.gpu_mem_mb > 0:
                        gpu_str += f" {pm.gpu_mem_mb:.0f}M"
                    gpu_t = Text(
                        gpu_str, style=_gradient_color(pm.gpu_pct),
                    )
                    net_str: str = (
                        f"↓{fmt_bytes(pm.io_read_bps)} "
                        f"↑{fmt_bytes(pm.io_write_bps)}"
                    )
                    net_t = net_str
                if sess.attached:
                    tmux_name = f"  └ 🔍 {sess.name}"
                    tmux_cmd = cleaned_cmd
                    tmux_age = f"⏱ {age_str} ●"
                else:
                    dim: str = "#555555"
                    tmux_name = Text(f"  └ 🔍 {sess.name}", style=dim)
                    tmux_cmd = Text(cleaned_cmd, style=dim)
                    tmux_age = Text(f"⏱ {age_str}", style=dim)
                    for v in (cpu_t, ram_t, gpu_t, net_t):
                        if isinstance(v, Text):
                            v.stylize(dim)
                tmux_key: str = f"tmux:{sess.name}"
                state_placeholder = Text(" " * state_col_width, style="on #000000")
                tcells: dict[str, str | Text] = {
                    "State": state_placeholder,
                    "P": "",
                    "◉": "",
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

        for a in top_level:
            _add_agent_row(a)
            for child in children_of.get(a.name, []):
                _add_agent_row(child, indent="  └ ")
                _add_tmux_rows(child)
            _add_tmux_rows(a)

        # Restore selected row
        if _saved_key:
            for idx, row_key in enumerate(table.rows):
                if row_key.value == _saved_key:
                    table.move_cursor(row=idx)
                    break

        self._update_mini_map()
        self._update_sparkline()

        n_working: int = sum(
            1 for a in self.agents if a.state == State.WORKING
        )
        n_idle: int = sum(
            1 for a in self.agents if a.state == State.IDLE
        )
        status = self.query_one("#status-line", Static)
        sort_label: str = self.sort_mode.value
        status.update(
            f"  {len(self.agents)} agents  │  "
            f"[bold #00d7d7]{n_working} working[/]  "
            f"[bold #d7af00]{n_idle} idle[/]  │  "
            f"Sort: [bold]{sort_label}[/]  │  "
            f"Layout: [bold]{'SPLIT' if self._split_mode else 'WIDE'}[/]  │  "
            f"Poll: {SETTINGS.poll_interval}s"
        )

        if state_changed_any:
            self._pulse_agent_table()


    # ── Mini-map ──────────────────────────────────────────────────────

    def _update_mini_map(self) -> None:
        """Render the agent fleet mini-map strip."""
        mini = self.query_one("#mini-map", Static)
        if not self.agents:
            mini.add_class("hidden")
            return
        mini.remove_class("hidden")

        _state_pri_colors: dict[str, tuple[str, str, str]] = {
            #              P1          P2          P3
            "WORKING": ("#00ff00", "#006600", "#003300"),
            "WAITING": ("#ffdd00", "#776600", "#333300"),
            "IDLE":    ("#ff4444", "#771111", "#330a0a"),
        }


        parent_names: set[str] = {a.name for a in self.agents}
        top_level: list[AgentWindow] = sorted(
            (a for a in self.agents
             if not a.parent_name or a.parent_name not in parent_names),
            key=lambda a: self._get_priority(a.name),
        )
        children_of: dict[str, list[AgentWindow]] = {}
        for a in self.agents:
            if a.parent_name and a.parent_name in parent_names:
                children_of.setdefault(a.parent_name, []).append(a)
        for kids in children_of.values():
            kids.sort(key=lambda a: self._get_priority(a.name))

        def _agent_color(a: AgentWindow) -> str:
            akey = f"{a.socket}:{a.kitty_id}"
            waiting = a.state == State.IDLE and akey in self._action_needed
            state_label = "WAITING" if waiting else a.state.value.upper()
            pri = self._get_priority(a.name)
            colors = _state_pri_colors.get(
                state_label, ("#555555", "#333333", "#222222"),
            )
            return colors[pri - 1]

        def _agent_state(a: AgentWindow) -> str:
            akey = f"{a.socket}:{a.kitty_id}"
            waiting = a.state == State.IDLE and akey in self._action_needed
            return "WAITING" if waiting else a.state.value.upper()



        # Build groups: list of (parent, [children])
        groups: list[tuple[AgentWindow, list[AgentWindow]]] = []
        for a in top_level:
            groups.append((a, children_of.get(a.name, [])))

        # Render as box cards: top bar + content row per group
        self._minimap_agents = []
        cards_top: list[str] = []
        cards_bot: list[str] = []
        for parent, kids in groups:
            pc = _agent_color(parent)
            pri = self._get_priority(parent.name)
            style = f"bold {pc}" if pri == 1 else pc
            name = _compact_name(parent.name, SETTINGS.minimap.max_name_length)
            pidx = len(self._minimap_agents)
            self._minimap_agents.append(parent.name)

            # Sub-agents inline
            subs: list[str] = []
            for child in kids:
                cc = _agent_color(child)
                cpri = self._get_priority(child.name)
                cs = f"bold {cc}" if cpri == 1 else cc
                cn = _compact_name(child.name, SETTINGS.minimap.max_sub_name_length)
                cidx = len(self._minimap_agents)
                self._minimap_agents.append(child.name)
                subs.append(
                    f"[#333333]┊[/] [@click=app.select_minimap({cidx})][{cs}]{cn}[/][/]"
                )

            # Card width: calculate visible content width
            sub_text = " ".join(subs)
            inner = f"[@click=app.select_minimap({pidx})][{style}]{name}[/][/]"
            if subs:
                inner += f" {sub_text}"

            # Top bar: colored ▄ blocks
            bar_len = len(name) + 1
            for child in kids:
                bar_len += len(_compact_name(child.name, SETTINGS.minimap.max_sub_name_length)) + 3
            bar_len = max(bar_len, 8)

            cards_top.append(f"[{pc}]{'▄' * bar_len}[/]")
            cards_bot.append(f" {inner}")

        # Join cards with spacing
        sep_top = "  "
        sep_bot = "  "
        line1 = sep_top.join(cards_top)
        line2 = sep_bot.join(cards_bot)

        mini.update(f"{line1}\n{line2}")

    def _update_sparkline(self) -> None:
        """Render state sparkline charts for all agents."""
        from .widgets import state_sparkline_markup, _gradient_color
        widget = self.query_one("#sparkline-chart", Static)
        if not self.agents or not self._sparkline_samples:
            widget.add_class("hidden")
            return
        widget.remove_class("hidden")

        parent_names: set[str] = {a.name for a in self.agents}
        ordered = sorted(
            self.agents,
            key=lambda a: (
                self._get_priority(a.name),
                0 if (not a.parent_name or a.parent_name not in parent_names) else 1,
                a.name,
            ),
        )

        # Aggregate efficiency header (weighted by priority)
        _pri_weight = {1: 5, 2: 3, 3: 1}
        w_working = 0.0
        w_waiting = 0.0
        w_total = 0.0
        raw_working = 0
        raw_waiting = 0
        raw_total = 0
        for agent in self.agents:
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

            # Celebration triggers (require ≥10 min of data)
            min_samples = int(600 / SETTINGS.poll_interval)  # 10 min
            enough_data = raw_total >= min_samples
            if enough_data:
                if eff_pct >= 80 and self._steady_armed:
                    self._steady_armed = False
                    self._show_steady_lad(eff_pct)
                elif eff_pct < 80:
                    self._steady_armed = True

                if eff_pct >= 60 and self._dopamine_armed:
                    self._dopamine_armed = False
                    self._show_dopamine_hit(eff_pct)
                elif eff_pct < 60:
                    self._dopamine_armed = True

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

    def _show_steady_lad(self, efficiency: float) -> None:
        """Mount the steady lad celebration overlay."""
        from .widgets import SteadyLadOverlay
        if self.query("#steady-lad") or self.query("#dopamine"):
            return
        self.mount(SteadyLadOverlay(efficiency, id="steady-lad"))

    def _show_dopamine_hit(self, efficiency: float) -> None:
        """Mount the dopamine celebration overlay."""
        from .widgets import DopamineOverlay
        # Don't stack multiple
        if self.query("#dopamine") or self.query("#steady-lad"):
            return
        self.mount(DopamineOverlay(efficiency, id="dopamine"))

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
            if f"{a.socket}:{a.kitty_id}" == key_val:
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

    # ── Actions ───────────────────────────────────────────────────────

    def _send_stop_to_selected_agent(self) -> None:
        """Send ESC to the currently selected agent row."""
        if len(self.screen_stack) > 1:
            return
        agent = self._get_selected_agent()
        if not agent:
            return
        kitty_cmd(
            agent.socket, "send-text", "--match",
            f"id:{agent.kitty_id}", "\x1b",
        )
        self.notify(f"ESC → {agent.name}", timeout=2)

    def action_stop_agent(self) -> None:
        """Send ESC to selected agent (table-focused safety behavior)."""
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        self._send_stop_to_selected_agent()

    def action_force_stop_agent(self) -> None:
        """Send ESC to selected agent from any focused widget."""
        self._send_stop_to_selected_agent()

    def on_app_focus(self, event: events.AppFocus) -> None:
        """When terminal window gains focus, focus the agent table."""
        del event
        self.query_one("#agent-table", DataTable).focus()

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
        if agent:
            focus_window(agent)

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

    def _refresh_interact_panel(self) -> None:
        """Refresh the interact panel for the currently selected item."""
        old_agent_key = self._interact_agent_key
        old_tmux_name = self._interact_tmux_name

        tmux = self._get_selected_tmux()
        if tmux:
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
            return
        key = f"{agent.socket}:{agent.kitty_id}"
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
                return f"agent:{agent.name}"
        if self._interact_tmux_name:
            for agent in self.agents:
                if any(s.name == self._interact_tmux_name for s in agent.tmux_sessions):
                    return f"agent:{agent.name}"
        return None

    def _reset_history_nav(self) -> None:
        self._history_nav_target = None
        self._history_nav_index = None

    def _set_interact_input_text(self, text: str) -> None:
        ta = self.query_one("#interact-input", ZeusTextArea)
        if text:
            ta.load_text(text)
        else:
            ta.clear()
        self._resize_interact_input(ta)

    def _handle_interact_history_nav(self, key: str) -> bool:
        """Handle Up/Down history traversal for interact input."""
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

        if key == "up":
            if self._history_nav_index is None:
                if ta.text.strip():
                    return False
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
            if down_idx < len(entries) - 1:
                next_idx = down_idx + 1
                self._history_nav_index = next_idx
                self._set_interact_input_text(entries[next_idx])
            else:
                self._history_nav_index = None
                self._set_interact_input_text("")
            return True

        return False

    def _append_interact_history(self, text: str) -> None:
        target = self._history_target_key()
        if not target:
            return
        append_history(target, text)

    def _prune_interact_histories(self) -> None:
        """Delete history files for agent names that are no longer present."""
        live_targets: set[str] = {f"agent:{a.name}" for a in self.agents}
        prune_histories(live_targets)

    # ── Agent priorities ────────────────────────────────────────────

    def _load_priorities(self) -> None:
        """Load priorities from disk."""
        try:
            import json
            data = json.loads(PRIORITIES_FILE.read_text())
            if isinstance(data, dict):
                self._agent_priorities = {
                    k: v for k, v in data.items()
                    if isinstance(k, str) and isinstance(v, int) and 1 <= v <= 3
                }
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_priorities(self) -> None:
        """Persist priorities to disk."""
        import json
        PRIORITIES_FILE.write_text(json.dumps(self._agent_priorities))

    def _get_priority(self, agent_name: str) -> int:
        """Return priority for an agent (1=high, 2=med, 3=low default)."""
        return self._agent_priorities.get(agent_name, 3)

    def action_cycle_priority(self) -> None:
        """Cycle priority 3→1→2→3 for the selected agent."""
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        if len(self.screen_stack) > 1:
            return
        agent = self._get_selected_agent()
        if not agent:
            return
        cur = self._get_priority(agent.name)
        # 3→1→2→3
        nxt = {3: 2, 2: 1, 1: 3}[cur]
        if nxt == 3:
            self._agent_priorities.pop(agent.name, None)
        else:
            self._agent_priorities[agent.name] = nxt
        self._save_priorities()
        self.poll_and_update()

    # ── Event handlers ────────────────────────────────────────────────

    def _dismiss_splash(self) -> bool:
        """Dismiss splash if present. Returns True if dismissed."""
        for splash in self.query(SplashOverlay):
            splash.dismiss()
            return True
        return False

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
            # Focus the interact input
            if self._interact_visible:
                self.query_one("#interact-input", ZeusTextArea).focus()
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
        if agent:
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
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        if len(self.screen_stack) > 1:
            return
        agent = self._get_selected_agent()
        if agent:
            self.push_screen(ConfirmKillScreen(agent))
            return
        tmux = self._get_selected_tmux()
        if tmux:
            self.push_screen(ConfirmKillTmuxScreen(tmux))

    def do_kill_agent(self, agent: AgentWindow) -> None:
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

    # ── New / Sub-agent / Rename ──────────────────────────────────────

    def action_new_agent(self) -> None:
        self.push_screen(NewAgentScreen())

    def action_spawn_subagent(self) -> None:
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        if len(self.screen_stack) > 1:
            return
        agent = self._get_selected_agent()
        if not agent:
            self.notify("No agent selected", timeout=2)
            return
        session: str | None = find_current_session(agent.cwd)
        if not session:
            self.notify(
                f"No session found for {agent.name}", timeout=3
            )
            return
        self.push_screen(SubAgentScreen(agent))

    def do_spawn_subagent(self, agent: AgentWindow, name: str) -> None:
        result: str | None = spawn_subagent(
            agent, name, workspace=agent.workspace
        )
        if result:
            self.notify(f"🧬 Spawned: {name}", timeout=3)
            self.set_timer(1.5, self.poll_and_update)
        else:
            self.notify(
                f"Failed to fork session for {agent.name}", timeout=3
            )

    def action_rename(self) -> None:
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        if len(self.screen_stack) > 1:
            return
        agent = self._get_selected_agent()
        if agent:
            self.push_screen(RenameScreen(agent))
            return
        tmux = self._get_selected_tmux()
        if tmux:
            self.push_screen(RenameTmuxScreen(tmux))

    def do_rename_agent(self, agent: AgentWindow, new_name: str) -> None:
        overrides: dict[str, str] = load_names()
        key: str = f"{agent.socket}:{agent.kitty_id}"
        overrides[key] = new_name
        save_names(overrides)
        self.notify(f"Renamed: {agent.name} → {new_name}", timeout=3)
        self.poll_and_update()

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
        if len(self.screen_stack) > 1:
            return
        self.push_screen(HelpScreen())

    def action_toggle_table(self) -> None:
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        table = self.query_one("#agent-table", ZeusDataTable)
        if table.has_class("hidden"):
            table.remove_class("hidden")
        else:
            table.add_class("hidden")

    def action_toggle_minimap(self) -> None:
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        mini = self.query_one("#mini-map", Static)
        if mini.has_class("hidden"):
            mini.remove_class("hidden")
        else:
            mini.add_class("hidden")

    def action_toggle_sparklines(self) -> None:
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        spark = self.query_one("#sparkline-chart", Static)
        if spark.has_class("hidden"):
            spark.remove_class("hidden")
        else:
            spark.add_class("hidden")

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
        if isinstance(self.focused, (Input, TextArea, ZeusTextArea)):
            return
        if len(self.screen_stack) > 1:
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
            if self._interact_visible:
                self.query_one("#interact-input", ZeusTextArea).focus()

    def action_toggle_interact_panel(self) -> None:
        """F8: toggle interact panel visibility."""
        panel = self.query_one("#interact-panel", Vertical)
        if self._interact_visible:
            self._interact_visible = False
            self._interact_agent_key = None
            self._interact_tmux_name = None
            self._reset_history_nav()
            panel.remove_class("visible")
            self.query_one("#agent-table", DataTable).focus()
        else:
            self._interact_visible = True
            panel.add_class("visible")
            self._refresh_interact_panel()

    # ── Action-needed detection ─────────────────────────────────────

    _ACTION_PROMPT = (
        "You are a triage classifier. An AI coding agent is IDLE. "
        "Does it need human input to continue? Look at the terminal "
        "output below and reply with a SINGLE word: YES or NO.\n\n"
        "Terminal output:\n"
    )

    def _get_screen_context(self, agent: AgentWindow) -> str:
        text = get_screen_text(agent)
        lines = text.splitlines()
        recent = [l for l in lines if l.strip()][-30:]
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
        if not agent or agent.state != State.IDLE:
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
        stream.write(Text.from_ansi(raw))

    @work(thread=True, exclusive=True, group="interact_stream")
    def _fetch_interact_stream(self, agent: AgentWindow) -> None:
        """Fetch screen text with ANSI formatting in background thread."""
        screen_text = get_screen_text(agent, ansi=True)
        agent_key = f"{agent.socket}:{agent.kitty_id}"
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
        stream.write(Text.from_ansi(raw))

    def _send_text_to_agent(self, agent: AgentWindow, text: str) -> None:
        """Send text to the agent's kitty window followed by Enter."""
        clean = text.replace("\x00", "")
        kitty_cmd(
            agent.socket, "send-text", "--match",
            f"id:{agent.kitty_id}", clean + "\r",
        )

    def action_send_interact(self) -> None:
        """Send text from interact input to the agent/tmux (Ctrl+s)."""
        if not self._interact_visible:
            return
        ta = self.query_one("#interact-input", ZeusTextArea)
        text = ta.text.strip()
        if not text:
            return
        self._append_interact_history(text)
        if self._interact_tmux_name:
            try:
                subprocess.run(
                    ["tmux", "send-keys", "-t", self._interact_tmux_name,
                     text, "Enter"],
                    capture_output=True, timeout=3,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            ta.clear()
            ta.styles.height = 3
            self._reset_history_nav()
            return

        agent = self._get_agent_by_key(self._interact_agent_key)
        if not agent:
            self.notify("Agent no longer available", timeout=2)
            return
        self._send_text_to_agent(agent, text)
        ta.clear()
        ta.styles.height = 3
        self._reset_history_nav()

    def action_queue_interact(self) -> None:
        """Send text + Alt+Enter (queue in pi) to agent/tmux."""
        if not self._interact_visible:
            return
        ta = self.query_one("#interact-input", ZeusTextArea)
        text = ta.text.strip()
        if not text:
            return
        self._append_interact_history(text)
        if self._interact_tmux_name:
            try:
                subprocess.run(
                    ["tmux", "send-keys", "-t", self._interact_tmux_name,
                     text, "M-Enter"],
                    capture_output=True, timeout=3,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            ta.clear()
            ta.styles.height = 3
            self._reset_history_nav()
            return

        agent = self._get_agent_by_key(self._interact_agent_key)
        if not agent:
            self.notify("Agent no longer available", timeout=2)
            return
        # Send text, Alt+Enter to queue, then Ctrl+U to clear pi's input
        kitty_cmd(
            agent.socket, "send-text", "--match",
            f"id:{agent.kitty_id}", text + "\x1b[13;3u\x15",
        )
        ta.clear()
        ta.styles.height = 3
        self._reset_history_nav()

    def action_refresh(self) -> None:
        self.poll_and_update()


def cmd_dashboard(args: argparse.Namespace | None = None) -> None:
    app = ZeusApp()
    app.run()
