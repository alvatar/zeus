"""Tests for per-agent dependency persistence."""

import zeus.dependencies as deps


def test_load_agent_dependencies_returns_empty_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "AGENT_DEPENDENCIES_FILE", tmp_path / "missing.json")
    assert deps.load_agent_dependencies() == {}


def test_save_and_load_agent_dependencies_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "deps.json"
    monkeypatch.setattr(deps, "AGENT_DEPENDENCIES_FILE", path)

    deps.save_agent_dependencies({
        "a": "b",
        "x": "x",  # filtered self-dependency
        "": "z",    # filtered empty
    })

    assert deps.load_agent_dependencies() == {"a": "b"}
