"""Tests for interact input history persistence."""

import zeus.input_history as history


def test_append_history_caps_to_max_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "INPUT_HISTORY_DIR", tmp_path)
    monkeypatch.setattr(history, "INPUT_HISTORY_MAX", 3)

    key = "agent:Zeus"
    for i in range(6):
        history.append_history(key, f"msg-{i}")

    assert history.load_history(key) == ["msg-3", "msg-4", "msg-5"]


def test_append_history_skips_immediate_duplicate(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "INPUT_HISTORY_DIR", tmp_path)
    monkeypatch.setattr(history, "INPUT_HISTORY_MAX", 10)

    key = "agent:Zeus"
    history.append_history(key, "hello")
    history.append_history(key, "hello")

    assert history.load_history(key) == ["hello"]


def test_prune_histories_removes_absent_targets(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "INPUT_HISTORY_DIR", tmp_path)
    monkeypatch.setattr(history, "INPUT_HISTORY_MAX", 10)

    keep = "agent:keep"
    stale = "agent:stale"
    history.append_history(keep, "a")
    history.append_history(stale, "b")

    keep_path = history.history_path_for_key(keep)
    stale_path = history.history_path_for_key(stale)

    assert keep_path.exists()
    assert stale_path.exists()

    history.prune_histories({keep})

    assert keep_path.exists()
    assert not stale_path.exists()
