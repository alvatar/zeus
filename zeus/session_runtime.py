"""Runtime session path synchronization and captured-session adoption helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import time
from pathlib import Path


_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SESSION_MAP_MAX_AGE_DEFAULT_S = 24 * 60 * 60


@dataclass(frozen=True)
class RuntimeSessionEntry:
    session_key: str
    session_path: str
    session_id: str
    cwd: str
    updated_at: float
    agent_id: str = ""


def _session_map_dir() -> Path:
    default_dir = os.path.join(os.path.expanduser("~/.zeus"), "session-map")
    raw = os.environ.get("ZEUS_SESSION_MAP_DIR", default_dir)
    return Path(os.path.expanduser(raw))


def _session_records_dir() -> Path:
    return _session_map_dir() / "sessions"


def _session_adoptions_dir() -> Path:
    return _session_map_dir() / "adoptions"


def _session_map_file(agent_id: str) -> Path | None:
    clean = agent_id.strip()
    if not clean or not _AGENT_ID_RE.fullmatch(clean):
        return None
    return _session_map_dir() / f"{clean}.json"


def _session_map_max_age_s() -> float:
    raw = (os.environ.get("ZEUS_SESSION_MAP_MAX_AGE_S") or "").strip()
    if not raw:
        return float(_SESSION_MAP_MAX_AGE_DEFAULT_S)
    try:
        parsed = float(raw)
    except ValueError:
        return float(_SESSION_MAP_MAX_AGE_DEFAULT_S)
    if parsed <= 0:
        return float(_SESSION_MAP_MAX_AGE_DEFAULT_S)
    return parsed


def _parse_updated_at_timestamp(raw: object) -> float | None:
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None

    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if dt.tzinfo is None:
        return None

    return dt.timestamp()


def _normalize_session_path(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None

    expanded = os.path.expanduser(raw.strip())
    if not expanded or not os.path.isabs(expanded):
        return None
    if not os.path.isfile(expanded):
        return None
    return expanded


def session_runtime_key(session_path: str) -> str | None:
    normalized = _normalize_session_path(session_path)
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest


def _session_record_file(session_path: str) -> Path | None:
    key = session_runtime_key(session_path)
    if not key:
        return None
    return _session_records_dir() / f"{key}.json"


def _session_adoption_file(session_path: str) -> Path | None:
    key = session_runtime_key(session_path)
    if not key:
        return None
    return _session_adoptions_dir() / f"{key}.json"


def _write_json_atomic(path: Path, payload: dict[str, object]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{time.time_ns()}")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _runtime_entry_from_payload(
    payload: object,
    *,
    now: float | None = None,
    expected_agent_id: str | None = None,
    expected_session_path: str | None = None,
) -> RuntimeSessionEntry | None:
    if not isinstance(payload, dict):
        return None

    updated_at_ts = _parse_updated_at_timestamp(payload.get("updatedAt"))
    if updated_at_ts is None:
        return None

    now_ts = time.time() if now is None else now
    if now_ts - updated_at_ts > _session_map_max_age_s():
        return None

    session_path = _normalize_session_path(payload.get("sessionPath"))
    if session_path is None:
        return None

    if expected_session_path is not None:
        normalized_expected = _normalize_session_path(expected_session_path)
        if normalized_expected is None or normalized_expected != session_path:
            return None

    payload_agent_id = payload.get("agentId")
    clean_agent_id = ""
    if isinstance(payload_agent_id, str):
        clean_agent_id = payload_agent_id.strip()
        if clean_agent_id and not _AGENT_ID_RE.fullmatch(clean_agent_id):
            return None

    if expected_agent_id is not None and clean_agent_id and clean_agent_id != expected_agent_id.strip():
        return None

    session_key = session_runtime_key(session_path)
    if not session_key:
        return None

    session_id_raw = payload.get("sessionId")
    session_id = session_id_raw.strip() if isinstance(session_id_raw, str) else ""
    cwd_raw = payload.get("cwd")
    cwd = cwd_raw.strip() if isinstance(cwd_raw, str) else ""

    return RuntimeSessionEntry(
        session_key=session_key,
        session_path=session_path,
        session_id=session_id,
        cwd=cwd,
        updated_at=updated_at_ts,
        agent_id=clean_agent_id,
    )


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def read_runtime_session_path(agent_id: str) -> str | None:
    """Read the latest session path published by the Zeus pi extension.

    Returns ``None`` when the runtime map is missing, malformed, mismatched,
    stale, or points at a missing session file.
    """
    map_file = _session_map_file(agent_id)
    if map_file is None:
        return None

    payload = _load_json(map_file)
    entry = _runtime_entry_from_payload(payload, expected_agent_id=agent_id)
    return entry.session_path if entry is not None else None


def list_runtime_sessions(*, now: float | None = None) -> list[RuntimeSessionEntry]:
    """Return fresh runtime session entries keyed by session path.

    These entries are published by the Zeus pi extension even when a session has
    not yet been adopted into a deterministic ``ZEUS_AGENT_ID``.
    """
    records_dir = _session_records_dir()
    try:
        files = sorted(records_dir.glob("*.json"))
    except OSError:
        return []

    out: list[RuntimeSessionEntry] = []
    for file_path in files:
        payload = _load_json(file_path)
        entry = _runtime_entry_from_payload(payload, now=now)
        if entry is not None:
            out.append(entry)

    out.sort(key=lambda entry: (entry.updated_at, entry.session_key), reverse=True)
    return out


def read_adopted_agent_id(session_path: str) -> str | None:
    """Return the adopted deterministic agent id for ``session_path``.

    Session adoption is session-file scoped, so stale records for deleted files
    are ignored automatically.
    """
    adoption_file = _session_adoption_file(session_path)
    if adoption_file is None:
        return None

    payload = _load_json(adoption_file)
    if not isinstance(payload, dict):
        return None

    normalized = _normalize_session_path(session_path)
    if normalized is None:
        return None

    payload_path = _normalize_session_path(payload.get("sessionPath"))
    if payload_path is None or payload_path != normalized:
        return None

    agent_id_raw = payload.get("agentId")
    if not isinstance(agent_id_raw, str):
        return None

    agent_id = agent_id_raw.strip()
    if not agent_id or not _AGENT_ID_RE.fullmatch(agent_id):
        return None

    return agent_id


def write_session_adoption(session_path: str, agent_id: str) -> bool:
    """Persist deterministic ownership for a captured session path."""
    clean_agent_id = agent_id.strip()
    if not clean_agent_id or not _AGENT_ID_RE.fullmatch(clean_agent_id):
        return False

    adoption_file = _session_adoption_file(session_path)
    normalized = _normalize_session_path(session_path)
    if adoption_file is None or normalized is None:
        return False

    existing = read_adopted_agent_id(normalized)
    if existing == clean_agent_id:
        return True

    payload: dict[str, object] = {
        "agentId": clean_agent_id,
        "sessionPath": normalized,
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return _write_json_atomic(adoption_file, payload)
