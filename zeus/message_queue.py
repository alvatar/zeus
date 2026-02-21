"""Filesystem-backed outbound message queue for Zeus injector delivery.

Queue layout (all under ``MESSAGE_QUEUE_DIR``):
- ``new/``      pending envelopes
- ``inflight/`` claimed envelopes being delivered

Ack semantics:
- Envelope is removed only after the dispatcher confirms recipient completion.
- Failed or pending deliveries are re-queued with backoff.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
import uuid

from .config import MESSAGE_QUEUE_DIR


_TARGET_AGENT = "agent"
_TARGET_HOPLITE = "hoplite"
_TARGET_PHALANX = "phalanx"
_VALID_TARGET_KINDS = {_TARGET_AGENT, _TARGET_HOPLITE, _TARGET_PHALANX}

_DELIVERY_FOLLOW_UP = "followUp"
_DELIVERY_STEER = "steer"
_VALID_DELIVERY_MODES = {_DELIVERY_FOLLOW_UP, _DELIVERY_STEER}


@dataclass
class OutboundEnvelope:
    """Persisted outbound message envelope."""

    id: str
    source_name: str
    source_agent_id: str
    source_role: str
    source_parent_id: str
    source_phalanx_id: str
    target_kind: str
    target_ref: str
    target_owner_id: str
    target_agent_id: str
    target_name: str
    delivery_mode: str
    message: str
    created_at: float
    updated_at: float
    attempts: int = 0
    next_attempt_at: float = 0.0

    @classmethod
    def new(
        cls,
        *,
        source_name: str,
        message: str,
        source_agent_id: str = "",
        source_role: str = "",
        source_parent_id: str = "",
        source_phalanx_id: str = "",
        target_kind: str = _TARGET_AGENT,
        target_ref: str = "",
        target_owner_id: str = "",
        target_agent_id: str = "",
        target_name: str = "",
        delivery_mode: str = _DELIVERY_FOLLOW_UP,
    ) -> "OutboundEnvelope":
        now = time.time()
        kind = target_kind.strip().lower() or _TARGET_AGENT
        ref = target_ref.strip()
        agent_id = target_agent_id.strip()
        mode = delivery_mode.strip() or _DELIVERY_FOLLOW_UP
        if mode not in _VALID_DELIVERY_MODES:
            mode = _DELIVERY_FOLLOW_UP

        if kind == _TARGET_AGENT:
            if not ref:
                ref = agent_id
            if not agent_id:
                agent_id = ref

        return cls(
            id=uuid.uuid4().hex,
            source_name=source_name.strip(),
            source_agent_id=source_agent_id.strip(),
            source_role=source_role.strip().lower(),
            source_parent_id=source_parent_id.strip(),
            source_phalanx_id=source_phalanx_id.strip(),
            target_kind=kind,
            target_ref=ref,
            target_owner_id=target_owner_id.strip(),
            target_agent_id=agent_id,
            target_name=target_name.strip(),
            delivery_mode=mode,
            message=message,
            created_at=now,
            updated_at=now,
            attempts=0,
            next_attempt_at=0.0,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "OutboundEnvelope" | None:
        def _s(key: str) -> str:
            val = raw.get(key)
            return val.strip() if isinstance(val, str) else ""

        def _f(key: str) -> float:
            val = raw.get(key)
            if isinstance(val, (int, float)):
                return float(val)
            return 0.0

        envelope_id = _s("id")
        source_name = _s("source_name")
        source_agent_id = _s("source_agent_id")
        source_role = _s("source_role").lower()
        source_parent_id = _s("source_parent_id")
        source_phalanx_id = _s("source_phalanx_id")

        target_kind = (_s("target_kind") or _TARGET_AGENT).lower()
        target_ref = _s("target_ref")
        target_owner_id = _s("target_owner_id")
        target_agent_id = _s("target_agent_id")
        target_name = _s("target_name")
        delivery_mode = _s("delivery_mode") or _DELIVERY_FOLLOW_UP

        if target_kind not in _VALID_TARGET_KINDS:
            return None

        if target_kind == _TARGET_AGENT:
            if not target_ref:
                target_ref = target_agent_id
            if not target_agent_id:
                target_agent_id = target_ref
            if not target_ref:
                return None
        else:
            if not target_ref:
                return None

        if delivery_mode not in _VALID_DELIVERY_MODES:
            delivery_mode = _DELIVERY_FOLLOW_UP

        message_raw = raw.get("message")
        message = message_raw if isinstance(message_raw, str) else ""
        if not (envelope_id and message):
            return None

        attempts_raw = raw.get("attempts", 0)
        attempts = int(attempts_raw) if isinstance(attempts_raw, (int, float)) else 0

        return cls(
            id=envelope_id,
            source_name=source_name,
            source_agent_id=source_agent_id,
            source_role=source_role,
            source_parent_id=source_parent_id,
            source_phalanx_id=source_phalanx_id,
            target_kind=target_kind,
            target_ref=target_ref,
            target_owner_id=target_owner_id,
            target_agent_id=target_agent_id,
            target_name=target_name,
            delivery_mode=delivery_mode,
            message=message,
            created_at=_f("created_at"),
            updated_at=_f("updated_at"),
            attempts=attempts,
            next_attempt_at=_f("next_attempt_at"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_name": self.source_name,
            "source_agent_id": self.source_agent_id,
            "source_role": self.source_role,
            "source_parent_id": self.source_parent_id,
            "source_phalanx_id": self.source_phalanx_id,
            "target_kind": self.target_kind,
            "target_ref": self.target_ref,
            "target_owner_id": self.target_owner_id,
            "target_agent_id": self.target_agent_id,
            "target_name": self.target_name,
            "delivery_mode": self.delivery_mode,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attempts": self.attempts,
            "next_attempt_at": self.next_attempt_at,
        }


def _new_dir() -> Path:
    return MESSAGE_QUEUE_DIR / "new"


def _inflight_dir() -> Path:
    return MESSAGE_QUEUE_DIR / "inflight"


def ensure_queue_dirs() -> None:
    _new_dir().mkdir(parents=True, exist_ok=True)
    _inflight_dir().mkdir(parents=True, exist_ok=True)


def queue_new_dir() -> Path:
    ensure_queue_dirs()
    return _new_dir()


def _envelope_filename(envelope: OutboundEnvelope) -> str:
    ts_ms = int(envelope.created_at * 1000)
    return f"{ts_ms:013d}-{envelope.id}.json"


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex}")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)


def enqueue_envelope(envelope: OutboundEnvelope) -> Path:
    ensure_queue_dirs()
    target = _new_dir() / _envelope_filename(envelope)
    _atomic_write_json(target, envelope.to_dict())
    return target


def load_envelope(path: Path) -> OutboundEnvelope | None:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return OutboundEnvelope.from_dict(raw)


def _mtime_sort_key(path: Path) -> tuple[int, str]:
    try:
        return (path.stat().st_mtime_ns, path.name)
    except OSError:
        return (0, path.name)


def list_new_envelopes() -> list[Path]:
    ensure_queue_dirs()
    return sorted(
        [p for p in _new_dir().iterdir() if p.is_file() and p.suffix == ".json"],
        key=_mtime_sort_key,
    )


def list_inflight_envelopes() -> list[Path]:
    ensure_queue_dirs()
    return sorted(
        [p for p in _inflight_dir().iterdir() if p.is_file() and p.suffix == ".json"],
        key=_mtime_sort_key,
    )


def claim_envelope(new_path: Path) -> Path | None:
    ensure_queue_dirs()
    if new_path.parent != _new_dir():
        return None
    target = _inflight_dir() / new_path.name
    try:
        new_path.replace(target)
    except OSError:
        return None
    return target


def ack_envelope(inflight_path: Path) -> None:
    try:
        inflight_path.unlink()
    except OSError:
        pass


def requeue_envelope(
    inflight_path: Path,
    envelope: OutboundEnvelope,
    *,
    now: float,
    delay_seconds: float,
) -> Path | None:
    envelope.attempts += 1
    envelope.updated_at = now
    envelope.next_attempt_at = now + max(0.0, delay_seconds)
    try:
        _atomic_write_json(inflight_path, envelope.to_dict())
    except OSError:
        return None

    target = _new_dir() / inflight_path.name
    try:
        inflight_path.replace(target)
    except OSError:
        return None
    return target


def reclaim_stale_inflight(lease_seconds: float, *, now: float | None = None) -> int:
    if lease_seconds <= 0:
        return 0

    ensure_queue_dirs()
    now_ts = time.time() if now is None else now
    reclaimed = 0

    for inflight in list_inflight_envelopes():
        env = load_envelope(inflight)
        if env is None:
            try:
                inflight.unlink()
            except OSError:
                pass
            continue

        if (now_ts - env.updated_at) < lease_seconds:
            continue

        env.updated_at = now_ts
        env.next_attempt_at = 0.0
        try:
            _atomic_write_json(inflight, env.to_dict())
        except OSError:
            continue

        target = _new_dir() / inflight.name
        try:
            inflight.replace(target)
        except OSError:
            continue
        reclaimed += 1

    return reclaimed
