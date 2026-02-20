"""Tests for zeus-msg autonomous send CLI."""

from __future__ import annotations

from argparse import Namespace
import io
from pathlib import Path

import zeus.message_queue as mq
import zeus.msg_cli as msg_cli
from zeus.models import AgentWindow


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


def _agent(name: str, agent_id: str) -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name=name,
        pid=100,
        kitty_pid=200,
        cwd="/tmp/project",
        agent_id=agent_id,
    )


def _args(
    *,
    to: str,
    file: str | None = None,
    text: str | None = None,
    stdin: bool = False,
    wait_delivery: bool = False,
    timeout: float = 30.0,
    from_sender: str | None = None,
) -> Namespace:
    return Namespace(
        to=to,
        file=file,
        text=text,
        stdin=stdin,
        wait_delivery=wait_delivery,
        timeout=timeout,
        from_sender=from_sender,
    )


def test_msg_cli_send_polemarch_resolves_parent(monkeypatch, tmp_path: Path) -> None:
    msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    payload = msg_root / "m.md"
    payload.write_text("hello\n")

    monkeypatch.setenv("ZEUS_AGENT_ID", "hoplite-1")
    monkeypatch.setenv("ZEUS_PARENT_ID", "polemarch-1")
    monkeypatch.setenv("ZEUS_PHALANX_ID", "phalanx-polemarch-1")
    monkeypatch.setenv("ZEUS_ROLE", "hoplite")
    monkeypatch.setenv("ZEUS_AGENT_NAME", "hoplite-a")

    rc = msg_cli.cmd_send(_args(to="polemarch", file=str(payload)))
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

    rc = msg_cli.cmd_send(_args(to="phalanx", file=str(payload)))
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

    rc = msg_cli.cmd_send(_args(to="agent:agent-2", file=str(outside)))
    assert rc == 1

    files = sorted((queue_root / "new").glob("*.json"))
    assert files == []


def test_msg_cli_send_resolves_plain_display_name_to_agent_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    payload = msg_root / "m.md"
    payload.write_text("ping\n")

    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")
    monkeypatch.setattr(
        msg_cli,
        "discover_agents",
        lambda: [
            _agent("barlovento-harbor", "f4294e5363654f52aa4d3a4f2f1cf533"),
            _agent("barlovento-onchain", "7ad581163d4e4460b5cd3df67a3bcbd5"),
        ],
    )

    rc = msg_cli.cmd_send(_args(to="barlovento-harbor", file=str(payload)))
    assert rc == 0

    env = _single_envelope(queue_root)
    assert env.target_kind == "agent"
    assert env.target_ref == "f4294e5363654f52aa4d3a4f2f1cf533"
    assert env.target_agent_id == "f4294e5363654f52aa4d3a4f2f1cf533"


def test_msg_cli_send_rejects_ambiguous_display_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    payload = msg_root / "m.md"
    payload.write_text("ping\n")

    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")
    monkeypatch.setattr(
        msg_cli,
        "discover_agents",
        lambda: [
            _agent("worker", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
            _agent("worker", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
        ],
    )

    rc = msg_cli.cmd_send(_args(to="worker", file=str(payload)))
    assert rc == 1
    assert sorted((queue_root / "new").glob("*.json")) == []


def test_msg_cli_send_accepts_inline_text_payload(monkeypatch, tmp_path: Path) -> None:
    _msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")

    rc = msg_cli.cmd_send(_args(to="agent:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", text="hello"))
    assert rc == 0

    env = _single_envelope(queue_root)
    assert env.message == "hello"


def test_msg_cli_send_from_overrides_env_sender_name(monkeypatch, tmp_path: Path) -> None:
    _msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")
    monkeypatch.setenv("ZEUS_AGENT_NAME", "env-sender")

    rc = msg_cli.cmd_send(
        _args(
            to="agent:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            text="hello",
            from_sender="manual-sender",
        )
    )
    assert rc == 0

    env = _single_envelope(queue_root)
    assert env.source_name == "manual-sender"


def test_msg_cli_send_rejects_empty_from_sender(monkeypatch, tmp_path: Path) -> None:
    _msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")

    rc = msg_cli.cmd_send(
        _args(
            to="agent:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            text="hello",
            from_sender="   ",
        )
    )

    assert rc == 1
    assert sorted((queue_root / "new").glob("*.json")) == []


def test_msg_cli_send_accepts_stdin_payload(monkeypatch, tmp_path: Path) -> None:
    _msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")
    monkeypatch.setattr(msg_cli.sys, "stdin", io.StringIO("from-stdin"))

    rc = msg_cli.cmd_send(_args(to="agent:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", stdin=True))
    assert rc == 0

    env = _single_envelope(queue_root)
    assert env.message == "from-stdin"


def test_msg_cli_send_rejects_multiple_payload_sources(monkeypatch, tmp_path: Path) -> None:
    msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    payload = msg_root / "m.md"
    payload.write_text("hello\n")

    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")

    rc = msg_cli.cmd_send(
        _args(
            to="agent:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            file=str(payload),
            text="also",
        )
    )
    assert rc == 1
    assert sorted((queue_root / "new").glob("*.json")) == []


def test_msg_cli_send_accepts_implicit_piped_stdin(monkeypatch, tmp_path: Path) -> None:
    _msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")
    monkeypatch.setattr(msg_cli.sys, "stdin", io.StringIO("pipe-default"))

    rc = msg_cli.cmd_send(
        _args(
            to="agent:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            file=None,
            text=None,
            stdin=False,
        )
    )

    assert rc == 0
    env = _single_envelope(queue_root)
    assert env.message == "pipe-default"


def test_msg_cli_send_wait_delivery_timeout_keeps_message_queued(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")

    rc = msg_cli.cmd_send(
        _args(
            to="agent:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            text="wait-me",
            wait_delivery=True,
            timeout=0.01,
        )
    )

    assert rc == 1
    files = sorted((queue_root / "new").glob("*.json"))
    assert len(files) == 1


def test_msg_cli_send_wait_delivery_success(monkeypatch, tmp_path: Path, capsys) -> None:
    _msg_root, queue_root = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv("ZEUS_AGENT_ID", "sender-1")
    monkeypatch.setattr(
        msg_cli,
        "_wait_for_delivery",
        lambda _p, _t, envelope: bool(envelope.id),
    )

    rc = msg_cli.cmd_send(
        _args(
            to="agent:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            text="ok",
            wait_delivery=True,
            timeout=1.0,
        )
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "ZEUS_MSG_ENQUEUED=" in out
    assert "ZEUS_MSG_DELIVERED=" in out
    env = _single_envelope(queue_root)
    assert env.message == "ok"


def test_wait_for_delivery_accepts_agent_bus_receipt_without_queue_ack(
    monkeypatch,
    tmp_path: Path,
) -> None:
    queue_root = tmp_path / "queue"
    new_dir = queue_root / "new"
    inflight_dir = queue_root / "inflight"
    new_dir.mkdir(parents=True)
    inflight_dir.mkdir(parents=True)

    enqueue_path = new_dir / "123-msg.json"
    enqueue_path.write_text("{}")

    envelope = mq.OutboundEnvelope.new(
        source_name="sender",
        source_agent_id="sender-1",
        target_kind="agent",
        target_ref="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        target_agent_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        message="payload",
    )

    monkeypatch.setattr(msg_cli, "has_agent_bus_receipt", lambda *_args, **_kwargs: True)

    ok = msg_cli._wait_for_delivery(enqueue_path, 0.01, envelope=envelope)
    assert ok is True
