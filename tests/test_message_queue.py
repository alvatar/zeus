"""Tests for filesystem outbound message queue."""

from pathlib import Path
import time

import zeus.message_queue as mq


def test_enqueue_claim_ack_roundtrip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mq, "MESSAGE_QUEUE_DIR", tmp_path)

    env = mq.OutboundEnvelope.new(
        source_name="source",
        target_agent_id="agent-1",
        target_name="target",
        message="hello",
    )

    queued = mq.enqueue_envelope(env)
    assert queued.parent == tmp_path / "new"

    loaded = mq.load_envelope(queued)
    assert loaded is not None
    assert loaded.message == "hello"

    claimed = mq.claim_envelope(queued)
    assert claimed is not None
    assert claimed.parent == tmp_path / "inflight"

    mq.ack_envelope(claimed)
    assert not claimed.exists()


def test_requeue_and_reclaim_stale_inflight(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mq, "MESSAGE_QUEUE_DIR", tmp_path)

    env = mq.OutboundEnvelope.new(
        source_name="source",
        target_agent_id="agent-1",
        target_name="target",
        message="hello",
    )
    queued = mq.enqueue_envelope(env)
    claimed = mq.claim_envelope(queued)
    assert claimed is not None

    loaded = mq.load_envelope(claimed)
    assert loaded is not None
    requeued = mq.requeue_envelope(claimed, loaded, now=time.time(), delay_seconds=2)
    assert requeued is not None
    assert requeued.parent == tmp_path / "new"

    requeued_env = mq.load_envelope(requeued)
    assert requeued_env is not None
    assert requeued_env.attempts == 1
    assert requeued_env.next_attempt_at > 0

    # Move back to inflight and reclaim as stale.
    claimed_again = mq.claim_envelope(requeued)
    assert claimed_again is not None

    stale_env = mq.load_envelope(claimed_again)
    assert stale_env is not None
    stale_env.updated_at = 0.0
    # Rewrite envelope so reclaim sees stale timestamp.
    mq.requeue_envelope(claimed_again, stale_env, now=0.0, delay_seconds=0.0)
    claimed_stale = mq.claim_envelope(tmp_path / "new" / claimed_again.name)
    assert claimed_stale is not None

    reclaimed = mq.reclaim_stale_inflight(lease_seconds=1.0, now=2.0)
    assert reclaimed == 1
    assert (tmp_path / "new" / claimed_stale.name).exists()
