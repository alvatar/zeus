"""Filesystem inbox delivery for hoplite sessions.

Zeus writes one JSON message file per hoplite-targeted delivery. Hoplite-side
extensions consume files and inject them into the running pi session.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
import uuid

from .config import HOPLITE_INBOX_DIR


def _sanitize_agent_id(value: str) -> str:
    return "".join(ch for ch in value.strip() if ch.isalnum() or ch in {"-", "_"})


def _agent_inbox_dir(agent_id: str) -> Path:
    return HOPLITE_INBOX_DIR / _sanitize_agent_id(agent_id)


def enqueue_hoplite_inbox_message(
    agent_id: str,
    message: str,
    *,
    message_id: str = "",
    source_name: str = "",
    source_agent_id: str = "",
) -> bool:
    """Write one inbox message file for a hoplite.

    Returns False when inputs are invalid or persistence fails.
    """
    clean_agent_id = _sanitize_agent_id(agent_id)
    clean_message = message
    if not clean_agent_id:
        return False
    if not clean_message.strip():
        return False

    inbox_dir = _agent_inbox_dir(clean_agent_id)
    try:
        inbox_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    created_at = time.time()
    file_id = (message_id or uuid.uuid4().hex).strip()
    payload = {
        "id": file_id,
        "created_at": created_at,
        "source_name": source_name.strip(),
        "source_agent_id": source_agent_id.strip(),
        "message": clean_message,
    }

    ts_ms = int(created_at * 1000)
    target = inbox_dir / f"{ts_ms:013d}-{file_id}.json"
    tmp = target.with_suffix(target.suffix + f".tmp.{uuid.uuid4().hex}")

    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(target)
        return True
    except OSError:
        return False
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
