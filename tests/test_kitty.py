"""Tests for kitty window detection heuristics."""

import subprocess

import zeus.kitty as kitty
from zeus.kitty import _iter_cmdline_tokens, _looks_like_pi_window
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


def test_resolve_agent_session_path_prefers_explicit_agent_session() -> None:
    agent = _agent(session_path="/tmp/explicit.jsonl")

    assert kitty.resolve_agent_session_path(agent) == "/tmp/explicit.jsonl"


def test_resolve_agent_session_path_falls_back_to_cwd_lookup(monkeypatch) -> None:
    agent = _agent(session_path="")
    monkeypatch.setattr(kitty, "find_current_session", lambda cwd: "/tmp/fallback.jsonl")

    assert kitty.resolve_agent_session_path(agent) == "/tmp/fallback.jsonl"


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

    result = kitty.spawn_subagent(agent, "child", workspace="")

    assert result is None
