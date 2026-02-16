"""zeus-msg CLI: enqueue autonomous filesystem messages."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .config import MESSAGE_TMP_DIR
from .message_queue import OutboundEnvelope, enqueue_envelope, ensure_queue_dirs


def _err(message: str) -> int:
    print(f"zeus-msg: {message}", file=sys.stderr)
    return 1


def _resolve_target(
    to_spec: str,
    *,
    sender_agent_id: str,
    sender_role: str,
    sender_parent_id: str,
    sender_phalanx_id: str,
) -> tuple[str, str, str] | None:
    clean = to_spec.strip()
    if not clean:
        return None

    if clean == "polemarch":
        if not sender_parent_id:
            return None
        return ("agent", sender_parent_id, "")

    if clean == "phalanx":
        owner_id = sender_parent_id or sender_agent_id
        if not owner_id:
            return None
        phalanx_id = sender_phalanx_id or f"phalanx-{owner_id}"
        return ("phalanx", phalanx_id, owner_id)

    if clean.startswith("hoplite:"):
        hoplite_id = clean.split(":", 1)[1].strip()
        if not hoplite_id:
            return None
        owner_id = sender_parent_id or sender_agent_id
        return ("hoplite", hoplite_id, owner_id)

    if clean.startswith("agent:"):
        target_agent_id = clean.split(":", 1)[1].strip()
        if not target_agent_id:
            return None
        return ("agent", target_agent_id, "")

    # Plain id fallback.
    return ("agent", clean, "")


def _read_payload(path_text: str) -> str | None:
    if not path_text.strip():
        return None

    try:
        path = Path(os.path.expanduser(path_text)).resolve()
    except OSError:
        return None

    try:
        allowed_root = MESSAGE_TMP_DIR.resolve()
    except OSError:
        return None

    if path != allowed_root and allowed_root not in path.parents:
        return None
    if not path.is_file():
        return None

    try:
        return path.read_text()
    except OSError:
        return None


def cmd_send(args: argparse.Namespace) -> int:
    payload = _read_payload(args.file)
    if payload is None:
        return _err(
            f"invalid --file path (must be readable under {MESSAGE_TMP_DIR})"
        )

    sender_agent_id = os.environ.get("ZEUS_AGENT_ID", "").strip()
    sender_role = os.environ.get("ZEUS_ROLE", "").strip().lower()
    sender_parent_id = os.environ.get("ZEUS_PARENT_ID", "").strip()
    sender_phalanx_id = os.environ.get("ZEUS_PHALANX_ID", "").strip()

    if not sender_agent_id:
        return _err("ZEUS_AGENT_ID is required")

    resolved = _resolve_target(
        args.to,
        sender_agent_id=sender_agent_id,
        sender_role=sender_role,
        sender_parent_id=sender_parent_id,
        sender_phalanx_id=sender_phalanx_id,
    )
    if resolved is None:
        return _err(f"cannot resolve --to target: {args.to!r}")

    target_kind, target_ref, target_owner_id = resolved
    source_name = os.environ.get("AGENTMON_NAME", "").strip() or sender_agent_id

    envelope = OutboundEnvelope.new(
        source_name=source_name,
        source_agent_id=sender_agent_id,
        source_role=sender_role,
        source_parent_id=sender_parent_id,
        source_phalanx_id=sender_phalanx_id,
        target_kind=target_kind,
        target_ref=target_ref,
        target_owner_id=target_owner_id,
        target_agent_id=target_ref if target_kind == "agent" else "",
        target_name="",
        message=payload,
    )

    ensure_queue_dirs()
    enqueue_envelope(envelope)
    print(f"ZEUS_MSG_ENQUEUED={envelope.id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="zeus-msg",
        description="Queue autonomous Polemarch/Hoplite messages for Zeus delivery",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="Queue one outbound message from file")
    p_send.add_argument("--to", required=True, help="polemarch | phalanx | hoplite:<id> | agent:<id> | <agent-id>")
    p_send.add_argument("--file", required=True, help="Payload file path (must be under message_tmp_dir)")
    p_send.set_defaults(func=cmd_send)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
