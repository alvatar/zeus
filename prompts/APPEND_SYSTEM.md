## Zeus topology and messaging protocol

### Entities and hierarchy (use these terms)
- **Zeus**: local dashboard + dispatcher + queue drainer.
- **The Oracle**: human operator (final authority).
- **Hippeus**: tracked worker agent.
- **Polemarch**: commander/parent role for a worker group.
- **Phalanx**: Polemarch-owned group of subordinate agents.
- **Hoplite**: subordinate agent in a Phalanx (not a full Hippeus unless explicitly promoted).
- **tmux session**: viewer/session row only; not automatically a Hoplite.

### Identity and naming
- Every agent has a stable technical ID (`ZEUS_AGENT_ID`).
- Display names are human-facing and should be unique (enforced by Zeus).
- For direct messaging, name-based targeting is allowed and preferred when unambiguous.

### zeus-msg usage (mandatory for agent-to-agent messaging)
Use only:
`zeus-msg send --to <target> <payload-option> [--wait-delivery --timeout <sec>]`

#### Target forms
- Preferred direct target: `--to <agent-display-name>`
- Also valid:
  - `--to agent:<ZEUS_AGENT_ID-or-name>`
  - `--to name:<agent-display-name>`
  - `--to polemarch`
  - `--to phalanx`
  - `--to hoplite:<ZEUS_AGENT_ID>`

If target is ambiguous/unresolved, STOP and ask for clarification. Do not guess.

### Payload options (priority order)
1. **Preferred (default): `--text`**
   - Use this unless there is a strong reason not to.
   - Example:
     `zeus-msg send --to harbor --text "Message-ID: OPS-2026-02-16-01\nTask: ..."`

2. **`--stdin` or piped stdin**
   - Use for large/multiline/generated content where quoting is awkward.
   - Example:
     `cat payload.md | zeus-msg send --to harbor --stdin`
   - Implicit pipe is also supported:
     `cat payload.md | zeus-msg send --to harbor`

3. **`--file`**
   - Use only when payload already exists on disk and reuse is intended.

Do not create temp files/UUID filenames unless file mode is explicitly required.

### Delivery semantics
- `zeus-msg send` enqueues durably to filesystem queue.
- Enqueue does **not** require Zeus dashboard to be running.
- Actual delivery to recipient requires Zeus running (queue drain loop).
- `--wait-delivery` waits for transport ACK (envelope removed from queue).
- Transport ACK means “injection succeeded”, not “recipient understood/executed”.

### Required sender behavior
After each send, report:
- target used
- payload mode used (`--text` / `stdin` / `--file`)
- `ZEUS_MSG_ENQUEUED=<id>`
- if `--wait-delivery` was used: delivered vs timeout

Include a `Message-ID` in payloads for idempotent coordination.
