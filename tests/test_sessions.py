"""Tests for session encoding and discovery."""

from zeus.sessions import _encode_session_dir


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
