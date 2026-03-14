"""Tests for Zeus shell-launch helpers."""

from __future__ import annotations

from zeus.spawn_shell import (
    kitty_hold_command_argv,
    resolve_user_shell,
    user_shell_command_argv,
    user_shell_command_string,
)


def test_resolve_user_shell_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")

    assert resolve_user_shell() == "/bin/zsh"


def test_user_shell_command_argv_uses_interactive_login_shell(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")

    assert user_shell_command_argv("exec pi --session /tmp/s.jsonl") == [
        "/bin/zsh",
        "-ilc",
        "exec pi --session /tmp/s.jsonl",
    ]


def test_user_shell_command_string_shell_quotes_command(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")

    assert user_shell_command_string("exec pi --session /tmp/s.jsonl --model openrouter/hunter-alpha") == (
        "/bin/zsh -ilc 'exec pi --session /tmp/s.jsonl --model openrouter/hunter-alpha'"
    )


def test_kitty_hold_command_argv_wraps_user_shell(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")

    assert kitty_hold_command_argv("/tmp/project", "exec pi --session /tmp/s.jsonl") == [
        "kitty",
        "--directory",
        "/tmp/project",
        "--hold",
        "/bin/zsh",
        "-ilc",
        "exec pi --session /tmp/s.jsonl",
    ]


def test_user_shell_command_argv_handles_fish(monkeypatch) -> None:
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.setattr("zeus.spawn_shell.resolve_user_shell", lambda env=None: "/usr/bin/fish")

    assert user_shell_command_argv("exec pi") == [
        "/usr/bin/fish",
        "-i",
        "-l",
        "-c",
        "exec pi",
    ]
