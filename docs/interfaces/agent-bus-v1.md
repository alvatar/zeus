# Agent Bus v1 (Queue Delivery Contract)

Status: Interface (normative)

## Scope

Applies to Zeus delivery paths targeting deterministic agent ids:
- `zeus-msg send`
- dashboard broadcast/direct queued delivery paths
- dashboard message dialog send/queue
- dashboard interact send/queue when target is an agent row
- dashboard Aegis automated prompts
- dashboard polemarch bootstrap onboarding prompts

Does not apply to tmux-row interact transport (no deterministic agent id contract).

## Storage Roots

All paths are under `STATE_DIR` (`ZEUS_STATE_DIR`):

- `zeus-agent-bus/inbox/<agent-id>/new/*.json`
- `zeus-agent-bus/inbox/<agent-id>/processing/*.json`
- `zeus-agent-bus/receipts/<agent-id>/<message-id>.json`
- `zeus-agent-bus/caps/<agent-id>.json`
- `zeus-agent-bus/processed/<agent-id>.json`

`<agent-id>` MUST be deterministic `ZEUS_AGENT_ID` sanitized to `[A-Za-z0-9_-]`.

## Message File Schema

Inbox message (`new/*.json`):

```json
{
  "id": "<message-id>",
  "created_at": 1739999999.123,
  "source_name": "string",
  "source_agent_id": "string",
  "source_role": "string",
  "deliver_as": "followUp",
  "message": "string"
}
```

Rules:
- `id` MUST be stable per queue envelope recipient delivery attempt lineage.
- `message` MUST be non-empty after trim.
- `deliver_as` MUST be one of: `followUp` | `steer`.
- UI mapping policy:
  - send action => `steer`
  - queue action => `followUp`

## Capability File Schema

Capability heartbeat (`caps/<agent-id>.json`):

```json
{
  "agent_id": "<agent-id>",
  "role": "hippeus|polemarch|hoplite",
  "session_id": "string",
  "session_path": "string",
  "cwd": "string",
  "updated_at": 1739999999.123,
  "supports": {
    "queue_bus": true,
    "receipt_v1": true
  },
  "extension": {
    "name": "zeus",
    "version": "1"
  }
}
```

Rules:
- `updated_at` MUST be epoch seconds.
- Queue delivery is allowed only when heartbeat is fresh (configured max age).

## Receipt File Schema

Accepted receipt (`receipts/<agent-id>/<message-id>.json`):

```json
{
  "id": "<message-id>",
  "status": "accepted",
  "accepted_at": 1739999999.456,
  "agent_id": "<agent-id>",
  "session_id": "string",
  "session_path": "string"
}
```

Rules:
- Receipt is written by extension only after successful `sendUserMessage` handoff.
- Zeus queue ACK requires accepted receipts from all recipients.

## Extension Consumption Semantics

1. Atomically claim inbox file: `new/ -> processing/`.
2. Validate payload.
3. If `id` already in processed ledger, ensure receipt exists and delete processing file.
4. Submit via `sendUserMessage(..., { deliverAs })` where `deliverAs` is `followUp` or `steer` from payload.
5. Persist processed-id ledger.
6. Write accepted receipt.
7. Delete processing file.

On submit failure, file MUST be moved back to `new/` for retry.

## Zeus Queue ACK Semantics

For each recipient/message-id:
- if local dedupe receipt exists: recipient is complete
- else if accepted receipt exists in bus: record local dedupe receipt; recipient is complete
- else delivery remains pending

Queue envelope ACK occurs only when all recipients are complete.

## Failure Rules

- Missing deterministic recipient ID: MUST block delivery (no keystroke fallback for queue routes).
- Missing/stale capability heartbeat: MUST block delivery and retry with backoff.
- Missing accepted receipt after handoff: MUST keep envelope queued and retry.

## Idempotency

- Transport remains at-least-once.
- Duplicate enqueue/retry for same `message-id` MUST not cause duplicate model injection due to extension processed-id ledger.
