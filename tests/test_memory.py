"""Tests for zeus.memory — agent memory storage."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from zeus.memory import (
    _get_conn,
    delete_memory,
    get_all_topic_namespaces,
    get_memories_for_injection,
    list_memories,
    list_topics,
    recall_memory,
    rename_project,
    resolve_project_name,
    save_memory,
    search_memories,
    validate_namespace,
)


@pytest.fixture()
def db(tmp_path: Path) -> str:
    """Return a temporary DB path for each test."""
    return str(tmp_path / "test-memory.db")


# ── Schema & init ────────────────────────────────────────────────────────


def test_lazy_init_creates_tables(db: str) -> None:
    conn = _get_conn(db)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "memories" in tables
    assert "topic_links" in tables
    assert "memories_fts" in tables


def test_lazy_init_creates_triggers(db: str) -> None:
    conn = _get_conn(db)
    triggers = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    conn.close()
    assert "memories_ai" in triggers
    assert "memories_ad" in triggers
    assert "memories_au" in triggers


def test_lazy_init_creates_parent_dirs(tmp_path: Path) -> None:
    deep = str(tmp_path / "a" / "b" / "c" / "memory.db")
    conn = _get_conn(deep)
    conn.close()
    assert os.path.exists(deep)


# ── Namespace validation ─────────────────────────────────────────────────


def test_validate_global() -> None:
    assert validate_namespace("global") == "global"


def test_validate_project() -> None:
    assert validate_namespace("project:zeus") == "project:zeus"
    assert validate_namespace("project:barlovento-main") == "project:barlovento-main"


def test_validate_new() -> None:
    assert validate_namespace("new:rust-async") == "new:rust-async"


def test_validate_topic_rejected_by_default() -> None:
    with pytest.raises(ValueError, match="Cannot write directly"):
        validate_namespace("topic:zk-proofs")


def test_validate_topic_allowed_with_flag() -> None:
    assert validate_namespace("topic:zk-proofs", allow_topic=True) == "topic:zk-proofs"


def test_validate_invalid_namespace() -> None:
    with pytest.raises(ValueError, match="Invalid namespace"):
        validate_namespace("bogus")


def test_validate_empty_namespace() -> None:
    with pytest.raises(ValueError, match="Invalid namespace"):
        validate_namespace("")


def test_validate_namespace_strips_whitespace() -> None:
    assert validate_namespace("  global  ") == "global"


def test_validate_rejects_slashes() -> None:
    with pytest.raises(ValueError, match="Invalid namespace"):
        validate_namespace("project:foo/bar")


# ── Project name resolution ──────────────────────────────────────────────


def test_resolve_project_name_in_zeus_repo() -> None:
    # Run from the zeus repo itself.
    name = resolve_project_name("/home/alvatar/code/zeus")
    assert name == "zeus"


def test_resolve_project_name_not_a_repo(tmp_path: Path) -> None:
    name = resolve_project_name(str(tmp_path))
    assert name == ""


# ── Save / recall ────────────────────────────────────────────────────────


def test_save_and_recall(db: str) -> None:
    save_memory("global", "pref:style", "early returns", db_path=db)
    m = recall_memory("global", "pref:style", db_path=db)
    assert m is not None
    assert m["content"] == "early returns"
    assert m["namespace"] == "global"
    assert m["key"] == "pref:style"


def test_save_upsert_updates_content(db: str) -> None:
    save_memory("global", "k1", "v1", db_path=db)
    save_memory("global", "k1", "v2", db_path=db)
    m = recall_memory("global", "k1", db_path=db)
    assert m is not None
    assert m["content"] == "v2"


def test_recall_bumps_access_count(db: str) -> None:
    save_memory("global", "k1", "v1", db_path=db)
    recall_memory("global", "k1", db_path=db)  # reads 0, bumps to 1
    recall_memory("global", "k1", db_path=db)  # reads 1, bumps to 2
    m = recall_memory("global", "k1", db_path=db)  # reads 2, bumps to 3
    assert m is not None
    # The SELECT returns the row before the UPDATE in the same call.
    assert m["access_count"] == 2


def test_recall_nonexistent_returns_none(db: str) -> None:
    assert recall_memory("global", "nope", db_path=db) is None


def test_save_rejects_topic_namespace(db: str) -> None:
    with pytest.raises(ValueError, match="Cannot write directly"):
        save_memory("topic:zk", "k", "v", db_path=db)


def test_save_allows_topic_with_flag(db: str) -> None:
    row_id = save_memory("topic:zk", "k", "v", allow_topic=True, db_path=db)
    assert row_id > 0
    m = recall_memory("topic:zk", "k", db_path=db)
    assert m is not None


def test_save_auto_fills_source_fields(db: str) -> None:
    save_memory(
        "project:zeus",
        "k1",
        "v1",
        source_agent="agent-1",
        source_project="zeus",
        db_path=db,
    )
    m = recall_memory("project:zeus", "k1", db_path=db)
    assert m is not None
    assert m["source_agent"] == "agent-1"
    assert m["source_project"] == "zeus"


def test_save_new_creates_topic_link(db: str) -> None:
    save_memory(
        "new:rust-async",
        "k1",
        "v1",
        source_project="zeus",
        db_path=db,
    )
    topics = list_topics("zeus", db_path=db)
    assert "rust-async" in topics["linked_topics"]


def test_save_new_without_source_project_no_link(db: str) -> None:
    save_memory("new:rust-async", "k1", "v1", db_path=db)
    topics = list_topics("", db_path=db)
    assert topics["linked_topics"] == []


def test_save_tags(db: str) -> None:
    save_memory("global", "k1", "v1", tags="correction,pending", db_path=db)
    m = recall_memory("global", "k1", db_path=db)
    assert m is not None
    assert m["tags"] == "correction,pending"


# ── Delete ───────────────────────────────────────────────────────────────


def test_delete_existing(db: str) -> None:
    save_memory("global", "k1", "v1", db_path=db)
    assert delete_memory("global", "k1", db_path=db) is True
    assert recall_memory("global", "k1", db_path=db) is None


def test_delete_nonexistent(db: str) -> None:
    assert delete_memory("global", "nope", db_path=db) is False


def test_delete_removes_from_fts(db: str) -> None:
    save_memory("global", "k1", "unique fts term xyzzy", db_path=db)
    results = search_memories("xyzzy", db_path=db)
    assert len(results) == 1
    delete_memory("global", "k1", db_path=db)
    results = search_memories("xyzzy", db_path=db)
    assert len(results) == 0


# ── Search (FTS5) ────────────────────────────────────────────────────────


def test_search_basic(db: str) -> None:
    save_memory("global", "k1", "rust error handling patterns", db_path=db)
    save_memory("global", "k2", "python type hints", db_path=db)
    results = search_memories("rust error", db_path=db)
    assert len(results) >= 1
    assert results[0]["key"] == "k1"


def test_search_filters_by_namespace(db: str) -> None:
    save_memory("global", "k1", "shared term foobar", db_path=db)
    save_memory("project:zeus", "k2", "shared term foobar", db_path=db)
    results = search_memories(
        "foobar", namespaces=["project:zeus"], db_path=db
    )
    assert len(results) == 1
    assert results[0]["namespace"] == "project:zeus"


def test_search_empty_query_returns_empty(db: str) -> None:
    save_memory("global", "k1", "content", db_path=db)
    results = search_memories("", db_path=db)
    assert results == []


def test_search_respects_limit(db: str) -> None:
    for i in range(20):
        save_memory("global", f"k{i}", f"common term {i}", db_path=db)
    results = search_memories("common term", limit=5, db_path=db)
    assert len(results) == 5


def test_search_excludes_archived(db: str) -> None:
    save_memory("global", "k1", "findable term", db_path=db)
    conn = _get_conn(db)
    conn.execute("UPDATE memories SET archived = 1 WHERE key = 'k1'")
    conn.commit()
    conn.close()
    results = search_memories("findable", db_path=db)
    assert len(results) == 0


# ── List ─────────────────────────────────────────────────────────────────


def test_list_by_namespace(db: str) -> None:
    save_memory("global", "k1", "v1", db_path=db)
    save_memory("project:zeus", "k2", "v2", db_path=db)
    results = list_memories("global", db_path=db)
    assert len(results) == 1
    assert results[0]["key"] == "k1"


def test_list_all(db: str) -> None:
    save_memory("global", "k1", "v1", db_path=db)
    save_memory("project:zeus", "k2", "v2", db_path=db)
    results = list_memories(db_path=db)
    assert len(results) == 2


def test_list_truncates_content(db: str) -> None:
    long_content = "x" * 500
    save_memory("global", "k1", long_content, db_path=db)
    results = list_memories("global", db_path=db)
    assert len(results[0]["content_preview"]) == 200


def test_list_filters_by_tags(db: str) -> None:
    save_memory("global", "k1", "v1", tags="correction,pending", db_path=db)
    save_memory("global", "k2", "v2", tags="mistake,automated", db_path=db)
    results = list_memories("global", tags="correction", db_path=db)
    assert len(results) == 1
    assert results[0]["key"] == "k1"


def test_list_respects_limit(db: str) -> None:
    for i in range(20):
        save_memory("global", f"k{i}", f"v{i}", db_path=db)
    results = list_memories("global", limit=5, db_path=db)
    assert len(results) == 5


def test_list_excludes_archived(db: str) -> None:
    save_memory("global", "k1", "v1", db_path=db)
    conn = _get_conn(db)
    conn.execute("UPDATE memories SET archived = 1 WHERE key = 'k1'")
    conn.commit()
    conn.close()
    results = list_memories("global", db_path=db)
    assert len(results) == 0


# ── List topics ──────────────────────────────────────────────────────────


def test_list_topics_with_links(db: str) -> None:
    save_memory(
        "new:zk-proofs", "k1", "v1", source_project="zeus", db_path=db
    )
    save_memory(
        "new:rust-async", "k2", "v2", source_project="zeus", db_path=db
    )
    result = list_topics("zeus", db_path=db)
    assert sorted(result["linked_topics"]) == ["rust-async", "zk-proofs"]
    assert result["pending_new_count"] == 2


def test_list_topics_empty_project(db: str) -> None:
    result = list_topics("nonexistent", db_path=db)
    assert result["linked_topics"] == []
    assert result["pending_new_count"] == 0


# ── Rename project ───────────────────────────────────────────────────────


def test_rename_project_updates_memories(db: str) -> None:
    save_memory("project:old-name", "k1", "v1", source_project="old-name", db_path=db)
    save_memory(
        "new:topic1", "k2", "v2", source_project="old-name", db_path=db
    )
    result = rename_project("old-name", "new-name", db_path=db)
    assert result["memories_renamed"] == 1
    assert result["source_project_updated"] >= 1
    assert result["topic_links_updated"] == 1

    # Old namespace gone.
    assert recall_memory("project:old-name", "k1", db_path=db) is None
    # New namespace has the memory.
    m = recall_memory("project:new-name", "k1", db_path=db)
    assert m is not None
    assert m["source_project"] == "new-name"

    # Topic link updated.
    topics = list_topics("new-name", db_path=db)
    assert "topic1" in topics["linked_topics"]
    topics_old = list_topics("old-name", db_path=db)
    assert topics_old["linked_topics"] == []


# ── get_all_topic_namespaces ─────────────────────────────────────────────


def test_get_all_topic_namespaces(db: str) -> None:
    save_memory("topic:zk", "k1", "v1", allow_topic=True, db_path=db)
    save_memory("topic:rust", "k2", "v2", allow_topic=True, db_path=db)
    save_memory("global", "k3", "v3", db_path=db)
    topics = get_all_topic_namespaces(db_path=db)
    assert sorted(topics) == ["rust", "zk"]


def test_get_all_topic_namespaces_empty(db: str) -> None:
    assert get_all_topic_namespaces(db_path=db) == []


# ── get_memories_for_injection ───────────────────────────────────────────


def test_get_memories_for_injection(db: str) -> None:
    save_memory("global", "pref", "early returns", db_path=db)
    save_memory("project:zeus", "conv", "modal errors", db_path=db)
    save_memory("topic:zk", "circuit", "grows quadratic", allow_topic=True, db_path=db)

    data = get_memories_for_injection("zeus", ["zk"], db_path=db)
    assert len(data["global"]) == 1
    assert data["global"][0]["content"] == "early returns"
    assert len(data["project"]) == 1
    assert data["project"][0]["content"] == "modal errors"
    assert "zk" in data["topics"]
    assert len(data["topics"]["zk"]) == 1


def test_get_memories_for_injection_empty_db(db: str) -> None:
    data = get_memories_for_injection("zeus", [], db_path=db)
    assert data["global"] == []
    assert data["project"] == []
    assert data["topics"] == {}


def test_get_memories_for_injection_excludes_archived(db: str) -> None:
    save_memory("global", "k1", "v1", db_path=db)
    conn = _get_conn(db)
    conn.execute("UPDATE memories SET archived = 1 WHERE key = 'k1'")
    conn.commit()
    conn.close()
    data = get_memories_for_injection("zeus", [], db_path=db)
    assert data["global"] == []


# ── FTS sync on update ───────────────────────────────────────────────────


def test_fts_syncs_on_update(db: str) -> None:
    save_memory("global", "k1", "original content alpha", db_path=db)
    results = search_memories("alpha", db_path=db)
    assert len(results) == 1

    save_memory("global", "k1", "updated content beta", db_path=db)
    # Old term gone.
    results = search_memories("alpha", db_path=db)
    assert len(results) == 0
    # New term found.
    results = search_memories("beta", db_path=db)
    assert len(results) == 1
