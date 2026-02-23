"""Agent memory storage — SQLite + FTS5.

Provides persistent memory for Zeus agents with namespace-scoped storage,
full-text search, and topic linking.

Database: ~/.zeus/memory.db (created lazily on first use).
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

_ZEUS_HOME = os.path.join(os.environ.get("HOME", "~"), ".zeus")
_DB_PATH_OVERRIDE: Optional[str] = None  # for testing


def _db_path() -> str:
    if _DB_PATH_OVERRIDE:
        return _DB_PATH_OVERRIDE
    return os.path.join(
        os.environ.get("ZEUS_HOME", _ZEUS_HOME),
        "memory.db",
    )


def set_db_path(path: str) -> None:
    """Override DB path (for testing)."""
    global _DB_PATH_OVERRIDE
    _DB_PATH_OVERRIDE = path


def reset_db_path() -> None:
    """Reset DB path to default."""
    global _DB_PATH_OVERRIDE
    _DB_PATH_OVERRIDE = None


_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    tags TEXT DEFAULT '',
    source_agent TEXT DEFAULT '',
    source_project TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    accessed_at TEXT,
    access_count INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,
    UNIQUE(namespace, key)
);

CREATE TABLE IF NOT EXISTS topic_links (
    project TEXT NOT NULL,
    topic TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project, topic)
);

CREATE INDEX IF NOT EXISTS idx_memories_ns
    ON memories(namespace);
CREATE INDEX IF NOT EXISTS idx_memories_ns_archived
    ON memories(namespace, archived);
CREATE INDEX IF NOT EXISTS idx_memories_source_project
    ON memories(source_project);
"""

_FTS_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    namespace, key, content, tags,
    content=memories,
    content_rowid=id
);
"""

# Triggers to keep FTS in sync with the memories table.
_FTS_TRIGGERS_SQL = """\
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, namespace, key, content, tags)
    VALUES (new.id, new.namespace, new.key, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, namespace, key, content, tags)
    VALUES ('delete', old.id, old.namespace, old.key, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, namespace, key, content, tags)
    VALUES ('delete', old.id, old.namespace, old.key, old.content, old.tags);
    INSERT INTO memories_fts(rowid, namespace, key, content, tags)
    VALUES (new.id, new.namespace, new.key, new.content, new.tags);
END;
"""

# Valid namespace prefixes for agent writes.
_WRITABLE_PREFIXES = ("global", "project:", "new:")
# Namespace prefix that only consolidation agents may write to.
_CONSOLIDATION_ONLY_PREFIX = "topic:"

# Regex for validating namespace format.
_NS_RE = re.compile(
    r"^(global|project:[a-zA-Z0-9_-]+|topic:[a-zA-Z0-9_-]+|new:[a-zA-Z0-9_-]+)$"
)


def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open (and lazily initialize) the memory database."""
    path = db_path or _db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA_SQL)
    conn.executescript(_FTS_SQL)
    conn.executescript(_FTS_TRIGGERS_SQL)
    conn.commit()
    return conn


def validate_namespace(namespace: str, *, allow_topic: bool = False) -> str:
    """Validate and return the namespace, or raise ValueError."""
    ns = namespace.strip()
    if not _NS_RE.match(ns):
        raise ValueError(
            f"Invalid namespace '{ns}'. Must be global, project:<name>, "
            f"new:<name>, or topic:<name>."
        )
    if ns.startswith(_CONSOLIDATION_ONLY_PREFIX) and not allow_topic:
        raise ValueError(
            f"Cannot write directly to '{ns}'. "
            f"Write to 'new:{ns[len(_CONSOLIDATION_ONLY_PREFIX):]}' instead."
        )
    return ns


def resolve_project_name(cwd: Optional[str] = None) -> str:
    """Derive project name from git repo root.

    Runs ``git rev-parse --show-toplevel``, strips ~/code/ prefix,
    replaces / with -. Returns empty string if not in a git repo.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if result.returncode != 0:
            return ""
        root = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""

    home = os.environ.get("HOME", "")
    code_prefix = os.path.join(home, "code") + os.sep
    if root.startswith(code_prefix):
        name = root[len(code_prefix):]
    else:
        name = os.path.basename(root)
    return name.replace(os.sep, "-").replace("/", "-")


# ── CRUD operations ──────────────────────────────────────────────────────


def save_memory(
    namespace: str,
    key: str,
    content: str,
    *,
    tags: str = "",
    source_agent: str = "",
    source_project: str = "",
    allow_topic: bool = False,
    db_path: Optional[str] = None,
) -> int:
    """Upsert a memory. Returns the row id."""
    ns = validate_namespace(namespace, allow_topic=allow_topic)
    conn = _get_conn(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO memories (namespace, key, content, tags,
                   source_agent, source_project)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(namespace, key) DO UPDATE SET
                   content = excluded.content,
                   tags = excluded.tags,
                   source_agent = excluded.source_agent,
                   source_project = excluded.source_project,
                   updated_at = datetime('now')
            """,
            (ns, key.strip(), content, tags.strip(), source_agent, source_project),
        )
        row_id = cur.lastrowid or 0

        # Auto-create topic_links for new:* saves.
        if ns.startswith("new:") and source_project:
            topic_name = ns[len("new:"):]
            conn.execute(
                """INSERT OR IGNORE INTO topic_links (project, topic)
                   VALUES (?, ?)""",
                (source_project, topic_name),
            )

        conn.commit()
        return row_id
    finally:
        conn.close()


def recall_memory(
    namespace: str,
    key: str,
    *,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    """Exact key lookup. Bumps access_count and accessed_at. Returns dict or None."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM memories WHERE namespace = ? AND key = ? AND archived = 0",
            (namespace, key),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """UPDATE memories SET access_count = access_count + 1,
                   accessed_at = datetime('now')
               WHERE id = ?""",
            (row["id"],),
        )
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def search_memories(
    query: str,
    *,
    namespaces: Optional[list[str]] = None,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> list[dict]:
    """FTS5 ranked search. Returns list of dicts ordered by relevance."""
    conn = _get_conn(db_path)
    try:
        if namespaces:
            placeholders = ",".join("?" for _ in namespaces)
            sql = f"""
                SELECT m.*, bm25(memories_fts) AS rank
                FROM memories_fts f
                JOIN memories m ON m.id = f.rowid
                WHERE memories_fts MATCH ?
                  AND m.namespace IN ({placeholders})
                  AND m.archived = 0
                ORDER BY rank
                LIMIT ?
            """
            params: list = [query, *namespaces, limit]
        else:
            sql = """
                SELECT m.*, bm25(memories_fts) AS rank
                FROM memories_fts f
                JOIN memories m ON m.id = f.rowid
                WHERE memories_fts MATCH ?
                  AND m.archived = 0
                ORDER BY rank
                LIMIT ?
            """
            params = [query, limit]
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # FTS query syntax errors (e.g., empty query, special chars).
        return []
    finally:
        conn.close()


def list_memories(
    namespace: Optional[str] = None,
    *,
    tags: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[str] = None,
) -> list[dict]:
    """Browse memories. Returns list of dicts with content truncated to 200 chars."""
    conn = _get_conn(db_path)
    try:
        conditions = ["archived = 0"]
        params: list = []
        if namespace:
            conditions.append("namespace = ?")
            params.append(namespace)
        if tags:
            # Match any of the comma-separated tags.
            for tag in tags.split(","):
                tag = tag.strip()
                if tag:
                    conditions.append("tags LIKE ?")
                    params.append(f"%{tag}%")

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""SELECT id, namespace, key,
                       SUBSTR(content, 1, 200) AS content_preview,
                       tags, source_agent, source_project,
                       created_at, updated_at, access_count
                FROM memories
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_memory(
    namespace: str,
    key: str,
    *,
    db_path: Optional[str] = None,
) -> bool:
    """Hard delete. Returns True if a row was deleted."""
    conn = _get_conn(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM memories WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_topics(
    project: str,
    *,
    db_path: Optional[str] = None,
) -> dict:
    """Return linked topics and pending new:* count for a project.

    Returns::

        {
            "linked_topics": ["zk-proofs", "rust-async"],
            "pending_new_count": 3,
        }
    """
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT topic FROM topic_links WHERE project = ? ORDER BY topic",
            (project,),
        ).fetchall()
        linked = [r["topic"] for r in rows]

        # Count new:* memories with source_project matching.
        pending = conn.execute(
            """SELECT COUNT(*) AS cnt FROM memories
               WHERE namespace LIKE 'new:%'
                 AND source_project = ?
                 AND archived = 0""",
            (project,),
        ).fetchone()
        return {
            "linked_topics": linked,
            "pending_new_count": pending["cnt"] if pending else 0,
        }
    finally:
        conn.close()


def rename_project(
    old_name: str,
    new_name: str,
    *,
    db_path: Optional[str] = None,
) -> dict:
    """Rename a project namespace. Updates memories, topic_links, and source_project.

    Returns counts of updated rows.
    """
    old_ns = f"project:{old_name}"
    new_ns = f"project:{new_name}"
    conn = _get_conn(db_path)
    try:
        # Rename namespace in memories.
        r1 = conn.execute(
            "UPDATE memories SET namespace = ? WHERE namespace = ?",
            (new_ns, old_ns),
        )
        # Update source_project references.
        r2 = conn.execute(
            "UPDATE memories SET source_project = ? WHERE source_project = ?",
            (new_name, old_name),
        )
        # Update topic_links.
        r3 = conn.execute(
            "UPDATE topic_links SET project = ? WHERE project = ?",
            (new_name, old_name),
        )
        conn.commit()
        return {
            "memories_renamed": r1.rowcount,
            "source_project_updated": r2.rowcount,
            "topic_links_updated": r3.rowcount,
        }
    finally:
        conn.close()


def get_all_topic_namespaces(*, db_path: Optional[str] = None) -> list[str]:
    """Return all distinct topic:* namespace names (without prefix)."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT DISTINCT SUBSTR(namespace, 7) AS topic
               FROM memories
               WHERE namespace LIKE 'topic:%' AND archived = 0
               ORDER BY topic"""
        ).fetchall()
        return [r["topic"] for r in rows]
    finally:
        conn.close()


def get_memories_for_injection(
    project: str,
    linked_topics: list[str],
    *,
    db_path: Optional[str] = None,
) -> dict[str, list[dict]]:
    """Load memories for system prompt injection, grouped by section.

    Returns::

        {
            "global": [...],
            "project": [...],
            "topics": {"zk-proofs": [...], ...},
        }
    """
    conn = _get_conn(db_path)
    try:
        result: dict[str, object] = {}

        # Global memories.
        result["global"] = [
            dict(r)
            for r in conn.execute(
                """SELECT namespace, key, content FROM memories
                   WHERE namespace = 'global' AND archived = 0
                   ORDER BY access_count DESC, updated_at DESC"""
            ).fetchall()
        ]

        # Project memories.
        project_ns = f"project:{project}"
        result["project"] = [
            dict(r)
            for r in conn.execute(
                """SELECT namespace, key, content FROM memories
                   WHERE namespace = ? AND archived = 0
                   ORDER BY access_count DESC, updated_at DESC""",
                (project_ns,),
            ).fetchall()
        ]

        # Linked topic memories.
        topics: dict[str, list[dict]] = {}
        for topic in linked_topics:
            topic_ns = f"topic:{topic}"
            rows = conn.execute(
                """SELECT namespace, key, content FROM memories
                   WHERE namespace = ? AND archived = 0
                   ORDER BY access_count DESC, updated_at DESC""",
                (topic_ns,),
            ).fetchall()
            topics[topic] = [dict(r) for r in rows]
        result["topics"] = topics

        return result  # type: ignore[return-value]
    finally:
        conn.close()
