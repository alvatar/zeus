"""Tests for zeus-msg autonomous send CLI."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import zeus.message_queue as mq
import zeus.msg_cli as msg_cli


def _prepare(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    msg_root = tmp_path / "msg"
    queue_root = tmp_path / "queue"
    msg_root.mkdir(parents=True)
    queue_root.mkdir(parents=True)

    monkeypatch.setattr(msg_cli, "MESSAGE_TMP_DIR", msg_root)
    monkeypatch.setattr(mq, "MESSAGE_QUEUE_DIR", queue_root)
    return msg_root, queue_root


def _single_envelope(queue_root: Path) -> mq.OutboundEnvelope:
    files = sorted((queue_root / "new").glob("*.json"))
    assert len(files) == 1
    env = mq.load_envelope(files[0])
    assert env is not None
    return env


def test_msg_cli_send_polemarch_resolves_parent(monkeypatch, tmp_path: Path) -> None:
    msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    payload = msg_root / "m.md"
    payload.write_text("hello\n")

    monkeypatch.setenv("ZEUS_AGENT_ID", "hoplite-1")
    monkeypatch.setenv("ZEUS_PARENT_ID", "polemarch-1")
    monkeypatch.setenv("ZEUS_PHALANX_ID", "phalanx-polemarch-1")
    monkeypatch.setenv("ZEUS_ROLE", "hoplite")
    monkeypatch.setenv("AGENTMON_NAME", "hoplite-a")

    rc = msg_cli.cmd_send(Namespace(to="polemarch", file=str(payload)))
    assert rc == 0

    env = _single_envelope(queue_root)
    assert env.target_kind == "agent"
    assert env.target_ref == "polemarch-1"
    assert env.target_agent_id == "polemarch-1"
    assert env.source_agent_id == "hoplite-1"
    assert env.message == "hello\n"


def test_msg_cli_send_phalanx_from_polemarch_uses_owner_fallback(monkeypatch, tmp_path: Path) -> None:
    msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    payload = msg_root / "m.md"
    payload.write_text("status\n")

    monkeypatch.setenv("ZEUS_AGENT_ID", "polemarch-1")
    monkeypatch.delenv("ZEUS_PARENT_ID", raising=False)
    monkeypatch.delenv("ZEUS_PHALANX_ID", raising=False)
    monkeypatch.setenv("ZEUS_ROLE", "polemarch")

    rc = msg_cli.cmd_send(Namespace(to="phalanx", file=str(payload)))
    assert rc == 0

    env = _single_envelope(queue_root)
    assert env.target_kind == "phalanx"
    assert env.target_ref == "phalanx-polemarch-1"
    assert env.target_owner_id == "polemarch-1"


def test_msg_cli_send_rejects_payload_outside_message_tmp_dir(monkeypatch, tmp_path: Path) -> None:
    msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("nope\n")

    monkeypatch.setenv("ZEUS_AGENT_ID", "agent-1")

    rc = msg_cli.cmd_send(Namespace(to="agent:agent-2", file=str(outside)))
    assert rc == 1

    files = sorted((queue_root / "new").glob("*.json"))
    assert files == []
