"""Zeus TUI dashboard — main App class."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from enum import Enum
import os
import subprocess
import time
import threading


class SortMode(Enum):
    STATE_ELAPSED = "state+elapsed"
    ALPHA = "alpha"

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static, Label, Input
from textual import work
from rich.text import Text

from ..config import POLL_INTERVAL
from ..models import (
    AgentWindow, TmuxSession, State, UsageData, OpenAIUsageData,
)
from ..process import _fmt_bytes, read_process_metrics
from ..kitty import (
    discover_agents, get_screen_text, focus_window, close_window,
    spawn_subagent, _load_names, _save_names,
)
from ..sessions import find_current_session
from ..sway import build_pid_workspace_map
from ..tmux import discover_tmux_sessions, match_tmux_to_agents
from ..state import detect_state, parse_footer
from ..usage import read_usage, read_openai_usage, _time_left

from .css import APP_CSS
from .widgets import ZeusDataTable, UsageBar
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
    state_changed_at: dict[int, float] = field(default_factory=dict)
    prev_states: dict[int, State] = field(default_factory=dict)
    idle_since: dict[int, float] = field(default_factory=dict)
    idle_notified: set[int] = field(default_factory=set)


class ZeusApp(App):
    TITLE = "Zeus"
    DEFAULT_CSS = APP_CSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit", show=False),
        Binding("enter", "focus_agent", "Focus Agent"),
        Binding("n", "new_agent", "New Agent"),
        Binding("s", "spawn_subagent", "Sub-Agent"),
        Binding("k", "kill_agent", "Kill Agent"),
        Binding("r", "rename", "Rename"),
        Binding("f5", "refresh", "Refresh", show=False),
        Binding("d", "toggle_expand", "Detail"),
        Binding("f4", "toggle_sort", "Sort"),
        Binding("question_mark", "show_help", "?", key_display="?"),
    ]

    agents: list[AgentWindow] = []
    sort_mode: SortMode = SortMode.STATE_ELAPSED
    _log_visible: bool = False
    prev_states: dict[int, State] = {}
    state_changed_at: dict[int, float] = {}
    idle_since: dict[int, float] = {}
    idle_notified: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Label("⚡ Zeus", id="title-text"),
            Static("", id="title-clock"),
            id="title-bar",
        )
        yield Vertical(
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
            id="top-bars",
        )
        yield Vertical(
            ZeusDataTable(
                id="agent-table",
                cursor_foreground_priority="renderable",
                cursor_background_priority="css",
            ),
            id="table-container",
        )
        yield Static("", id="log-panel")
        yield Static("", id="status-line")

    def on_mount(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(
            "Name", "State", "Elapsed", "Model/Cmd", "Ctx", "CPU",
            "RAM", "GPU", "Net", "WS", "CWD", "Tokens",
        )
        self.poll_and_update()
        self.set_interval(POLL_INTERVAL, self.poll_and_update)
        self.set_interval(1.0, self.update_clock)
        self.set_interval(1.0, self._update_log_panel)

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
            old: State | None = prev_states.get(a.kitty_id)
            if a.kitty_id not in state_changed_at:
                state_changed_at[a.kitty_id] = now
            elif old is not None and old != a.state:
                state_changed_at[a.kitty_id] = now

            if a.state == State.IDLE:
                if old == State.WORKING:
                    idle_since[a.kitty_id] = now
                    idle_notified.discard(a.kitty_id)
            else:
                idle_since.pop(a.kitty_id, None)
                idle_notified.discard(a.kitty_id)
            prev_states[a.kitty_id] = a.state

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
        # Commit state tracking
        self.agents = r.agents
        self.prev_states = r.prev_states
        self.state_changed_at = r.state_changed_at
        self.idle_since = r.idle_since
        self.idle_notified = r.idle_notified

        # Update Claude usage bars
        if r.usage.available:
            sess_bar = self.query_one("#usage-session", UsageBar)
            sess_bar.pct = r.usage.session_pct
            sess_left: str = _time_left(r.usage.session_resets_at)
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
            left: str = _time_left(r.openai.requests_resets_at)
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

        def _state_sort_key(a: AgentWindow) -> tuple[int, float, str]:
            # IDLE first, then oldest state change first, then name
            pri: int = 0 if a.state == State.IDLE else 1
            changed_at: float = self.state_changed_at.get(a.kitty_id, time.time())
            return (pri, changed_at, a.name.lower())

        def _alpha_sort_key(a: AgentWindow) -> str:
            return a.name.lower()

        sort_key = (
            _alpha_sort_key
            if self.sort_mode == SortMode.ALPHA
            else _state_sort_key
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

        def _add_agent_row(a: AgentWindow, indent: str = "") -> None:
            icon: str = {"WORKING": "▶", "IDLE": "⏹"}[a.state.value]
            state_color: str = {
                "WORKING": "#00d700", "IDLE": "#ff3333"
            }[a.state.value]
            name_text: str = f"{indent}🧬 {a.name}" if indent else a.name
            state_text = Text(
                f"{icon} {a.state.value}",
                style=f"bold {state_color}",
            )
            elapsed: float = time.time() - self.state_changed_at.get(
                a.kitty_id, time.time()
            )
            elapsed_text = Text(_fmt_duration(elapsed), style="#cccccc")
            ctx_str: str = f"{a.ctx_pct:.0f}%" if a.ctx_pct else "—"
            tok_str: str = (
                f"↑{a.tokens_in} ↓{a.tokens_out}" if a.tokens_in else "—"
            )

            pm = a.proc_metrics
            cpu_text = f"{pm.cpu_pct:.0f}%"
            ram_text = f"{pm.ram_mb:.0f}M"
            gpu_str: str = f"{pm.gpu_pct:.0f}%"
            if pm.gpu_mem_mb > 0:
                gpu_str += f" {pm.gpu_mem_mb:.0f}M"
            gpu_text = gpu_str
            net_str: str = (
                f"↓{_fmt_bytes(pm.io_read_bps)} "
                f"↑{_fmt_bytes(pm.io_write_bps)}"
            )
            net_text = net_str

            row_key: str = f"{a.socket}:{a.kitty_id}"
            table.add_row(
                name_text, state_text, elapsed_text,
                a.model or "—", ctx_str,
                cpu_text, ram_text, gpu_text, net_text,
                a.workspace or "?", a.cwd, tok_str,
                key=row_key,
            )

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
                    cpu_t = f"{pm.cpu_pct:.0f}%"
                    ram_t = f"{pm.ram_mb:.0f}M"
                    gpu_str: str = f"{pm.gpu_pct:.0f}%"
                    if pm.gpu_mem_mb > 0:
                        gpu_str += f" {pm.gpu_mem_mb:.0f}M"
                    gpu_t = gpu_str
                    net_str: str = (
                        f"↓{_fmt_bytes(pm.io_read_bps)} "
                        f"↑{_fmt_bytes(pm.io_write_bps)}"
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
                table.add_row(
                    tmux_name, tmux_age, "", tmux_cmd,
                    "", cpu_t, ram_t, gpu_t, net_t, "", sess.cwd, "",
                    key=tmux_key,
                )

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
            f"Poll: {POLL_INTERVAL}s"
        )

        self._update_log_panel()

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
        except Exception:
            return None

    def _get_selected_agent(self) -> AgentWindow | None:
        key_val: str | None = self._get_selected_row_key()
        if not key_val or key_val.startswith("tmux:"):
            return None
        for a in self.agents:
            if f"{a.socket}:{a.kitty_id}" == key_val:
                return a
        return None

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

    # ── Actions ───────────────────────────────────────────────────────

    def action_focus_agent(self) -> None:
        agent = self._get_selected_agent()
        if agent:
            focus_window(agent)

    def _focus_tmux_client(self, sess: TmuxSession) -> bool:
        """Focus the sway window running an attached tmux session."""
        try:
            r = subprocess.run(
                ["tmux", "list-clients", "-t", sess.name,
                 "-F", "#{client_pid}"],
                capture_output=True, text=True, timeout=2)
            if r.returncode != 0 or not r.stdout.strip():
                return False
            client_pid: int = int(r.stdout.strip().splitlines()[0])
            pid: int = client_pid
            for _ in range(15):
                try:
                    with open(f"/proc/{pid}/comm") as f:
                        comm: str = f.read().strip()
                    if comm == "kitty":
                        subprocess.run(
                            ["swaymsg", f"[pid={pid}]", "focus"],
                            capture_output=True, timeout=3)
                        return True
                    ppid: int | None = None
                    with open(f"/proc/{pid}/status") as f:
                        for line in f:
                            if line.startswith("PPid:"):
                                ppid = int(line.split()[1])
                                break
                    if ppid is None or ppid <= 1:
                        break
                    pid = ppid
                except (FileNotFoundError, ValueError, IndexError,
                        PermissionError):
                    break
        except (subprocess.TimeoutExpired, ValueError):
            pass
        return False

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
                def _move_and_focus() -> None:
                    time.sleep(0.5)
                    try:
                        subprocess.run(
                            ["swaymsg", f"[pid={proc.pid}]",
                             "move", "workspace", parent_ws],
                            capture_output=True, timeout=3)
                        subprocess.run(
                            ["swaymsg", "workspace", parent_ws],
                            capture_output=True, timeout=3)
                        subprocess.run(
                            ["swaymsg", f"[pid={proc.pid}]", "focus"],
                            capture_output=True, timeout=3)
                    except Exception:
                        pass
                threading.Thread(
                    target=_move_and_focus, daemon=True
                ).start()
            self.notify(f"Attached: {sess.name}", timeout=2)

    # ── Event handlers ────────────────────────────────────────────────

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        self._update_log_panel()

    def on_data_table_row_selected(
        self, event: DataTable.RowSelected
    ) -> None:
        self._activate_selected_row()

    _last_kill_time: float = 0.0

    def _activate_selected_row(self) -> None:
        if time.time() - self._last_kill_time < 1.0:
            return
        tmux = self._get_selected_tmux()
        if tmux:
            self._attach_tmux(tmux)
            return
        agent = self._get_selected_agent()
        if agent:
            focus_window(agent)
            self.notify(f"Focused: {agent.name}", timeout=2)

    _last_click_row: int | None = None
    _last_click_time: float = 0.0

    def on_click(self, event: object) -> None:
        if getattr(event, "chain", 0) < 2:
            return
        table = self.query_one("#agent-table", DataTable)
        w = getattr(event, "widget", None)
        if w is not table and table not in getattr(w, "ancestors", []):
            return
        self.set_timer(0.05, self._activate_selected_row)

    # ── Kill ──────────────────────────────────────────────────────────

    def action_kill_agent(self) -> None:
        if isinstance(self.focused, Input):
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
        try:
            kitty_pid: int | None = None
            try:
                r = subprocess.run(
                    ["tmux", "list-clients", "-t", sess.name,
                     "-F", "#{client_pid}"],
                    capture_output=True, text=True, timeout=2)
                if r.returncode == 0 and r.stdout.strip():
                    client_pid: int = int(
                        r.stdout.strip().splitlines()[0]
                    )
                    pid: int = client_pid
                    for _ in range(15):
                        try:
                            with open(f"/proc/{pid}/comm") as f:
                                comm: str = f.read().strip()
                            if comm == "kitty":
                                kitty_pid = pid
                                break
                            ppid: int | None = None
                            with open(f"/proc/{pid}/status") as f:
                                for line in f:
                                    if line.startswith("PPid:"):
                                        ppid = int(line.split()[1])
                                        break
                            if ppid is None or ppid <= 1:
                                break
                            pid = ppid
                        except (FileNotFoundError, ValueError,
                                IndexError, PermissionError):
                            break
            except Exception:
                pass

            subprocess.run(
                ["tmux", "detach-client", "-s", sess.name, "-a"],
                capture_output=True, timeout=3)
            subprocess.run(
                ["tmux", "detach-client", "-s", sess.name],
                capture_output=True, timeout=3)

            if kitty_pid:
                subprocess.run(
                    ["swaymsg", f"[pid={kitty_pid}]", "kill"],
                    capture_output=True, timeout=3)

            self.notify(f"Detached: {sess.name}", timeout=2)
        except Exception as e:
            self.notify(f"Detach failed: {e}", timeout=3)
        self.poll_and_update()

    # ── New / Sub-agent / Rename ──────────────────────────────────────

    def action_new_agent(self) -> None:
        self.push_screen(NewAgentScreen())

    def action_spawn_subagent(self) -> None:
        if isinstance(self.focused, Input):
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
        if isinstance(self.focused, Input):
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
        overrides: dict[str, str] = _load_names()
        key: str = f"{agent.socket}:{agent.kitty_id}"
        overrides[key] = new_name
        _save_names(overrides)
        self.notify(f"Renamed: {agent.name} → {new_name}", timeout=3)
        self.poll_and_update()

    def do_rename_tmux(self, sess: TmuxSession, new_name: str) -> None:
        try:
            subprocess.run(
                ["tmux", "rename-session", "-t", sess.name, new_name],
                capture_output=True, timeout=3)
            self.notify(f"Renamed: {sess.name} → {new_name}", timeout=3)
            self.poll_and_update()
        except Exception as e:
            self.notify(f"Rename failed: {e}", timeout=3)

    # ── Log panel ─────────────────────────────────────────────────────

    def action_show_help(self) -> None:
        if len(self.screen_stack) > 1:
            return
        self.push_screen(HelpScreen())

    def action_toggle_sort(self) -> None:
        if isinstance(self.focused, Input):
            return
        if len(self.screen_stack) > 1:
            return
        if self.sort_mode == SortMode.STATE_ELAPSED:
            self.sort_mode = SortMode.ALPHA
        else:
            self.sort_mode = SortMode.STATE_ELAPSED
        self.poll_and_update()

    def action_toggle_expand(self) -> None:
        if isinstance(self.focused, Input):
            return
        if len(self.screen_stack) > 1:
            return
        self._log_visible = not self._log_visible
        panel = self.query_one("#log-panel", Static)
        if self._log_visible:
            panel.add_class("visible")
            self._update_log_panel()
        else:
            panel.remove_class("visible")

    def _update_log_panel(self) -> None:
        """Update the log panel with recent output of selected item."""
        panel = self.query_one("#log-panel", Static)
        if not self._log_visible:
            return

        max_lines: int = 200

        tmux = self._get_selected_tmux()
        if tmux:
            try:
                r = subprocess.run(
                    ["tmux", "capture-pane", "-t", tmux.name,
                     "-p", "-S", f"-{max_lines}"],
                    capture_output=True, text=True, timeout=3)
                if r.returncode == 0 and r.stdout.strip():
                    lines: list[str] = r.stdout.splitlines()
                    recent: list[str] = [
                        l for l in lines if l.strip()
                    ][-max_lines:]
                    header: str = (
                        f"[bold #00d787]── tmux: {tmux.name} ──[/]"
                    )
                    content: str = "\n".join(
                        f"  {line.rstrip()}" for line in recent
                    )
                    panel.update(f"{header}\n{content}")
                    return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            panel.update(f"  [tmux: {tmux.name}] (no output)")
            return

        agent = self._get_selected_agent()
        if not agent:
            panel.update("  No agent selected")
            return
        lines = agent._screen_text.splitlines()
        recent = [l for l in lines if l.strip()][-max_lines:]
        if not recent:
            panel.update(f"  [{agent.name}] (no output)")
            return
        header = f"[bold #00d7d7]── {agent.name} ──[/]"
        content = "\n".join(f"  {line.rstrip()}" for line in recent)
        panel.update(f"{header}\n{content}")

    def action_refresh(self) -> None:
        self.poll_and_update()


def cmd_dashboard(args: argparse.Namespace | None = None) -> None:
    app = ZeusApp()
    app.run()
