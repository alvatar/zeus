"""Filesystem-backed agent bus for extension-delivered queue messages."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import time
import uuid

from .config import (
    AGENT_BUS_CAPS_DIR,
    AGENT_BUS_INBOX_DIR,
    AGENT_BUS_PROCESSED_DIR,
    AGENT_BUS_RECEIPTS_DIR,
)


def sanitize_agent_id(value: str) -> str:
    return "".join(ch for ch in value.strip() if ch.isalnum() or ch in {"-", "_"})


def _agent_dir(root: Path, agent_id: str) -> Path:
    return root / sanitize_agent_id(agent_id)


def _inbox_new_dir(agent_id: str) -> Path:
    return _agent_dir(AGENT_BUS_INBOX_DIR, agent_id) / "new"


def _receipt_file(agent_id: str, message_id: str) -> Path:
    clean_agent_id = sanitize_agent_id(agent_id)
    clean_message_id = message_id.strip()
    return AGENT_BUS_RECEIPTS_DIR / clean_agent_id / f"{clean_message_id}.json"


def _capability_file(agent_id: str) -> Path:
    clean_agent_id = sanitize_agent_id(agent_id)
    return AGENT_BUS_CAPS_DIR / f"{clean_agent_id}.json"


def _write_json_atomic(path: Path, payload: dict[str, object]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex}")
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


def enqueue_agent_bus_message(
    agent_id: str,
    message: str,
    *,
    message_id: str = "",
    source_name: str = "",
    source_agent_id: str = "",
    source_role: str = "",
    deliver_as: str = "followUp",
) -> bool:
    clean_agent_id = sanitize_agent_id(agent_id)
    clean_message = message
    if not clean_agent_id:
        return False
    if not clean_message.strip():
        return False

    inbox_new = _inbox_new_dir(clean_agent_id)
    try:
        inbox_new.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    created_at = time.time()
    file_id = (message_id or uuid.uuid4().hex).strip() or uuid.uuid4().hex
    payload = {
        "id": file_id,
        "created_at": created_at,
        "source_name": source_name.strip(),
        "source_agent_id": source_agent_id.strip(),
        "source_role": source_role.strip().lower(),
        "deliver_as": (deliver_as or "followUp").strip() or "followUp",
        "message": clean_message,
    }

    ts_ms = int(created_at * 1000)
    target = inbox_new / f"{ts_ms:013d}-{file_id}.json"
    return _write_json_atomic(target, payload)


def load_agent_bus_receipt(agent_id: str, message_id: str) -> dict[str, object] | None:
    file_path = _receipt_file(agent_id, message_id)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def has_agent_bus_receipt(agent_id: str, message_id: str) -> bool:
    receipt = load_agent_bus_receipt(agent_id, message_id)
    if receipt is None:
        return False
    status = str(receipt.get("status", "")).strip().lower()
    if status and status != "accepted":
        return False
    msg_id = str(receipt.get("id", "")).strip()
    if msg_id and msg_id != message_id.strip():
        return False
    return True


def load_agent_bus_capability(agent_id: str) -> dict[str, object] | None:
    file_path = _capability_file(agent_id)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _timestamp_from_capability(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        clean = value.strip()
        if not clean:
            return None
        try:
            return float(clean)
        except ValueError:
            pass
        try:
            # Support ISO timestamps with optional Z suffix.
            return datetime.fromisoformat(clean.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def capability_health(
    agent_id: str,
    *,
    max_age_s: float,
    now: float | None = None,
) -> tuple[bool, str | None]:
    cap = load_agent_bus_capability(agent_id)
    if cap is None:
        return False, f"missing capability heartbeat for {sanitize_agent_id(agent_id)}"

    supports = cap.get("supports")
    if isinstance(supports, dict):
        queue_bus = supports.get("queue_bus")
        if queue_bus is False:
            return False, f"capability disabled queue_bus for {sanitize_agent_id(agent_id)}"

    updated_raw = cap.get("updated_at")
    updated_at = _timestamp_from_capability(updated_raw)
    if updated_at is None:
        return False, f"capability heartbeat missing updated_at for {sanitize_agent_id(agent_id)}"

    now_ts = time.time() if now is None else now
    age = now_ts - updated_at
    if age < 0:
        return True, None

    if age > max_age_s:
        return False, (
            f"stale capability heartbeat for {sanitize_agent_id(agent_id)} "
            f"({age:.1f}s > {max_age_s:.1f}s)"
        )

    return True, None


def processed_ledger_path(agent_id: str) -> Path:
    clean_agent_id = sanitize_agent_id(agent_id)
    return AGENT_BUS_PROCESSED_DIR / f"{clean_agent_id}.json"
