"""Tests for kitty window detection heuristics and name uniqueness."""

import json
import subprocess

import zeus.kitty as kitty
from zeus.kitty import (
    _iter_cmdline_tokens,
    _looks_like_pi_window,
    ensure_unique_agent_names,
)
from zeus.models import AgentWindow


def test_iter_cmdline_tokens_splits_shell_payload():
    cmdline = ["bash", "-lc", "pi --session abc"]
    assert _iter_cmdline_tokens(cmdline) == ["bash", "-lc", "pi", "--session", "abc"]


def test_looks_like_pi_window_exact_token():
    win = {"cmdline": ["pi", "--print"], "title": "shell"}
    assert _looks_like_pi_window(win) is True


def test_looks_like_pi_window_path_token():
    win = {"cmdline": ["/home/user/.local/bin/pi", "--print"], "title": "shell"}
    assert _looks_like_pi_window(win) is True


def test_looks_like_pi_window_shell_command_payload():
    win = {"cmdline": ["bash", "-lc", "exec pi --session x"], "title": "shell"}
    assert _looks_like_pi_window(win) is True


def test_looks_like_pi_window_does_not_match_pip():
    win = {"cmdline": ["python", "-m", "pip", "install", "textual"], "title": "shell"}
    assert _looks_like_pi_window(win) is False


def test_looks_like_pi_window_title_pi_symbol():
    win = {"cmdline": ["bash"], "title": "π my-agent"}
    assert _looks_like_pi_window(win) is True


def _agent(session_path: str = "", agent_id: str = "parent-1") -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="agent",
        pid=100,
        kitty_pid=99,
        cwd="/tmp/project",
        agent_id=agent_id,
        session_path=session_path,
    )


def test_resolve_agent_session_path_prefers_runtime_sync(monkeypatch) -> None:
    agent = _agent(session_path="/tmp/explicit.jsonl")
    monkeypatch.setattr(
        kitty,
        "read_runtime_session_path",
        lambda _agent_id: "/tmp/runtime.jsonl",
    )

    assert kitty.resolve_agent_session_path(agent) == "/tmp/runtime.jsonl"


def test_resolve_agent_session_path_prefers_explicit_agent_session(monkeypatch) -> None:
    agent = _agent(session_path="/tmp/explicit.jsonl")
    monkeypatch.setattr(kitty, "read_runtime_session_path", lambda _agent_id: None)
    monkeypatch.setattr(kitty.os.path, "isfile", lambda path: path == "/tmp/explicit.jsonl")

    assert kitty.resolve_agent_session_path(agent) == "/tmp/explicit.jsonl"


def test_resolve_agent_session_path_falls_back_to_cwd_lookup(monkeypatch) -> None:
    agent = _agent(session_path="")
    monkeypatch.setattr(kitty, "read_runtime_session_path", lambda _agent_id: None)
    monkeypatch.setattr(kitty, "find_current_session", lambda cwd: "/tmp/fallback.jsonl")

    assert kitty.resolve_agent_session_path(agent) == "/tmp/fallback.jsonl"


def test_resolve_agent_session_path_with_source_marks_runtime(monkeypatch) -> None:
    agent = _agent(session_path="/tmp/explicit.jsonl")
    monkeypatch.setattr(
        kitty,
        "read_runtime_session_path",
        lambda _agent_id: "/tmp/runtime.jsonl",
    )

    assert kitty.resolve_agent_session_path_with_source(agent) == (
        "/tmp/runtime.jsonl",
        "runtime",
    )


def test_resolve_agent_session_path_with_source_falls_back_when_env_stale(monkeypatch) -> None:
    agent = _agent(session_path="/tmp/stale.jsonl")
    monkeypatch.setattr(kitty, "read_runtime_session_path", lambda _agent_id: None)
    monkeypatch.setattr(kitty.os.path, "isfile", lambda _path: False)
    monkeypatch.setattr(kitty, "find_current_session", lambda _cwd: "/tmp/fallback.jsonl")

    assert kitty.resolve_agent_session_path_with_source(agent) == (
        "/tmp/fallback.jsonl",
        "cwd",
    )


def test_discover_agents_uses_runtime_session_path_when_env_missing(monkeypatch) -> None:
    socket = "/tmp/kitty-4242"
    windows = [
        {
            "tabs": [
                {
                    "windows": [
                        {
                            "id": 1,
                            "pid": 123,
                            "cwd": "/tmp/project",
                            "env": {
                                "ZEUS_AGENT_NAME": "alpha",
                                "ZEUS_AGENT_ID": "agent-1",
                                "ZEUS_ROLE": "hippeus",
                            },
                            "cmdline": ["bash", "-lc", "pi"],
                        }
                    ]
                }
            ]
        }
    ]

    monkeypatch.setattr(kitty, "discover_sockets", lambda: [socket])
    monkeypatch.setattr(
        kitty,
        "kitty_cmd",
        lambda _socket, *_args, **_kwargs: json.dumps(windows),
    )
    monkeypatch.setattr(kitty, "load_agent_ids", lambda: {})
    monkeypatch.setattr(kitty, "save_agent_ids", lambda _ids: None)
    monkeypatch.setattr(kitty, "load_names", lambda: {})
    monkeypatch.setattr(
        kitty,
        "read_runtime_session_path",
        lambda agent_id: "/tmp/runtime.jsonl" if agent_id == "agent-1" else None,
    )

    agents = kitty.discover_agents()

    assert len(agents) == 1
    assert agents[0].name == "alpha"
    assert agents[0].session_path == "/tmp/runtime.jsonl"


def test_spawn_subagent_uses_explicit_parent_session_path(monkeypatch, tmp_path) -> None:
    source = tmp_path / "parent.jsonl"
    source.write_text('{"type":"session"}\n')

    agent = _agent(session_path=str(source))

    captured: dict[str, str] = {}

    def fake_fork_session(src: str, target_cwd: str) -> str | None:
        captured["src"] = src
        child = tmp_path / "child.jsonl"
        child.write_text('{"type":"session"}\n')
        return str(child)

    popen_calls: list[list[str]] = []
    popen_env: dict[str, str] = {}

    class DummyProc:
        pid = 123

    def fake_popen(cmd: list[str], **kwargs):
        popen_calls.append(cmd)
        popen_env.update(kwargs.get("env", {}))
        return DummyProc()

    monkeypatch.setattr(kitty, "fork_session", fake_fork_session)
    monkeypatch.setattr(kitty.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(kitty, "generate_agent_id", lambda: "agent-id")
    monkeypatch.setattr(kitty, "read_runtime_session_path", lambda _agent_id: None)

    result = kitty.spawn_subagent(agent, "child", workspace="")

    assert result is not None
    assert captured["src"] == str(source)
    assert popen_calls
    assert "--session" in popen_calls[0][-1]
    assert popen_env["ZEUS_AGENT_NAME"] == "child"
    assert popen_env["ZEUS_PARENT_ID"] == "parent-1"
    assert popen_env["ZEUS_AGENT_ID"] == "agent-id"
    assert popen_env["ZEUS_ROLE"] == "hippeus"


def test_spawn_subagent_requires_parent_agent_id(monkeypatch, tmp_path) -> None:
    source = tmp_path / "parent.jsonl"
    source.write_text('{"type":"session"}\n')

    agent = _agent(session_path=str(source), agent_id="")

    monkeypatch.setattr(kitty, "fork_session", lambda _src, _cwd: str(tmp_path / "child.jsonl"))
    monkeypatch.setattr(kitty.subprocess, "Popen", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kitty, "read_runtime_session_path", lambda _agent_id: None)

    result = kitty.spawn_subagent(agent, "child", workspace="")

    assert result is None


# ---------------------------------------------------------------------------
# ensure_unique_agent_names
# ---------------------------------------------------------------------------

def _make_agent(name: str, agent_id: str = "") -> AgentWindow:
    return AgentWindow(
        kitty_id=0, socket="", name=name, pid=0, kitty_pid=0,
        cwd="", agent_id=agent_id,
    )


def test_ensure_unique_names_no_duplicates():
    agents = [_make_agent("a", "id-a"), _make_agent("b", "id-b")]
    ensure_unique_agent_names(agents)
    assert [a.name for a in agents] == ["a", "b"]


def test_ensure_unique_names_two_duplicates():
    agents = [_make_agent("pi-1", "id-a"), _make_agent("pi-1", "id-b")]
    ensure_unique_agent_names(agents)
    names = sorted(a.name for a in agents)
    assert len(set(names)) == 2
    assert "pi-1" in names
    assert "pi-1-2" in names


def test_ensure_unique_names_three_duplicates():
    agents = [
        _make_agent("x", "id-1"),
        _make_agent("x", "id-2"),
        _make_agent("x", "id-3"),
    ]
    ensure_unique_agent_names(agents)
    names = [a.name for a in agents]
    assert len(set(names)) == 3, f"expected 3 unique names, got {names}"


def test_ensure_unique_names_stable_across_calls():
    """Same input produces same disambiguation every time."""
    agents_a = [_make_agent("pi-1", "id-b"), _make_agent("pi-1", "id-a")]
    agents_b = [_make_agent("pi-1", "id-a"), _make_agent("pi-1", "id-b")]
    ensure_unique_agent_names(agents_a)
    ensure_unique_agent_names(agents_b)
    # Both should assign the same agent_id the same final name
    mapping_a = {a.agent_id: a.name for a in agents_a}
    mapping_b = {a.agent_id: a.name for a in agents_b}
    assert mapping_a == mapping_b


def test_ensure_unique_names_suffix_avoids_existing():
    """If pi-1-2 already exists, skip to pi-1-3."""
    agents = [
        _make_agent("pi-1", "id-a"),
        _make_agent("pi-1-2", "id-b"),
        _make_agent("pi-1", "id-c"),
    ]
    ensure_unique_agent_names(agents)
    names = sorted(a.name for a in agents)
    assert len(set(names)) == 3, f"expected 3 unique names, got {names}"
    assert "pi-1" in names
    assert "pi-1-2" in names
    assert "pi-1-3" in names


def test_ensure_unique_names_case_insensitive():
    agents = [_make_agent("Worker", "id-a"), _make_agent("worker", "id-b")]
    ensure_unique_agent_names(agents)
    names_lower = [a.name.casefold() for a in agents]
    assert len(set(names_lower)) == 2


# ---------------------------------------------------------------------------
# discover_agents auto-naming uniqueness
# ---------------------------------------------------------------------------

def _make_kitty_windows(
    win_id: int,
    *,
    agent_name: str = "",
    agent_id: str = "",
) -> list[dict]:
    """Build minimal kitty `ls` output for one pi window."""
    env: dict[str, str] = {}
    if agent_name:
        env["ZEUS_AGENT_NAME"] = agent_name
    if agent_id:
        env["ZEUS_AGENT_ID"] = agent_id
    return [
        {
            "tabs": [
                {
                    "windows": [
                        {
                            "id": win_id,
                            "pid": 100 + win_id,
                            "cwd": "/tmp/project",
                            "env": env,
                            "cmdline": ["bash", "-lc", "pi"],
                            "title": "π test",
                        }
                    ]
                }
            ]
        }
    ]


def test_discover_agents_unique_auto_names_across_sockets(monkeypatch) -> None:
    """Two kitty instances each with win_id=1 must NOT both get pi-1."""
    socket_a = "/tmp/kitty-1000"
    socket_b = "/tmp/kitty-2000"

    def fake_kitty_cmd(socket, *args, **kwargs):
        return json.dumps(_make_kitty_windows(1))

    monkeypatch.setattr(kitty, "discover_sockets", lambda: [socket_a, socket_b])
    monkeypatch.setattr(kitty, "kitty_cmd", fake_kitty_cmd)
    monkeypatch.setattr(kitty, "load_agent_ids", lambda: {})
    monkeypatch.setattr(kitty, "save_agent_ids", lambda _ids: None)
    monkeypatch.setattr(kitty, "load_names", lambda: {})
    monkeypatch.setattr(kitty, "read_runtime_session_path", lambda _id: None)

    agents = kitty.discover_agents()

    assert len(agents) == 2
    names = [a.name for a in agents]
    assert len(set(names)) == 2, f"expected unique names, got {names}"
    assert "pi-1" in names
    # The second one must NOT be pi-1
    other = [n for n in names if n != "pi-1"]
    assert len(other) == 1
    assert other[0].startswith("pi-")


def test_discover_agents_override_frees_auto_name(monkeypatch) -> None:
    """If socket_a:1 is overridden to 'worker', socket_b:1 can use pi-1."""
    socket_a = "/tmp/kitty-1000"
    socket_b = "/tmp/kitty-2000"

    def fake_kitty_cmd(socket, *args, **kwargs):
        return json.dumps(_make_kitty_windows(1))

    overrides = {f"{socket_a}:1": "worker"}
    monkeypatch.setattr(kitty, "discover_sockets", lambda: [socket_a, socket_b])
    monkeypatch.setattr(kitty, "kitty_cmd", fake_kitty_cmd)
    monkeypatch.setattr(kitty, "load_agent_ids", lambda: {})
    monkeypatch.setattr(kitty, "save_agent_ids", lambda _ids: None)
    monkeypatch.setattr(kitty, "load_names", lambda: overrides)
    monkeypatch.setattr(kitty, "read_runtime_session_path", lambda _id: None)

    agents = kitty.discover_agents()

    assert len(agents) == 2
    names = sorted(a.name for a in agents)
    assert "worker" in names
    assert "pi-1" in names


def test_discover_agents_auto_name_skips_override_value(monkeypatch) -> None:
    """Auto-naming must not collide with an override destination name."""
    socket_a = "/tmp/kitty-1000"
    socket_b = "/tmp/kitty-2000"

    def fake_kitty_cmd(socket, *args, **kwargs):
        # Both have win_id=2 to force collision scenario
        return json.dumps(_make_kitty_windows(2))

    # Some other agent is overridden to "pi-2"
    overrides = {f"{socket_a}:2": "pi-2"}
    monkeypatch.setattr(kitty, "discover_sockets", lambda: [socket_a, socket_b])
    monkeypatch.setattr(kitty, "kitty_cmd", fake_kitty_cmd)
    monkeypatch.setattr(kitty, "load_agent_ids", lambda: {})
    monkeypatch.setattr(kitty, "save_agent_ids", lambda _ids: None)
    monkeypatch.setattr(kitty, "load_names", lambda: overrides)
    monkeypatch.setattr(kitty, "read_runtime_session_path", lambda _id: None)

    agents = kitty.discover_agents()

    assert len(agents) == 2
    names = sorted(a.name for a in agents)
    assert len(set(names)) == 2, f"expected unique names, got {names}"
