# Filesystem Messaging (Zeus Injector)

Status: Guide (non-normative)

## Purpose

Zeus uses a filesystem-backed outbound queue so message delivery survives Zeus restarts.

Design goals:
- no always-on broker daemon
- transport safety (remove only after injection ACK)
- eventual delivery after Zeus restarts
- `inotify` wakeups for low-latency draining

Current scope:
- cross-agent summary/direct flows (`Ctrl+b`, `Ctrl+m`) use this queue
- autonomous Polemarch/Hoplite sends via `zeus-msg send` use the same queue

## Storage and payload paths

Storage roots are configurable via `[storage]` in `~/.zeus/config.toml`:

```toml
[storage]
state_dir = "~/.zeus"
message_tmp_dir = "~/.zeus/messages"
```

Also supported via env vars:
- `ZEUS_STATE_DIR`
- `ZEUS_MESSAGE_TMP_DIR`

Behavior in current implementation:
- queue envelopes live under: `<state_dir>/zeus-message-queue/`
- payload files are expected in: `<message_tmp_dir>` (default `~/.zeus/messages`)

## Agent-side autonomous sends (`zeus-msg`)

`zeus-msg` is a one-shot local CLI that enqueues an outbound envelope from a payload file.

Examples:

```bash
# hoplite -> polemarch
zeus-msg send --to polemarch --file ~/.zeus/messages/zeus-msg-<uuid>.md

# polemarch -> all hoplites in phalanx
zeus-msg send --to phalanx --file ~/.zeus/messages/zeus-msg-<uuid>.md

# polemarch/hoplite -> one hoplite by id
zeus-msg send --to hoplite:<agent_id> --file ~/.zeus/messages/zeus-msg-<uuid>.md
```

Address resolution notes:
- sender id is `ZEUS_AGENT_ID`
- `--to polemarch` resolves via `ZEUS_PARENT_ID`
- `--to phalanx` resolves via `ZEUS_PHALANX_ID` (or `phalanx-<owner>` fallback)

## Queue layout

```
<state_dir>/zeus-message-queue/
  new/        # pending envelopes
  inflight/   # claimed envelopes currently being delivered
```

Envelope payload (JSON) includes:
- `id`
- `source_name`
- `target_agent_id`
- `target_name`
- `message`
- `created_at`
- `updated_at`
- `attempts`
- `next_attempt_at`

## Delivery state machine

1. **enqueue**: write envelope into `new/`
2. **claim**: atomically move `new/<file>` -> `inflight/<file>`
3. **inject**: Zeus sends message to target terminal with queue semantics (Alt+Enter path)
4. **ack**:
   - success -> remove envelope from `inflight/`
   - failure -> update attempts/backoff and move envelope back to `new/`

Crash recovery:
- stale `inflight/` envelopes are reclaimed back to `new/` after lease timeout
- on next Zeus run, drain resumes from disk state

## ACK semantics

ACK is **transport ACK**:
- envelope is removed when injection commands succeed
- ACK does **not** mean the receiver model understood or executed the task

This is intentional for current stage; app-level ACK can be added later.

Dedupe behavior:
- Zeus records per-recipient message receipts by envelope `id`.
- If an envelope with the same id is retried after a successful delivery,
  Zeus skips duplicate injection and ACKs it.
- Receipt entries are pruned with a TTL window.

## Wakeups and catch-up

Zeus uses two drain triggers:
- `inotifywait` watcher on `new/` (fast path)
- periodic sweep timer (fallback)

If Zeus is offline:
- envelopes remain on disk
- delivery continues automatically when Zeus comes back

## Payload extraction for B/M flows

When preparing cross-agent payloads, Zeus now prefers file pointers:

1. `ZEUS_MSG_FILE=<path>` in transcript/screen text
2. fallback to wrapped `%%%%` marker extraction

Accepted file pointers are restricted to configured `message_tmp_dir`.

Important addressing note:
- the sender does **not** need to know recipient agent IDs.
- sender only writes a payload file and prints `ZEUS_MSG_FILE=<path>`.
- recipient selection/routing is performed by Zeus from UI context (`Ctrl+b` broadcast set or `Ctrl+m` selected target).
- `<path>` can be any valid file path under `message_tmp_dir`; file name token is arbitrary (it is not an agent ID).

## Operational notes

- Required dependency: `inotifywait` (`inotify-tools` package)
- If `inotifywait` is missing, periodic sweep still delivers, but with higher latency
- Backoff is bounded exponential
- IDs/state are persisted under `state_dir` and can be kept at `/tmp` if desired
