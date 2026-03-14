"""Tests for wrapper-side Pi auth env recovery."""

from __future__ import annotations

import subprocess

from zeus.pi_wrapper_env import (
    PI_PROVIDER_ENV_VARS,
    fetch_provider_env_from_process_tree,
    fetch_provider_env_from_shell,
    missing_provider_env_vars,
    resolve_user_shell,
    shell_export_lines,
    shell_login_argv,
)


def test_resolve_user_shell_prefers_passwd_over_intermediary_shell(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")

    class _Pw:
        pw_shell = "/bin/zsh"

    monkeypatch.setattr("zeus.pi_wrapper_env.pwd.getpwuid", lambda _uid: _Pw())

    assert resolve_user_shell() == "/bin/zsh"


def test_shell_login_argv_uses_interactive_login_shell(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")

    class _Pw:
        pw_shell = "/bin/zsh"

    monkeypatch.setattr("zeus.pi_wrapper_env.pwd.getpwuid", lambda _uid: _Pw())

    assert shell_login_argv("printf ok") == ["/bin/zsh", "-ilc", "printf ok"]


def test_shell_login_argv_handles_fish(monkeypatch) -> None:
    monkeypatch.setattr("zeus.pi_wrapper_env.resolve_user_shell", lambda env=None: "/usr/bin/fish")

    assert shell_login_argv("printf ok") == ["/usr/bin/fish", "-i", "-l", "-c", "printf ok"]


def test_missing_provider_env_vars_only_returns_unset(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    missing = missing_provider_env_vars()

    assert "OPENROUTER_API_KEY" not in missing
    assert "OPENAI_API_KEY" in missing
    assert set(missing).issubset(set(PI_PROVIDER_ENV_VARS))


def test_fetch_provider_env_from_process_tree_walks_ancestors() -> None:
    envs = {
        200: {"SHELL": "/bin/bash"},
        100: {"OPENROUTER_API_KEY": "sk-or", "OPENAI_API_KEY": "sk-oa"},
    }
    parents = {200: 100, 100: 1}

    updates = fetch_provider_env_from_process_tree(
        ["OPENROUTER_API_KEY", "OPENAI_API_KEY"],
        start_pid=200,
        environ_reader=lambda pid: envs.get(pid, {}),
        parent_reader=lambda pid: parents.get(pid, 0),
    )

    assert updates == {
        "OPENROUTER_API_KEY": "sk-or",
        "OPENAI_API_KEY": "sk-oa",
    }


def test_fetch_provider_env_from_shell_parses_marker(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")

    class _Pw:
        pw_shell = "/bin/zsh"

    monkeypatch.setattr("zeus.pi_wrapper_env.pwd.getpwuid", lambda _uid: _Pw())

    calls: list[tuple[list[str], dict[str, str]]] = []

    def _run(argv, **kwargs):  # noqa: ANN001
        calls.append((list(argv), dict(kwargs["env"])))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='noise\n__ZEUS_PI_WRAPPER_ENV__{"OPENROUTER_API_KEY":"sk-or","OPENAI_API_KEY":"sk-oa"}\n',
            stderr="",
        )

    updates = fetch_provider_env_from_shell(["OPENROUTER_API_KEY", "OPENAI_API_KEY"], runner=_run)

    assert updates == {
        "OPENROUTER_API_KEY": "sk-or",
        "OPENAI_API_KEY": "sk-oa",
    }
    assert calls[0][0][:2] == ["/bin/zsh", "-ilc"]
    assert calls[0][1]["SHELL"] == "/bin/zsh"
    assert calls[0][1]["ZEUS_PI_WRAPPER_ENV_SYNC"] == "1"


def test_fetch_provider_env_from_shell_ignores_invalid_output(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")

    def _run(argv, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(argv, 0, stdout="garbage\n", stderr="")

    assert fetch_provider_env_from_shell(["OPENROUTER_API_KEY"], runner=_run) == {}


def test_shell_export_lines_quotes_values() -> None:
    exports = shell_export_lines({"OPENROUTER_API_KEY": "sk-or:abc/def", "OPENAI_API_KEY": "x y"})

    assert "export OPENAI_API_KEY='x y'" in exports
    assert "export OPENROUTER_API_KEY=sk-or:abc/def" in exports
