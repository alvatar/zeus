"""Persistent recipient/message dedupe receipts."""

from __future__ import annotations

import json
from typing import Any

from .config import MESSAGE_RECEIPTS_FILE


def load_message_receipts() -> dict[str, dict[str, float]]:
    try:
        raw = json.loads(MESSAGE_RECEIPTS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    if not isinstance(raw, dict):
        return {}

    out: dict[str, dict[str, float]] = {}
    for recipient_key, values in raw.items():
        if not isinstance(recipient_key, str) or not isinstance(values, dict):
            continue
        rec: dict[str, float] = {}
        for msg_id, ts in values.items():
            if not isinstance(msg_id, str) or not isinstance(ts, (int, float)):
                continue
            rec[msg_id] = float(ts)
        if rec:
            out[recipient_key] = rec
    return out


def save_message_receipts(receipts: dict[str, dict[str, float]]) -> None:
    payload: dict[str, dict[str, float]] = {}
    for recipient_key, values in receipts.items():
        if not isinstance(recipient_key, str) or not isinstance(values, dict):
            continue
        rec: dict[str, float] = {}
        for msg_id, ts in values.items():
            if not isinstance(msg_id, str) or not isinstance(ts, (int, float)):
                continue
            rec[msg_id] = float(ts)
        if rec:
            payload[recipient_key] = rec

    MESSAGE_RECEIPTS_FILE.write_text(json.dumps(payload))


def prune_message_receipts(
    receipts: dict[str, dict[str, float]],
    *,
    now: float,
    ttl_seconds: float,
) -> bool:
    changed = False
    cutoff = now - ttl_seconds

    for recipient_key in list(receipts.keys()):
        values = receipts[recipient_key]
        for msg_id in list(values.keys()):
            if values[msg_id] >= cutoff:
                continue
            values.pop(msg_id, None)
            changed = True
        if values:
            continue
        receipts.pop(recipient_key, None)
        changed = True

    return changed


def has_message_receipt(
    receipts: dict[str, dict[str, float]],
    *,
    recipient_key: str,
    message_id: str,
    now: float,
    ttl_seconds: float,
) -> bool:
    rec = receipts.get(recipient_key)
    if rec is None:
        return False

    ts = rec.get(message_id)
    if ts is None:
        return False

    if ts < (now - ttl_seconds):
        rec.pop(message_id, None)
        if not rec:
            receipts.pop(recipient_key, None)
        return False

    return True


def record_message_receipt(
    receipts: dict[str, dict[str, float]],
    *,
    recipient_key: str,
    message_id: str,
    now: float,
) -> None:
    rec = receipts.setdefault(recipient_key, {})
    rec[message_id] = now
