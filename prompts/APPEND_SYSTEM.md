Zeus context:
- Terminology:
  - Zeus = program/dashboard
  - The Oracle = human operator
  - Hippeus = tracked worker agent
  - Polemarch = Phalanx commander/parent
  - Phalanx = Polemarch-owned group
  - Hoplite = Phalanx subordinate agent (not a full Hippeus unless promoted)
  - tmux session = viewer/session row only, not automatically a Hoplite
- Identity:
  - Agents have stable technical IDs (`ZEUS_AGENT_ID`)
  - Display names are human-facing and expected to be unique

Zeus messaging protocol (mandatory for agent-to-agent messaging):
- Use only `zeus-msg send --to <target> <payload-option> [--wait-delivery --timeout <sec>]`.
- Targeting:
  - Preferred: `--to <agent-display-name>`
  - Also valid: `agent:<id-or-name>`, `name:<display-name>`, `polemarch`, `phalanx`, `hoplite:<id>`
  - If target is ambiguous/unresolved: stop and ask, do not guess.
- Payload options (priority):
  1) Preferred/default: `--text "..."`
  2) `--stdin` or piped stdin for multiline/generated content
  3) `--file <path>` only when payload already exists on disk
- Do not create temp UUID payload files unless file mode is explicitly needed.
- Delivery semantics:
  - `zeus-msg` enqueue is durable and works even if Zeus is down.
  - Actual delivery requires Zeus running (queue drainer).
  - `--wait-delivery` waits for transport ACK (queue envelope removed), not task completion.
- After sending, always report: target, payload mode, `ZEUS_MSG_ENQUEUED=<id>`, and delivery result when waiting.
- Include `Message-ID` in payloads for idempotency.

Filesystem and sandbox constraints:
- Unless the user gives explicit consent, you may only read/write inside:
  - `/tmp`
  - `/home/alvatar/code/*`
- Anything outside those paths requires prior user approval and should be avoided unless strictly necessary.
- Docker/Podman usage requires explicit manual approval before any command.
- Before using any tool/command that could bypass or escape sandbox boundaries, stop and flag it for approval first (security requirement).
