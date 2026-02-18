# Snapshot file format (v1)

## Status

Interface contract for Zeus snapshot save/restore payloads.

## File location

By default snapshots are written to:

- `~/.zeus/snapshots/*.json`

(Resolved through Zeus `STATE_DIR`.)

## Top-level object

```json
{
  "schema_version": 1,
  "created_at": "2026-02-18T18:40:00.000000+00:00",
  "hostname": "host-name",
  "working_agent_ids": ["agent-a", "agent-b"],
  "entry_count": 3,
  "entries": [
    { "...": "..." }
  ]
}
```

### Required fields

- `schema_version` (integer): must be `1`.
- `entries` (array): list of restorable entities.

### Optional metadata fields

- `created_at` (string, ISO datetime)
- `hostname` (string)
- `working_agent_ids` (string array)
- `entry_count` (integer)

## Entry kinds

Each item in `entries` must contain `kind` and `session_path`.

### 1) `kitty`

```json
{
  "kind": "kitty",
  "name": "agent-name",
  "agent_id": "...",
  "role": "hippeus|polemarch|...",
  "cwd": "/abs/path",
  "workspace": "DP-1:3",
  "session_path": "/abs/path/session.jsonl",
  "session_source": "runtime|env|...",
  "parent_id": "optional"
}
```

### 2) `stygian`

```json
{
  "kind": "stygian",
  "name": "shadow",
  "agent_id": "...",
  "role": "hippeus",
  "cwd": "/abs/path",
  "tmux_session": "stygian-xxxx",
  "session_path": "/abs/path/session.jsonl",
  "session_source": "tmux|env|..."
}
```

### 3) `hoplite`

```json
{
  "kind": "hoplite",
  "name": "hoplite-a",
  "agent_id": "...",
  "role": "hoplite",
  "cwd": "/abs/path",
  "tmux_session": "hoplite-xxxx",
  "session_path": "/abs/path/session.jsonl",
  "session_source": "tmux-option|runtime|start-command",
  "owner_id": "polemarch-id",
  "phalanx_id": "phalanx-polemarch-id"
}
```

## Restore policies

Restore supports two policy dimensions:

- `workspace_mode`: `original` | `current`
- `if_running`: `error` | `skip` | `replace`

Default behavior is strict:

- `workspace_mode=original`
- `if_running=error`

## Compatibility

- Unknown `schema_version` values are rejected.
- Unknown entry `kind` values are rejected.
