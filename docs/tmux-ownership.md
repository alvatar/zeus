# Deterministic tmux ownership in Zeus

## Goal

Map tmux sessions to Hippeis using deterministic ids only.

## Ownership model

Zeus uses deterministic sources only, in this order:

1. `@zeus_owner` tmux session option
2. session agent id (`@zeus_agent` or `ZEUS_AGENT_ID` from pane start command or tmux env)

Heuristic matching by cwd/screen text is disabled.

## Hippeus identity

- Each tracked Hippeus has an `agent_id` (`ZEUS_AGENT_ID`).
- Zeus-launched Hippeis are started with `ZEUS_AGENT_ID` in their environment.
- Independently discovered Hippeis (heuristic pi windows) are assigned a persisted id in:
  - `~/.zeus/zeus-agent-ids.json` by default (`"socket:kitty_id" -> "agent_id"`)

## Backfill stamping

When a tmux session is matched to a Hippeus and `@zeus_owner` is missing, Zeus backfills:

```bash
tmux set-option -t <session> @zeus_owner <agent_id>
```

This is done only for deterministic-id matches (`option-agent-id`, `start-command-agent-id`, `env-agent-id`, `env-id`).

## tmux propagation

Zeus ensures tmux server config includes:

```bash
tmux set -ga update-environment ZEUS_AGENT_ID
```

This allows `ZEUS_AGENT_ID` from client environments to propagate into newly created sessions.

## Independent `pi` launches

Independent `pi` launches remain supported. They can still be discovered heuristically.

For strongest determinism from session creation time, use a wrapper around `pi` that sets `ZEUS_AGENT_ID` if missing.

Installer-managed option:

```bash
bash install.sh --wrap-pi
```

This wraps `~/.local/bin/pi`, stores original binary at `~/.local/bin/pi.zeus-orig`, and restores it on `bash uninstall.sh`.

Manual wrapper example:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [ -z "${ZEUS_AGENT_ID:-}" ]; then
  ZEUS_AGENT_ID=$(python3 - <<'PY'
import uuid
print(uuid.uuid4().hex)
PY
)
  export ZEUS_AGENT_ID
fi

exec /path/to/real/pi "$@"
```

## Notes

- Determinism is immediate when `@zeus_owner` or session `ZEUS_AGENT_ID` exists.
- Sessions without deterministic ids stay unassigned to avoid ambiguous ownership.
