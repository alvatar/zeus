"""Tests for session encoding and discovery."""

import json

from pathlib import Path

import zeus.sessions as sessions
from zeus.sessions import (
    _encode_session_dir,
    read_session_text,
    read_session_user_text,
    make_new_session_path,
)


def test_encode_session_dir_basic():
    assert _encode_session_dir("/home/user/project") == "--home-user-project--"


def test_encode_session_dir_root():
    assert _encode_session_dir("/") == "----"


def test_encode_session_dir_nested():
    result = _encode_session_dir("/home/user/code/zeus")
    assert result == "--home-user-code-zeus--"
    assert "/" not in result[2:-2]  # no slashes in the middle


def test_encode_session_dir_with_colon():
    result = _encode_session_dir("/mnt/drive:C/stuff")
    assert ":" not in result


def test_make_new_session_path_creates_target_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "AGENT_SESSIONS_DIR", tmp_path)

    path = Path(make_new_session_path("/home/user/project"))

    assert path.parent == tmp_path / "--home-user-project--"
    assert path.suffix == ".jsonl"
    assert path.parent.is_dir()


def test_read_session_text_collects_text_content(tmp_path):
    session = tmp_path / "sample.jsonl"
    lines = [
        {"type": "session", "id": "abc"},
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "ignore"},
                    {"type": "text", "text": "hello"},
                ],
            },
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "content": [
                    {"type": "text", "text": "world"},
                ],
            },
        },
    ]
    session.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert read_session_text(str(session)) == "hello\nworld"


def test_read_session_text_avoids_artificial_double_newlines(tmp_path):
    session = tmp_path / "double-newlines.jsonl"
    lines = [
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "line1\n"},
                    {"type": "text", "text": "line2"},
                ],
            },
        }
    ]
    session.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert read_session_text(str(session)) == "line1\nline2"


def test_read_session_user_text_filters_non_user_messages(tmp_path):
    session = tmp_path / "user-only.jsonl"
    lines = [
        {"type": "session", "id": "abc"},
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "assistant text"}],
            },
        },
        {
            "type": "message",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "%%%%\n"},
                    {"type": "text", "text": "payload\n"},
                    {"type": "text", "text": "%%%%"},
                ],
            },
        },
    ]
    session.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert read_session_user_text(str(session)) == "%%%%\npayload\n%%%%"


def test_read_session_text_includes_string_message_content(tmp_path):
    session = tmp_path / "string-content.jsonl"
    lines = [
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": "assistant line",
            },
        },
        {
            "type": "message",
            "message": {
                "role": "user",
                "content": "user line",
            },
        },
    ]
    session.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert read_session_text(str(session)) == "assistant line\nuser line"


def test_read_session_user_text_includes_string_message_content(tmp_path):
    session = tmp_path / "user-string-content.jsonl"
    lines = [
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": "assistant line",
            },
        },
        {
            "type": "message",
            "message": {
                "role": "user",
                "content": "user line",
            },
        },
    ]
    session.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert read_session_user_text(str(session)) == "user line"


def test_fork_session_creates_new_file_without_mutating_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "AGENT_SESSIONS_DIR", tmp_path)

    source = tmp_path / "source.jsonl"
    source_entries = [
        {
            "type": "session",
            "version": 3,
            "id": "parent-id",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": "/tmp/project",
        },
        {
            "type": "message",
            "id": "m1",
            "parentId": None,
            "timestamp": "2026-01-01T00:00:01Z",
            "message": {
                "role": "user",
                "content": "hello",
            },
        },
        {
            "type": "message",
            "id": "m2",
            "parentId": "m1",
            "timestamp": "2026-01-01T00:00:02Z",
            "message": {
                "role": "assistant",
                "content": "hi",
            },
        },
    ]
    source.write_text("\n".join(json.dumps(line) for line in source_entries) + "\n")
    parent_before = source.read_bytes()

    child_raw = sessions.fork_session(str(source), "/home/user/project")

    assert child_raw is not None
    child = Path(child_raw)
    assert child != source
    assert child.is_file()
    assert source.read_bytes() == parent_before

    child_entries = [
        json.loads(line)
        for line in child.read_text().splitlines()
        if line.strip()
    ]

    assert child_entries[0]["type"] == "session"
    assert child_entries[0]["cwd"] == "/home/user/project"
    assert child_entries[0]["parentSession"] == str(source)

    source_non_header = [e for e in source_entries if e["type"] != "session"]
    child_non_header = [e for e in child_entries if e["type"] != "session"]
    assert child_non_header == source_non_header
