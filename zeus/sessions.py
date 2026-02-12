"""Claude session forking and discovery for sub-agents."""

from __future__ import annotations

import json
from pathlib import Path

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


def fork_session(source_path: str, target_cwd: str) -> str | None:
    """Fork a pi session file into a new independent session.

    Returns the path to the new session file, or None on failure.
    """
    import uuid
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

    session_dir: Path = AGENT_SESSIONS_DIR / _encode_session_dir(target_cwd)
    session_dir.mkdir(parents=True, exist_ok=True)

    new_id: str = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    ts: str = now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond // 1000:03d}Z"
    new_file: Path = session_dir / f"{ts}_{new_id}.jsonl"

    new_header: dict = {
        "type": "session",
        "version": header.get("version", 3),
        "id": new_id,
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
