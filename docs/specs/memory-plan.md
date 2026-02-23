# Agent Memory v1 — Implementation Plan

## 1. Namespace Types

| Prefix | Meaning | Example | Created by |
|---|---|---|---|
| `global` | Universal preferences, cross-cutting | `global` | Agent (hot path) |
| `project:<name>` | Per-git-repo knowledge | `project:zeus`, `project:barlovento-main` | Auto-derived from `git rev-parse --show-toplevel`, strip `~/code/`, replace `/` with `-` |
| `topic:<name>` | Specialized knowledge areas | `topic:zk-proofs`, `topic:rust-async` | Only via consolidation (promoted from `new:`) |
| `new:<name>` | Staging — awaiting consolidation | `new:zk-proofs` | Agent (hot path) |

Rules:
- `topic:` namespaces are never created directly by agents. Agents write to
  `new:<name>`, consolidation promotes to `topic:<name>`.
- Project name derived from git repo root: `git rev-parse --show-toplevel`,
  strip `~/code/`, replace `/` with `-`.
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

All registered in `pi_extensions/zeus.ts` via `pi.registerTool()`. All
execute via `pi.exec("sqlite3", ...)`.

| Tool | Args | Behavior |
|---|---|---|
| `zeus_memory_save` | `namespace, key, content, tags?` | Upsert. Validates: must be `global`, `project:*`, or `new:*`. Rejects `topic:*`. Auto-fills `source_agent`, `source_project`. On `new:*` save, auto-creates `topic_links` entry. |
| `zeus_memory_recall` | `namespace, key` | Exact key lookup. Bumps `access_count` and `accessed_at`. |
| `zeus_memory_search` | `query, namespace?, limit?` | FTS5 `bm25()` ranked. If namespace omitted, searches `global` + current project + linked topics. Default limit 10. |
| `zeus_memory_list` | `namespace?, limit?` | Browse. If namespace omitted, lists current project. Returns key + first 200 chars. |
| `zeus_memory_delete` | `namespace, key` | Hard delete. |
| `zeus_memory_list_topics` | (none) | Returns `topic:*` names linked to current project + count of `new:*` pending. |
| `zeus_memory_rename_project` | `old_name, new_name` | Renames all memories from `project:<old>` to `project:<new>`, updates `topic_links`, updates `source_project` references. |
| `zeus_consolidation_done` | (none) | Sends a `consolidation_done` message through the agent bus to Zeus. Only for ephemeral consolidation agents. |

## 4. Insertion

### 4.1 Hot path — agent inline (zero extra LLM cost)

Agent calls `zeus_memory_save`:
- `global`: cross-cutting preferences
- `project:<name>`: project-specific (extension resolves name from cwd,
  agent doesn't need to know it)
- `new:<name>`: specialized knowledge beyond current project

On `new:*` save, extension auto-fills `source_project` and auto-creates
`topic_links(project, name)`.

### 4.2 Warm path — heuristic triggers (zero LLM cost)

**A) Correction detector (`before_agent_start`):**

Extension tracks whether previous turn had tool calls (flag set in
`turn_end`). On `before_agent_start`:

1. Was previous turn a tool-calling turn?
2. Does `event.prompt` match correction patterns?
   - Starts with: `"no,"` / `"no."` / `"wrong"` / `"actually,"` / `"actually "`
   - Contains: `"don't "` / `"instead of"` / `"not like that"` / `"I said"` /
     `"I meant"` / `"should be ... not"`
   - Short message (< 300 chars) after an edit/write tool call
3. If both match: save to `project:<name>` with key `correction:<timestamp>`,
   tags `correction,pending`, content is user's message verbatim.

**B) Failed-action detector (`turn_end`):**

Scan `event.toolResults` in sequence. If `edit`/`write` followed by `bash`
with `isError: true`:

- Save to `project:<name>` with key `mistake:<file-path-hash>:<timestamp>`,
  tags `mistake,automated`.
- Content: `"Edit to <path> failed: <error excerpt>"` (first 200 chars of
  error output).

### 4.3 Cold path — consolidation via ephemeral Hippeus

Triggered from dashboard `Ctrl+Alt+M`. Dialog contains:
- **Model dropdown** (top): cached available-models, preselects last-used
  invoke model
- **Topic dropdown**: all `topic:*` namespaces + `global`
- **"Consolidate Topic" button**: runs topic/global consolidation on
  dropdown selection
- **"Consolidate Project" button**: runs project consolidation for
  selected agent's project

On press:

1. Spawn ephemeral Hippeus (same cwd as selected agent, chosen model).
2. Tag as ephemeral: write `~/.zeus/ephemeral/<agent_id>`.
3. Load consolidation prompt from `~/.zeus/consolidation-project.md` or
   `~/.zeus/consolidation-topic.md`. Replace `<project_name>` or
   `<namespace>` placeholder. Send as initial task.
4. Hippeus works using `zeus_memory_*` tools.
5. If ambiguous conflicts: agent asks, user responds via dashboard message
   dialog, agent resolves.
6. Hippeus calls `zeus_consolidation_done` → sends `consolidation_done`
   message through agent bus to Zeus:
   ```json
   {
     "type": "consolidation_done",
     "agent_id": "<agent_id>",
     "timestamp": "<iso>"
   }
   ```
7. Dashboard bus drain loop receives message, matches agent_id to
   ephemeral tag, kills agent, cleans up ephemeral marker.
8. Safety net: 30min without done signal → acknowledge-required warning
   modal. User can kill or let it continue.

#### Project consolidation (config/consolidation-project.md)

Full self-contained prompt. The ephemeral agent has no prior context — this
prompt IS the entire instruction set. Contains:

- Memory system explanation (namespaces, tools, what good memories look like)
- Step 1 — Process `new:*` topics: for each `new:<topic>` with
  `source_project` matching this project, check if a `topic:<topic>` exists.
  If yes, merge memories into it and delete `new:*` entries. If no, promote
  `new:*` to `topic:*` (save with `topic:` namespace, delete `new:` entries).
  Update topic_links. Discard low-quality entries.
- Step 2 — Process `correction,pending` entries: read the raw user message,
  extract the underlying rule/preference, save as a proper memory with a
  descriptive key in `project:<name>` or `global` depending on scope, delete
  the raw correction entry.
- Step 3 — Process `mistake,automated` entries: if the mistake reveals a
  pattern worth remembering, save as a proper memory in `project:<name>` or
  `global`. If it was a one-off, delete it.
- Step 4 — Deduplicate remaining project memories: merge near-duplicates,
  remove older entries when a newer one clearly overrides, delete stale
  entries.
- Step 5 — Report summary.
- Step 6 — Call `zeus_consolidation_done`.

#### Topic/global consolidation (config/consolidation-topic.md)

Full self-contained prompt. Contains:

- Memory system explanation (namespaces, tools, what good memories look like)
- Step 1 — List all memories in the namespace.
- Step 2 — Merge near-duplicates, keep the most complete version, delete
  redundant entries.
- Step 3 — Resolve overrides. Clear overrides (same subject, newer
  timestamp): delete old entry. Ambiguous conflicts: list both, ask which
  to keep, do NOT call done until resolved.
- Step 4 — Improve quality: rewrite vague keys/content without changing
  meaning.
- Step 5 — Report summary.
- Step 6 — Call `zeus_consolidation_done`.

## 5. Extraction (Recall)

### 5.1 Automatic injection (`before_agent_start`, every prompt)

1. Resolve project: `pi.exec("git", ["rev-parse", "--show-toplevel"])` →
   strip `~/code/`, replace `/` with `-`.
2. Query `topic_links` for topics linked to this project.
3. Load memories (excluding `archived = 1`):
   - `global`: up to 2K tokens
   - `project:<name>`: up to 3K tokens
   - Each linked `topic:*`: up to 1K per topic, max 4K total
4. FTS5 search across all above namespaces using `event.prompt`, ranked by
   `bm25()`, limit 10.
5. Deduplicate: skip `(namespace, key)` pairs already loaded in step 3.
6. Format as text block, append to `event.systemPrompt`.
7. Total budget: **10K tokens**.

FTS results fill whatever budget remains after fixed sections.

### 5.2 Injected block format

```
[Agent Memory]
Project: zeus | Linked topics: zk-proofs, rust-async | Pending: 2 new topics

[global]
- user:preferences: Prefers early returns, conventional commits, no ternaries...

[project:zeus]
- error-handling-convention: All dashboard errors use modal notice, not toast...
- tmux-ownership-decision: ID-only matching, no cwd heuristics...

[topic:zk-proofs]
- circuit-size: R1CS constraint count grows quadratically with...

[Relevant to this prompt]
- project:zeus/config-parse: Tried serde flatten, failed because...
- topic:rust-async/cancellation: Always use select! with...
```

### 5.3 FTS5 query for [Relevant to this prompt]

```sql
SELECT namespace, key, content, bm25(memories_fts) AS rank
FROM memories_fts
WHERE memories_fts MATCH ?
  AND namespace IN ('global', 'project:zeus', 'topic:zk-proofs', 'topic:rust-async')
  AND archived = 0
ORDER BY rank
LIMIT 10;
```

MATCH parameter is user's prompt text. BM25 scores relevance (TF-IDF).
Common words score low, domain terms score high.

**Limitation:** keyword-based, not semantic. Mitigated by instructing agents
to use descriptive keys and content. Qdrant for semantic search is a future
phase.

### 5.4 On-demand (tools)

Agent calls `zeus_memory_search` / `zeus_memory_recall` when auto-injected
context isn't sufficient.

## 6. Context Assembly in Pi

### 6.1 Startup (once, or on tool change / /reload)

```
_baseSystemPrompt = buildSystemPrompt({
  1. Base Pi prompt (tools, guidelines, docs)
  2. + APPEND_SYSTEM.md (Zeus: security, messaging, tmux, memory instructions)
  3. + Project Context (AGENTS.md chain from ~/.pi/agent/ to cwd)
  4. + Skills
  5. + Date/time + cwd
})
```

### 6.2 Each user prompt

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

Per-turn injection. Pi resets system prompt after each prompt. Fresh memories
loaded every turn.

## 7. System Prompt Addition (APPEND_SYSTEM.md)

```
Agent memory
- You have persistent memory across sessions via zeus_memory_* tools.
- Namespace types:
  - `global`: universal preferences, cross-cutting knowledge.
  - `project:<name>`: per-git-repo. Auto-derived from repo root, you don't
    need to specify the name.
  - `new:<name>`: specialized knowledge beyond current project
    (e.g. `new:rust-async`). Staged for consolidation.
  - `topic:<name>`: promoted specialized knowledge. Read-only — write to
    `new:<name>` instead.
- Available tools:
  - `zeus_memory_save(namespace, key, content, tags?)`: store a memory.
    Namespace must be `global`, `project:<name>`, or `new:<name>`.
  - `zeus_memory_recall(namespace, key)`: retrieve a specific memory by
    exact key.
  - `zeus_memory_search(query, namespace?, limit?)`: full-text search. If
    namespace omitted, searches global + project + linked topics.
  - `zeus_memory_list(namespace?, limit?)`: browse memories. If namespace
    omitted, lists current project.
  - `zeus_memory_delete(namespace, key)`: remove a memory.
  - `zeus_memory_list_topics()`: show topics linked to current project and
    pending new topics.
  - `zeus_memory_rename_project(old_name, new_name)`: rename a project
    namespace and update all references.
- When to save:
  - User corrections ("don't do X, do Y instead")
  - Architecture/design decisions
  - Non-obvious gotchas or dependency quirks
  - Coding style preferences (global)
  - Specialized knowledge beyond this project (new:<topic-name>)
- When to search:
  - Starting a new task: search for relevant project context
  - Encountering unfamiliar code/patterns: check for past learnings
  - Before making architecture decisions: check for prior decisions
- Relevant memories are auto-injected at the start of each prompt. Use the
  search tool when you need deeper context.
- Keep content concise — store what you learned, not raw observations.
- Use descriptive keys: `error-handling-convention`, `no-orm-policy`,
  `auth-strategy-decision`.
- Use descriptive content with specific terms — recall is keyword-based.
```

## 8. Files

| File | Location in repo | Installed to | Overwrite policy |
|---|---|---|---|
| `config/consolidation-project.md` | repo | `~/.zeus/consolidation-project.md` | Always overwrite |
| `config/consolidation-topic.md` | repo | `~/.zeus/consolidation-topic.md` | Always overwrite |
| `config/message-presets.toml` | repo | `~/.zeus/message-presets.toml` | Always overwrite |
| `prompts/APPEND_SYSTEM.md` | repo | `~/.pi/agent/APPEND_SYSTEM.md` | Copy (not symlinked) |
| `pi_extensions/zeus.ts` | repo | `~/.pi/agent/extensions/zeus.ts` | Symlink |
| DB | — | `~/.zeus/memory.db` | Created lazily on first tool use |

## 9. Implementation Phases

### Phase 1: Storage + tools

- `zeus/memory.py`: schema creation, query helpers, project name resolution
  from cwd via `git rev-parse --show-toplevel`.
- 8 extension tools in `pi_extensions/zeus.ts`: `zeus_memory_save`,
  `zeus_memory_recall`, `zeus_memory_search`, `zeus_memory_list`,
  `zeus_memory_delete`, `zeus_memory_list_topics`,
  `zeus_memory_rename_project`, `zeus_consolidation_done`.
- DB at `~/.zeus/memory.db`, lazy init on first tool use.
- Namespace validation: reject direct `topic:*` writes from regular agents.
- `topic_links` auto-creation on `new:*` saves.
- `source_agent` and `source_project` auto-fill on every save.
- FTS5 sync triggers: keep FTS index in sync with memories table on
  insert/update/delete.
- Tests for all memory operations, namespace validation, FTS5 indexing,
  project name resolution.

### Phase 2: Automatic injection

- `before_agent_start` hook in `pi_extensions/zeus.ts`.
- Project resolution via `git rev-parse --show-toplevel`.
- Load global + project + linked topics memories from SQLite.
- FTS5 search against `event.prompt`, dedup against already-loaded.
- Format memory block, enforce 10K token budget (2K global, 3K project,
  4K topics, remainder for FTS).
- Append to `event.systemPrompt`, return modified prompt.
- Tests for injection logic, budget enforcement, dedup, empty DB case.

### Phase 3: Warm path triggers

- Correction detector: `before_agent_start` hook, track previous-turn tool
  usage flag via `turn_end`, pattern-match `event.prompt`.
- Failed-action detector: `turn_end` hook, scan `event.toolResults` for
  edit→bash-failure sequences.
- Both write to `project:<name>` with appropriate tags.
- Tests for both detectors, edge cases (no previous turn, no git repo,
  multiple edits in one turn).

### Phase 4: Consolidation UI + ephemeral agents

- Write `config/consolidation-project.md` and
  `config/consolidation-topic.md` with full self-contained prompts.
- Update `install.sh` to copy both to `~/.zeus/` (always overwrite).
- Dashboard dialog (`Ctrl+Alt+M`): model dropdown, topic dropdown,
  "Consolidate Topic" button, "Consolidate Project" button.
- Ephemeral Hippeus spawning: create agent with chosen model and cwd,
  write `~/.zeus/ephemeral/<agent_id>`, load prompt from `~/.zeus/`,
  replace placeholders, send as initial message.
- `zeus_consolidation_done` tool: send `consolidation_done` message
  through agent bus to Zeus.
- Dashboard bus drain: detect `consolidation_done` message, match to
  ephemeral agent, kill agent, cleanup ephemeral marker.
- 30-minute safety net: acknowledge-required warning modal for ephemeral
  agents that haven't signaled done.
- CSS for consolidation dialog.
- Tests for dialog, ephemeral lifecycle, done detection, safety net timeout.

### Phase 5: System prompt + install

- Update `prompts/APPEND_SYSTEM.md` with memory section (section 7).
- Copy updated APPEND_SYSTEM.md to `~/.pi/agent/APPEND_SYSTEM.md`.
- End-to-end manual testing with a live agent: save, recall, search,
  injection, consolidation cycle.
- Write architecture diagrams (sections 6.1, 6.2) into `README.md`.
