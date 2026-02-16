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
| Phalanx parent/commander role (future feature) | **Polemarch** |

## Normative rules

1. User-facing UI copy, help text, notifications, CLI help text, and project docs MUST use the canonical terms above.
2. `Polemarch` is a reserved term for future functionality and MUST NOT imply currently available features.
3. `Hoplite` names a subordinate agent inside a Polemarch's Phalanx and MUST NOT be treated as a full Hippeus unless explicitly promoted.
4. Zeus technical identifiers remain unchanged unless a separate migration spec explicitly says otherwise.

## Out of scope (unchanged technical contracts)

The following remain as-is:

- CLI/program/package identity: `zeus`, `zeus.*`
- Environment variables: `ZEUS_*`, `AGENTMON_NAME`
- Persistent paths/keys: `/tmp/zeus-*`, `agent_id`, `@zeus_owner`
- External protocol fields/headers: JSON role `"user"`, HTTP `User-Agent`
