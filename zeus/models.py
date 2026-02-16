"""Core data types."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class State(str, Enum):
    WORKING = "WORKING"
    IDLE = "IDLE"


@dataclass
class TmuxSession:
    name: str
    command: str
    cwd: str
    created: int = 0           # unix timestamp
    attached: bool = False
    pane_pid: int = 0          # shell PID inside the tmux pane
    owner_id: str = ""        # tmux @zeus_owner (deterministic owner)
    env_agent_id: str = ""    # ZEUS_AGENT_ID from tmux session env
    role: str = ""            # tmux @zeus_role (e.g. hoplite)
    phalanx_id: str = ""      # tmux @zeus_phalanx
    match_source: str = ""    # owner-id/env-id/cwd/screen-exact/screen-fallback
    _proc_metrics: Optional['ProcessMetrics'] = None


@dataclass
class ProcessMetrics:
    cpu_pct: float = 0.0
    ram_mb: float = 0.0
    gpu_pct: float = 0.0
    gpu_mem_mb: float = 0.0
    io_read_bps: float = 0.0
    io_write_bps: float = 0.0


@dataclass
class AgentWindow:
    kitty_id: int
    socket: str
    name: str
    pid: int
    kitty_pid: int
    cwd: str
    agent_id: str = ""
    state: State = State.IDLE
    model: str = ""
    ctx_pct: float = 0.0
    tokens_in: str = ""
    tokens_out: str = ""
    workspace: str = ""
    parent_name: str = ""
    session_path: str = ""
    tmux_sessions: list[TmuxSession] = field(default_factory=list)
    proc_metrics: ProcessMetrics = field(default_factory=ProcessMetrics)
    _screen_text: str = ""


@dataclass
class UsageData:
    session_pct: float = 0.0
    week_pct: float = 0.0
    extra_pct: float = 0.0
    extra_used: float = 0.0
    extra_limit: float = 0.0
    session_resets_at: str = ""
    week_resets_at: str = ""
    available: bool = False


@dataclass
class OpenAIUsageData:
    requests_pct: float = 0.0
    tokens_pct: float = 0.0
    requests_limit: int = 0
    requests_remaining: int = 0
    tokens_limit: int = 0
    tokens_remaining: int = 0
    requests_resets_at: str = ""
    tokens_resets_at: str = ""
    available: bool = False
