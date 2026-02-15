"""Tests for session encoding and discovery."""

import json

from pathlib import Path

import zeus.sessions as sessions
from zeus.sessions import _encode_session_dir, read_session_text, make_new_session_path


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
