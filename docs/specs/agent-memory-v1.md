# Agent Memory System — v1 Specification

## Overview

Persistent memory for Zeus agents. Agents accumulate knowledge across sessions —
preferences, decisions, gotchas, patterns — stored in SQLite with FTS5 search.
Memories are scoped by namespace type (global, project, topic) and automatically
injected into the system prompt on each LLM turn.

## 1. Namespace Types

| Prefix | Meaning | Example | Created by |
|---|---|---|---|
| `global` | Universal preferences, cross-cutting knowledge | `global` | Agent (hot path) |
| `project:<name>` | Per-git-repo knowledge | `project:zeus`, `project:barlovento-main` | Auto-derived from `git rev-parse --show-toplevel` |
| `topic:<name>` | Specialized knowledge areas | `topic:zk-proofs`, `topic:rust-async` | Only via consolidation (promoted from `new:`) |
| `new:<name>` | Staging — awaiting consolidation | `new:zk-proofs` | Agent (hot path) |

Rules:
- `topic:` namespaces are never created directly by agents. Agents write to
  `new:<name>`, consolidation promotes to `topic:<name>`.
- Project names are derived from git repo root: `git rev-parse --show-toplevel`,
  strip `~/code/` prefix, replace `/` with `-`. Example: `~/code/barlovento/main`
  → `barlovento-main`.
- `global` is a singleton namespace.

## 2. Schema

```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    tags TEXT DEFAULT '',
    source_agent TEXT DEFAULT '',
    source_project TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    accessed_at TEXT,
    access_count INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,
    UNIQUE(namespace, key)
);

CREATE TABLE topic_links (
    project TEXT NOT NULL,
    topic TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project, topic)
);

CREATE INDEX idx_memories_ns ON memories(namespace);
CREATE INDEX idx_memories_ns_archived ON memories(namespace, archived);
CREATE INDEX idx_memories_source_project ON memories(source_project);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    namespace, key, content, tags,
    content=memories,
    content_rowid=id
);
```

## 3. Extension Tools

All tools are registered in `pi_extensions/zeus.ts` via `pi.registerTool()`.
All execute via `pi.exec("sqlite3", ...)` — no native dependencies.

| Tool | Args | Behavior |
|---|---|---|
| `zeus_memory_save` | `namespace, key, content, tags?` | Upsert. Validates namespace: must be `global`, `project:*`, or `new:*`. Rejects direct `topic:*` writes. Auto-fills `source_agent`, `source_project`. When saving to `new:*`, auto-creates entry in `topic_links` for the current project. |
| `zeus_memory_recall` | `namespace, key` | Exact key lookup. Bumps `access_count` and `accessed_at`. |
| `zeus_memory_search` | `query, namespace?, limit?` | FTS5 `bm25()` ranked search. If namespace omitted, searches `global` + current project + all linked topics. Default limit 10. |
| `zeus_memory_list` | `namespace?, limit?` | Browse. If namespace omitted, lists current project. Returns key + first 200 chars of content. |
| `zeus_memory_delete` | `namespace, key` | Hard delete. |
| `zeus_memory_list_topics` | (none) | Returns all `topic:*` names linked to the current project, plus count of `new:*` memories pending consolidation. |
| `zeus_consolidation_done` | (none) | Writes completion marker `~/.zeus/ephemeral-done/<agent_id>`. Only used by ephemeral consolidation agents. |

## 4. Insertion

### Hot path — agent inline (zero extra LLM cost)

Agent calls `zeus_memory_save` as part of normal tool use. The system prompt
instructs when to save:

- `global`: user corrections about coding style, general preferences
- `project:<name>`: architecture decisions, conventions, dependency gotchas,
  project-specific patterns. Agent doesn't need to know the project name — the
  extension resolves it from cwd.
- `new:<name>`: specialized knowledge that applies beyond the current project
  (e.g., `new:zk-proofs`, `new:rust-async`). Gets staged for consolidation.

When saving to `new:<name>`, the extension:
1. Auto-fills `source_project` from the current git repo
2. Auto-creates `topic_links(project, name)` if it doesn't exist yet

### Warm path — heuristic triggers (zero LLM cost)

Two detectors in extension hooks:

**A) Correction detector (`before_agent_start`):**

Extension maintains a flag tracking whether the previous turn involved tool
calls (set in `turn_end`). On `before_agent_start`:

1. Check: was the previous turn a tool-calling turn?
2. Check: does `event.prompt` match correction indicators?
   - Starts with: `"no,"` `"no."` `"wrong"` `"actually,"` `"actually "`
   - Contains: `"don't "`, `"instead of"`, `"not like that"`, `"I said"`,
     `"I meant"`, `"should be ... not"`
   - Short message (< 300 chars) after an edit/write tool call
3. If both match, save to `project:<name>`:
   - Key: `correction:<timestamp>`
   - Tags: `correction,pending`
   - Content: user's message verbatim

**B) Failed-action detector (`turn_end`):**

On `turn_end`, scan `event.toolResults` in sequence:

1. Find any `edit` or `write` tool result
2. Check if a subsequent `bash` result in the same turn has `isError: true`
3. If yes, extract file path from edit input, error text (first 200 chars)
   from bash result
4. Save to `project:<name>`:
   - Key: `mistake:<file-path-hash>:<timestamp>`
   - Tags: `mistake,automated`
   - Content: `"Edit to <path> failed: <error excerpt>"`

### Cold path — consolidation via ephemeral Hippeus

Triggered from dashboard via `Ctrl+Alt+M`. Opens a dialog with:

- **Model dropdown** (top): populated from cached available-models list,
  preselects last-used invoke model
- **Topic dropdown**: lists all `topic:*` namespaces + `global`
- **"Consolidate Topic" button**: consolidates the selected topic/global
- **"Consolidate Project" button**: consolidates the selected agent's project

On press:
1. Zeus spawns an ephemeral Hippeus (same cwd as selected agent, chosen model)
2. Tags it as ephemeral: writes `~/.zeus/ephemeral/<agent_id>`
3. Sends the consolidation message as its initial task
4. Hippeus does the work, reports results
5. Hippeus calls `zeus_consolidation_done` → writes `~/.zeus/ephemeral-done/<agent_id>`
6. Dashboard poll cycle detects done marker → kills the agent, cleans up markers

**Safety net:** If an ephemeral agent has been alive > 30 minutes without a
done marker, dashboard shows an acknowledge-required warning modal. User
can kill or let it continue.

#### Project consolidation message

```
You are a memory consolidation agent. Consolidate memories for project
"<project_name>". Steps:

1. Use zeus_memory_list to find all memories in new:* namespaces where
   source_project is "<project_name>".
2. For each new:* topic:
   a. Check if a topic:* with the same or similar name exists
      (use zeus_memory_list_topics).
   b. If yes: merge the new:* memories into the existing topic:*
      (save to topic:*, delete from new:*).
   c. If no: promote new:* to topic:* by saving all memories with the
      topic:* namespace and deleting the new:* entries.
   d. Ensure topic_links is updated.
3. Use zeus_memory_list for project:<project_name>. Deduplicate near-identical
   memories. Remove older entries when a newer one clearly overrides them.
4. Report what you did.
5. Call zeus_consolidation_done when finished.
```

#### Topic/global consolidation message

```
You are a memory consolidation agent. Consolidate memories in "<namespace>".
Steps:

1. Use zeus_memory_list to see all memories in this namespace.
2. Identify near-duplicate memories. Merge into one, keeping the most
   complete version. Delete the redundant entries.
3. Identify contradictions where a newer memory overrides an older one.
   For clear overrides (same subject, newer timestamp): delete the old entry.
   For ambiguous conflicts: list both and ask which to keep. Do NOT call
   zeus_consolidation_done until all conflicts are resolved.
4. Report what you did and list any conflicts that need input.
5. Call zeus_consolidation_done when all work is complete.
```

## 5. Extraction (Recall)

### Automatic injection (`before_agent_start`, every prompt)

On each user prompt, the Zeus extension:

1. Resolves current project: `pi.exec("git", ["rev-parse", "--show-toplevel"])`
   → strip `~/code/`, replace `/` with `-`
2. Queries `topic_links` for topics linked to this project
3. Loads memories (excluding `archived = 1`):
   - `global`: all, up to 2K tokens
   - `project:<name>`: all, up to 3K tokens
   - Each linked `topic:*`: up to 1K per topic, max 4K total
4. FTS5 search across all above namespaces using `event.prompt` as query,
   ranked by `bm25()`, limit 10 results
5. Deduplicates: skips any `(namespace, key)` already loaded in steps 3
6. Formats into text block, appends to `event.systemPrompt`
7. Returns `{ systemPrompt: event.systemPrompt + memoryBlock }`

Total budget: **10K tokens**.

Section budgets: global 2K, project 3K, linked topics 4K (1K each), FTS
results fill remaining budget.

### Injected block format

```
[Agent Memory]
Project: zeus | Linked topics: zk-proofs, rust-async | Pending: 2 new topics

[global]
- user:preferences: Prefers early returns, conventional commits, no ternaries...
- user:review-style: Focus on logic and security, don't nitpick formatting...

[project:zeus]
- convention:error-handling: All dashboard errors use modal notice, not toast...
- decision:tmux-ownership: ID-only matching, no cwd heuristics...
- correction:1708901234: "don't use unwrap in non-test code"...

[topic:zk-proofs]
- gotcha:circuit-size: R1CS constraint count grows quadratically with...

[Relevant to this prompt]
- project:zeus/mistake:config-parse: Tried serde flatten, failed because...
- topic:rust-async/pattern:cancellation: Always use select! with...
```

### On-demand (tools)

Agent calls `zeus_memory_search` or `zeus_memory_recall` when auto-injected
context isn't sufficient. The system prompt tells the agent these tools exist
and when to use them.

### FTS5 query mechanics

The `[Relevant to this prompt]` block is built by:

```sql
SELECT namespace, key, content, bm25(memories_fts) AS rank
FROM memories_fts
WHERE memories_fts MATCH ?
  AND namespace IN ('global', 'project:zeus', 'topic:zk-proofs', 'topic:rust-async')
  AND archived = 0
ORDER BY rank
LIMIT 10;
```

The MATCH parameter is the user's prompt text. FTS5 tokenizes it and scores
with BM25 (TF-IDF based). Common words score low, domain terms score high.

**Limitation:** FTS5 is keyword-based, not semantic. "connection pooling issues"
won't match "database socket exhaustion." Mitigated by instructing agents to
use descriptive keys and content. Qdrant can be added in a future phase for
semantic search.

## 6. Context Assembly in Pi

### Startup (once, or on tool change / /reload)

```
_baseSystemPrompt = buildSystemPrompt({
  1. Base Pi prompt (tools, guidelines, docs)
  2. + APPEND_SYSTEM.md (Zeus: security, messaging, tmux, memory instructions)
  3. + Project Context (AGENTS.md chain from ~/.pi/agent/ to cwd)
  4. + Skills
  5. + Date/time + cwd
})
```

### Each user prompt

```
messages = [...conversation_history, user_message, pending_nextTurn_messages]

for each extension:
  before_agent_start(event):
    event.prompt = user's text
    event.systemPrompt = _baseSystemPrompt (or previous extension's output)

    ┌─── Zeus extension ──────────────────────────────────────┐
    │ 1. Query SQLite for global memories                     │
    │ 2. Query SQLite for project memories (git-repo derived) │
    │ 3. Query topic_links → load linked topic memories       │
    │ 4. FTS5 search against event.prompt                     │
    │ 5. Format memory block (10K token budget)               │
    │ 6. return {                                             │
    │      systemPrompt: event.systemPrompt + memoryBlock     │
    │    }                                                    │
    └─────────────────────────────────────────────────────────┘

agent.setSystemPrompt(modified systemPrompt)
agent.prompt(messages)
  → LLM sees: systemPrompt (with memories) + messages

After prompt completes:
  agent.setSystemPrompt(_baseSystemPrompt)   ← RESET
```

Key properties:
- Memory injection is per-turn, not persistent. Pi resets the system prompt
  after each prompt. Fresh memories are loaded every turn.
- Custom messages injected via `message` return would persist in the session
  and get compacted. System prompt append avoids this — memories are ephemeral
  context, not conversation content.
- Multiple extensions chain: each `before_agent_start` handler sees the
  previous handler's `systemPrompt` output.

## 7. System Prompt (APPEND_SYSTEM.md addition)

```
Agent memory
- You have persistent memory across sessions via zeus_memory_* tools.
- Namespace types: `global` (universal), `project:<name>` (per-git-repo),
  `new:<name>` (specialized knowledge, staged for consolidation).
- Your project name is auto-derived from your git repo root.
- `topic:<name>` namespaces are read-only — write to `new:<name>` instead.
  Consolidation promotes new topics to topic namespaces.
- **When to save** (call `zeus_memory_save`):
  - User corrections ("don't do X, do Y instead")
  - Architecture/design decisions
  - Non-obvious gotchas or dependency quirks
  - Coding style preferences (global)
  - Specialized knowledge beyond this project (new:<topic-name>)
- **When to search** (call `zeus_memory_search`):
  - Starting a new task: search for relevant project context
  - Encountering unfamiliar code/patterns: check for past learnings
  - Before making architecture decisions: check for prior decisions
- Relevant memories are auto-injected at the start of each prompt.
  Use the search tool when you need deeper context.
- Keep content concise — store what you learned, not raw observations.
- Use descriptive keys: `convention:error-handling`, `gotcha:sqlx-pooling`,
  `decision:auth-strategy`.
- Use descriptive content with specific terms — recall is keyword-based.
```

## 8. Implementation Phases

### Phase 1: Storage + tools
- [ ] Create `zeus/memory.py` module: SQLite schema creation, query helpers
- [ ] Register memory tools in `pi_extensions/zeus.ts`: save, recall, search,
      list, delete, list_topics, consolidation_done
- [ ] DB initialization on first tool use (lazy)
- [ ] Project name resolution via `git rev-parse --show-toplevel`
- [ ] Namespace validation in save (reject direct `topic:*` writes)
- [ ] Auto-create `topic_links` on `new:*` saves
- [ ] Tests for all memory operations

### Phase 2: Automatic injection
- [ ] `before_agent_start` hook: query memories, build text block, append
      to system prompt
- [ ] Token budget enforcement (10K total, per-section limits)
- [ ] FTS5 search against user prompt, dedup against loaded memories
- [ ] Memory block formatting
- [ ] Tests for injection logic

### Phase 3: Warm path triggers
- [ ] Correction detector in `before_agent_start`: track previous-turn
      tool usage, pattern-match user prompt
- [ ] Failed-action detector in `turn_end`: scan tool results for
      edit→bash-failure sequences
- [ ] Tests for both detectors

### Phase 4: Consolidation UI + ephemeral agents
- [ ] Dashboard dialog (`Ctrl+Alt+M`): model dropdown, topic dropdown,
      consolidate-topic button, consolidate-project button
- [ ] Ephemeral Hippeus spawning: create agent, tag as ephemeral, send
      consolidation message
- [ ] `zeus_consolidation_done` tool: write completion marker
- [ ] Dashboard poll: detect done marker, auto-kill ephemeral agent
- [ ] 30-minute safety net warning
- [ ] CSS for consolidation dialog
- [ ] Tests for dialog, ephemeral lifecycle

### Phase 5: System prompt + install
- [ ] Update APPEND_SYSTEM.md with memory instructions
- [ ] Update install.sh to initialize empty DB on install
- [ ] Update README.md with architecture diagrams
- [ ] End-to-end testing
