# Zeus Terminology Specification

## Purpose

Define canonical naming for Zeus user-facing language.

## Canonical terms

| Concept | Canonical term |
|---|---|
| Program | **Zeus** |
| Human operator | **The Oracle** |
| Worker (singular) | **Hippeus** |
| Workers (plural) | **Hippeis** |
| Worker group (singular) | **Phalanx** |
| Worker groups (plural) | **Phalanges** |
| Phalanx subordinate (singular) | **Hoplite** |
| Phalanx subordinates (plural) | **Hoplites** |
| Generic tmux viewer row | **tmux session** |
| Phalanx parent/commander role | **Polemarch** |

## Normative rules

1. User-facing UI copy, help text, notifications, CLI help text, and project docs MUST use the canonical terms above.
2. `Polemarch` denotes the currently available parent/commander role for Phalanx orchestration.
3. `Hoplite` MUST refer only to an AGENT-based subordinate initialized by a Polemarch and explicitly associated with that Polemarch's Phalanx.
4. Viewer-only tmux rows/sessions (regular tmux attach/view entries) MUST be labeled `tmux session` and MUST NOT be labeled `Hoplite` or treated as Phalanx members.
5. A `Hoplite` MUST NOT be treated as a full `Hippeus` unless explicitly promoted.
6. Zeus technical identifiers remain unchanged unless a separate migration spec explicitly says otherwise.

## Out of scope (unchanged technical contracts)

The following remain as-is:

- CLI/program/package identity: `zeus`, `zeus.*`
- Environment variables: `ZEUS_*`
- Persistent paths/keys: `/tmp/zeus-*`, `agent_id`, `@zeus_owner`
- External protocol fields/headers: JSON role `"user"`, HTTP `User-Agent`
