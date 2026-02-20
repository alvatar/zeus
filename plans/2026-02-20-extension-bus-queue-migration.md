# Plan: Queue-Scoped Migration to Extension Bus (Robust Messaging)

**Status:** LOCKED
**Date:** 2026-02-20
**Author:** Zeus assistant (spec-writer) | Mode: interactive
**Complexity:** complex
**Authority:** approval
**Tier:** 3

## Problem
Queue-based communication is still mixed between extension/inbox handoff and terminal keystroke transport. ACK remains handoff-level, not extension-acceptance-level. This causes inconsistent semantics and leaves parts of delivery dependent on terminal/editor state.

## Goal
Migrate **queue routes only** (`zeus-msg`, broadcast, direct queue flows) to robust extension-backed delivery with:
- capability-gated recipient routing,
- deterministic agent-id targeting,
- extension acceptance receipts,
- queue ACK only after acceptance receipts.

## Non-Goals
- Do not migrate interact panel (`Ctrl+s`/`Ctrl+w`) direct editor send paths in this phase.
- Do not change non-queue UX behavior outside delivery semantics.
- Do not redesign orchestration (dependency graph, priorities, Aegis behavior).

## Autonomous Decisions
- None (all key tradeoffs were Oracle-selected):
  - Scope: **A** (queue routes only)
  - ACK: **B** (extension acceptance receipt)
  - Capability gating: **B** (heartbeat)
  - Idempotency: **B** (durable processed IDs + atomic claim)

## Requirements

### Must Have
- [ ] Introduce a queue-delivery bus contract for agent inbox, receipts, and capabilities under `STATE_DIR`.
- [ ] Queue targets (`agent`, `hoplite`, `phalanx`) must resolve to deterministic agent IDs for bus delivery.
- [ ] Remove queue-route dependence on keystroke injection for deliverable recipients.
- [ ] Implement extension-side atomic claim + durable processed-id dedupe before submit.
- [ ] Implement extension-side accepted receipt write keyed by `message_id`.
- [ ] Queue envelope ACK must occur only after all recipient accepted receipts are observed.
- [ ] Missing capability / missing deterministic identity must force-visible notify and keep envelope queued with backoff.
- [ ] Keep at-least-once semantics with idempotency and dedupe preserved.

### Should Have
- [ ] Add explicit stale-capability timeout policy and cover it in tests.
- [ ] Add concise operator-facing diagnostics for blocked queue deliveries.
- [ ] Keep legacy fallback behavior only where recipient identity is fundamentally non-restorable, and mark as blocked (not silent fallback transport).

### Could Have
- [ ] Add a small runbook section for inspecting inbox/receipt/capability files during incidents.

## Implementation Plan

- [ ] **Task 1:** Define bus interface + update delivery documentation
      - Files: `docs/interfaces/agent-bus-v1.md` (create), `docs/guides/filesystem-messaging.md` (modify)
      - Validation: `rg -n "accepted receipt|capability|inbox|queue ACK" docs/interfaces/agent-bus-v1.md docs/guides/filesystem-messaging.md`
      - Notes: Document file schemas, lifecycles, ack semantics, and retry behavior.

- [ ] **Task 2:** Add core bus storage primitives
      - Files: `zeus/config.py` (modify), `zeus/agent_bus.py` (create), `tests/test_agent_bus.py` (create)
      - Validation: `python3 -m pytest tests/test_agent_bus.py -q`
      - Notes: Atomic write/read helpers for inbox entries, capability heartbeat read, receipt read helpers.

- [ ] **Task 3:** Implement extension protocol for robust consumption
      - Files: `pi_extensions/zeus.ts` (modify)
      - Validation: `rg -n "capability|heartbeat|processed|receipts|followUp|rename" pi_extensions/zeus.ts`
      - Notes:
        - Claim: `new/ -> processing/` atomically
        - Dedupe: durable processed-id ledger per agent
        - Submit: `pi.sendUserMessage(..., { deliverAs: "followUp" })`
        - Receipt: write `accepted` receipt file after successful submit
        - Cleanup: remove processing file only after receipt write

- [ ] **Task 4:** Migrate queue resolver/drain to bus + receipt ACK
      - Files: `zeus/dashboard/app.py` (modify), `tests/test_dashboard_message_queue_routes.py` (modify)
      - Validation: `python3 -m pytest tests/test_dashboard_message_queue_routes.py -q`
      - Notes:
        - Resolve recipients by deterministic agent IDs
        - Gate by capability heartbeat freshness
        - Deliver via bus enqueue helper
        - ACK queue envelope only when all recipient receipts observed

- [ ] **Task 5:** Failure paths and operator visibility
      - Files: `zeus/dashboard/app.py` (modify), `tests/test_dashboard_message_queue_routes.py` (modify)
      - Validation: `python3 -m pytest tests/test_dashboard_message_queue_routes.py -k "blocked or missing or stale" -q`
      - Notes: Force-visible unresolved reasons, throttle repeat notices, preserve retry/backoff.

- [ ] **Task 6:** Full project verification (tmux-observable)
      - Files: `zeus/dashboard/app.py`, `zeus/agent_bus.py`, `pi_extensions/zeus.ts`, tests/docs above
      - Validation: `tmux -L zeustest new-session -d -s tests 'cd /home/alvatar/code/zeus && ./check.sh 2>&1 | tee /tmp/test-output.log'`
      - Notes: Must report tmux session name and `/tmp/test-output.log` outcome.

## Context Files

Files the dev agent should read before starting:
- `zeus/dashboard/app.py`
- `zeus/message_queue.py`
- `zeus/message_receipts.py`
- `zeus/config.py`
- `pi_extensions/zeus.ts`
- `docs/guides/filesystem-messaging.md`
- `tests/test_dashboard_message_queue_routes.py`
- `zeus/hoplite_inbox.py`

## Autonomy Scope

### Decide yourself:
- Exact helper names and module split (`agent_bus.py` vs extending `hoplite_inbox.py`) as long as interface contract is kept.
- Receipt/capability stale timeout defaults and throttling constants.
- Test fixture structure and helper reuse.

### Escalate (log blocker, skip, continue):
- Any need to change non-queue interact send semantics (`Ctrl+s`/`Ctrl+w`).
- Any proposal to reintroduce keystroke fallback for queue recipients that have deterministic agent IDs.
- Any dependency additions or external runtime requirements.

## Verification

### Smoke Tests
- `python3 -m pytest tests/test_agent_bus.py -q` — validates bus persistence primitives.
- `python3 -m pytest tests/test_dashboard_message_queue_routes.py -q` — validates routing, blocked behavior, and queue semantics.

### Expected State
- File `docs/interfaces/agent-bus-v1.md` exists and defines message/receipt/capability schemas.
- File `zeus/agent_bus.py` exists and exposes atomic inbox + receipt/capability helpers.
- Queue ACK in `zeus/dashboard/app.py` is gated by extension accepted receipt observation.
- No queue-route delivery path for deterministic recipients depends on terminal keystrokes.

### Regression
- `tmux -L zeustest new-session -d -s tests 'cd /home/alvatar/code/zeus && ./check.sh 2>&1 | tee /tmp/test-output.log'` passes.

### Integration Test
- Bring up Zeus + one polemarch + two hoplites with extension active.
- Send phalanx payload via `zeus-msg send --to phalanx ...`.
- Confirm:
  - inbox files created per hoplite,
  - extension emits accepted receipts,
  - queue envelope removed only after receipts,
  - duplicate `message_id` does not produce duplicate injection.

## Enrichment / Lock Evidence
- Verified existing files (first 50 lines read):
  - `zeus/dashboard/app.py`
  - `zeus/config.py`
  - `zeus/message_queue.py`
  - `zeus/message_receipts.py`
  - `pi_extensions/zeus.ts`
  - `docs/guides/filesystem-messaging.md`
  - `tests/test_dashboard_message_queue_routes.py`
  - `zeus/hoplite_inbox.py`
- Verified parent directories for planned new files:
  - `docs/interfaces/`
  - `zeus/`
  - `tests/`
  - `plans/`
