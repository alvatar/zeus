"""zeus-msg CLI: enqueue autonomous filesystem messages."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import time

from .config import MESSAGE_TMP_DIR
from .kitty import discover_agents
from .message_queue import OutboundEnvelope, enqueue_envelope, ensure_queue_dirs


_AGENT_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


def _err(message: str) -> int:
    print(f"zeus-msg: {message}", file=sys.stderr)
    return 1


def _resolve_agent_target(value: str) -> tuple[str, str, str]:
    """Resolve plain/agent-prefixed target to a concrete agent id.

    Supports either:
    - ZEUS_AGENT_ID values (32-char hex), or
    - exact active display names (unique among active agents).
    """
    clean = value.strip()
    if not clean:
        raise ValueError("missing agent target")

    try:
        agents = discover_agents()
    except Exception:
        agents = []

    id_matches = [
        a for a in agents if (a.agent_id or "").strip() == clean
    ]
    if id_matches:
        return ("agent", clean, "")

    name_matches = [a for a in agents if a.name.strip() == clean]
    if len(name_matches) == 1:
        target_agent_id = (name_matches[0].agent_id or "").strip()
        if not target_agent_id:
            raise ValueError(
                f"matched agent {clean!r} has no ZEUS_AGENT_ID"
            )
        return ("agent", target_agent_id, "")

    if len(name_matches) > 1:
        ids = sorted(
            {
                (a.agent_id or "<missing>").strip() or "<missing>"
                for a in name_matches
            }
        )
        raise ValueError(
            "ambiguous agent name "
            f"{clean!r}; use agent:<ZEUS_AGENT_ID> (matches: {', '.join(ids)})"
        )

    if _AGENT_ID_RE.fullmatch(clean):
        return ("agent", clean, "")

    raise ValueError(
        f"cannot resolve --to target {clean!r}; use agent:<ZEUS_AGENT_ID> "
        "or an exact active agent name"
    )


def _resolve_target(
    to_spec: str,
    *,
    sender_agent_id: str,
    sender_role: str,
    sender_parent_id: str,
    sender_phalanx_id: str,
) -> tuple[str, str, str]:
    clean = to_spec.strip()
    if not clean:
        raise ValueError("empty --to target")

    if clean == "polemarch":
        if not sender_parent_id:
            raise ValueError("cannot resolve --to polemarch without ZEUS_PARENT_ID")
        return ("agent", sender_parent_id, "")

    if clean == "phalanx":
        owner_id = sender_parent_id or sender_agent_id
        if not owner_id:
            raise ValueError("cannot resolve --to phalanx without sender id")
        phalanx_id = sender_phalanx_id or f"phalanx-{owner_id}"
        return ("phalanx", phalanx_id, owner_id)

    if clean.startswith("hoplite:"):
        hoplite_id = clean.split(":", 1)[1].strip()
        if not hoplite_id:
            raise ValueError("missing hoplite id after hoplite:")
        owner_id = sender_parent_id or sender_agent_id
        return ("hoplite", hoplite_id, owner_id)

    if clean.startswith("agent:"):
        target = clean.split(":", 1)[1].strip()
        return _resolve_agent_target(target)

    if clean.startswith("name:"):
        target_name = clean.split(":", 1)[1].strip()
        return _resolve_agent_target(target_name)

    # Plain id/name fallback with strict resolution.
    return _resolve_agent_target(clean)


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


def _payload_from_args(args: argparse.Namespace) -> tuple[str | None, str | None]:
    file_arg = getattr(args, "file", None)
    text_arg = getattr(args, "text", None)
    stdin_arg = bool(getattr(args, "stdin", False))

    sources = 0
    if file_arg:
        sources += 1
    if text_arg is not None:
        sources += 1
    if stdin_arg:
        sources += 1

    if sources > 1:
        return None, "choose exactly one payload source: --file, --text, or --stdin"

    if file_arg:
        payload = _read_payload(str(file_arg))
        if payload is None:
            return None, (
                f"invalid --file path (must be readable under {MESSAGE_TMP_DIR})"
            )
        return payload, None

    if text_arg is not None:
        return str(text_arg), None

    if stdin_arg:
        return sys.stdin.read(), None

    if not sys.stdin.isatty():
        return sys.stdin.read(), None

    return None, "missing payload: provide --file, --text, --stdin, or pipe stdin"


def _wait_for_delivery(enqueue_path: Path, timeout_s: float) -> bool:
    """Wait until Zeus acks delivery by removing queue envelope file."""
    queue_root = enqueue_path.parent.parent
    inflight_path = queue_root / "inflight" / enqueue_path.name

    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() <= deadline:
        if not enqueue_path.exists() and not inflight_path.exists():
            return True
        time.sleep(0.1)

    return not enqueue_path.exists() and not inflight_path.exists()


def cmd_send(args: argparse.Namespace) -> int:
    payload, payload_err = _payload_from_args(args)
    if payload is None:
        return _err(payload_err or "invalid payload")
    if payload == "":
        return _err("payload is empty")

    sender_agent_id = os.environ.get("ZEUS_AGENT_ID", "").strip()
    sender_role = os.environ.get("ZEUS_ROLE", "").strip().lower()
    sender_parent_id = os.environ.get("ZEUS_PARENT_ID", "").strip()
    sender_phalanx_id = os.environ.get("ZEUS_PHALANX_ID", "").strip()

    if not sender_agent_id:
        return _err("ZEUS_AGENT_ID is required")

    try:
        target_kind, target_ref, target_owner_id = _resolve_target(
            args.to,
            sender_agent_id=sender_agent_id,
            sender_role=sender_role,
            sender_parent_id=sender_parent_id,
            sender_phalanx_id=sender_phalanx_id,
        )
    except ValueError as error:
        return _err(str(error))
    from_sender = getattr(args, "from_sender", None)
    if from_sender is not None:
        source_name = str(from_sender).strip()
        if not source_name:
            return _err("--from cannot be empty")
    else:
        source_name = os.environ.get("ZEUS_AGENT_NAME", "").strip() or sender_agent_id

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
    enqueue_path = enqueue_envelope(envelope)
    print(f"ZEUS_MSG_ENQUEUED={envelope.id}")

    if bool(getattr(args, "wait_delivery", False)):
        timeout_s = float(getattr(args, "timeout", 30.0))
        if _wait_for_delivery(enqueue_path, timeout_s):
            print(f"ZEUS_MSG_DELIVERED={envelope.id}")
            return 0
        return _err(
            f"delivery timeout after {timeout_s:.1f}s; message remains queued"
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="zeus-msg",
        description="Queue autonomous Polemarch/Hoplite messages for Zeus delivery",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="Queue one outbound message")
    p_send.add_argument(
        "--to",
        required=True,
        help=(
            "polemarch | phalanx | hoplite:<id> | "
            "agent:<id-or-name> | name:<display-name> | <id-or-name>"
        ),
    )
    p_send.add_argument(
        "--from",
        dest="from_sender",
        help="Override sender display name for source_name",
    )
    p_send.add_argument(
        "--file",
        help="Payload file path (must be under message_tmp_dir)",
    )
    p_send.add_argument(
        "--text",
        help="Inline payload text",
    )
    p_send.add_argument(
        "--stdin",
        action="store_true",
        help="Read payload from stdin",
    )
    p_send.add_argument(
        "--wait-delivery",
        action="store_true",
        help="Block until Zeus transport-acks delivery",
    )
    p_send.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Delivery wait timeout in seconds (used with --wait-delivery)",
    )
    p_send.set_defaults(func=cmd_send)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
