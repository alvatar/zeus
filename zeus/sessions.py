"""Claude session forking and discovery for sub-agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .config import AGENT_SESSIONS_DIR


def _encode_session_dir(cwd: str) -> str:
    """Encode a cwd into pi's session directory name."""
    return f"--{cwd.lstrip('/').replace('/', '-').replace(':', '-')}--"


def find_current_session(cwd: str) -> str | None:
    """Find the most recent session file for a given cwd."""
    session_dir: Path = AGENT_SESSIONS_DIR / _encode_session_dir(cwd)
    if not session_dir.is_dir():
        return None
    files = sorted(
        [f for f in session_dir.iterdir() if f.suffix == ".jsonl"],
        key=lambda f: f.name, reverse=True)
    return str(files[0]) if files else None


def _iter_text_content(node: object) -> Iterator[str]:
    """Yield text values for content items where ``type == 'text'``."""
    if isinstance(node, dict):
        if node.get("type") == "text":
            text = node.get("text")
            if isinstance(text, str):
                yield text
        for val in node.values():
            if isinstance(val, (dict, list)):
                yield from _iter_text_content(val)
        return

    if isinstance(node, list):
        for item in node:
            yield from _iter_text_content(item)


def _join_text_chunks(chunks: list[str]) -> str:
    """Join chunks while avoiding artificial blank lines."""
    out = ""
    for chunk in chunks:
        if not chunk:
            continue
        if not out:
            out = chunk
            continue
        if out.endswith("\n") or chunk.startswith("\n"):
            out += chunk
        else:
            out += "\n" + chunk
    return out


def _iter_message_texts(entry: dict, role_filter: set[str] | None) -> Iterator[str]:
    """Yield text chunks from a parsed session entry with optional role filter."""
    if entry.get("type") == "message":
        message = entry.get("message")
        if not isinstance(message, dict):
            return
        role = message.get("role")
        if role_filter is not None and role not in role_filter:
            return

        content = message.get("content")
        if isinstance(content, str):
            if content:
                yield content
            return
        yield from _iter_text_content(content)
        return

    if role_filter is None:
        yield from _iter_text_content(entry)


def _read_session_text_filtered(
    session_path: str,
    *,
    role_filter: set[str] | None,
) -> str:
    path = Path(session_path)
    if not path.is_file():
        return ""

    chunks: list[str] = []
    try:
        with open(path) as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                for text in _iter_message_texts(entry, role_filter):
                    if text:
                        chunks.append(text)
    except OSError:
        return ""

    return _join_text_chunks(chunks)


def read_session_text(session_path: str) -> str:
    """Read all text content fragments from a pi session JSONL file."""
    return _read_session_text_filtered(session_path, role_filter=None)


def read_session_user_text(session_path: str) -> str:
    """Read text fragments from user-role messages only."""
    return _read_session_text_filtered(session_path, role_filter={"user"})


def _new_session_file(target_cwd: str) -> Path:
    """Build a unique session file path under pi's session directory."""
    import uuid
    from datetime import datetime, timezone

    session_dir: Path = AGENT_SESSIONS_DIR / _encode_session_dir(target_cwd)
    session_dir.mkdir(parents=True, exist_ok=True)

    new_id: str = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    ts: str = now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond // 1000:03d}Z"
    return session_dir / f"{ts}_{new_id}.jsonl"


def make_new_session_path(target_cwd: str) -> str:
    """Return a fresh session file path for launching a new pi session."""
    return str(_new_session_file(target_cwd))


def fork_session(source_path: str, target_cwd: str) -> str | None:
    """Fork a pi session file into a new independent session.

    Returns the path to the new session file, or None on failure.
    """
    from datetime import datetime, timezone

    source = Path(source_path)
    if not source.exists():
        return None

    entries: list[dict] = []
    with open(source) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not entries:
        return None

    header: dict | None = next(
        (e for e in entries if e.get("type") == "session"), None
    )
    if not header:
        return None

    new_file: Path = _new_session_file(target_cwd)
    now = datetime.now(timezone.utc)

    new_header: dict = {
        "type": "session",
        "version": header.get("version", 3),
        "id": new_file.stem.split("_", 1)[1],
        "timestamp": now.isoformat(),
        "cwd": target_cwd,
        "parentSession": source_path,
    }

    with open(new_file, "w") as f:
        f.write(json.dumps(new_header) + "\n")
        for entry in entries:
            if entry.get("type") != "session":
                f.write(json.dumps(entry) + "\n")

    return str(new_file)
