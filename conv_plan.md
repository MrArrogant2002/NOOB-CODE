# NOOB CODE — Prompting Pipeline & Memory Architecture

## Three-Layer Memory System

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1 — Working Memory (RAM, per-task, lost after task)    │
│   WorkingMemory._recent  ← tool loop exchanges               │
│   Rebuilt fresh every task from the layers below             │
├─────────────────────────────────────────────────────────────┤
│ Layer 2 — Session Memory (SQLite, data/sessions.db)          │
│   Stores raw user messages with timestamps                   │
│   ONLY used for UI display / markdown export                 │
│   NOT fed back to the model between tasks                    │
├─────────────────────────────────────────────────────────────┤
│ Layer 3 — Long-Term Memory (.noob-code/memory.md)            │
│   Bullet-point notes the LLM writes about the project        │
│   Survives across all sessions, loaded into every task       │
└─────────────────────────────────────────────────────────────┘
```

---

## Turn-by-Turn: What Goes Into the Model

### Turn 1 — User types "hello"

`_run_task()` fires. A brand-new `WorkingMemory` is created. The exact message list
sent to Ollama:

```
messages = [
  {
    "role": "system",
    "content":
      "You are NOOB CODE, a local AI coding assistant built by Eswar Balu...
       [identity block — who you are, who created you, what you are NOT]

       RULE 1 — conversational messages: greetings → plain text + finish, no tools.
       RULE 2 — coding tasks: one tool at a time, verify, then finish.
       RULE 3 — file operations: MUST call write_file/edit_file, never write content as text.
       RULE 4 — no tool-call echoing: never include tool-call JSON in text reply.
       [test policy: protected or open]

       ── if .noob-code/memory.md exists ──────────────────────────
       ## Project Memory
       - bullet notes written by the LLM in previous sessions...

       ── if codebase indexer has run ─────────────────────────────
       ## Codebase Map
       backend/server.py → async def _run_task(), class ConnectionState...
       orchestrator/tools.py → class ToolBox, def run_shell()..."
  },
  {
    "role": "user",
    "content": "hello"
  }
]
```

Model replies in plain text and calls `finish`. After task ends:
- `append_message(session_id, "user", "hello")` → written to SQLite
- `update_after_task("hello", summary, ...)` → a **separate** bare LLM call generates
  1–3 bullet notes → appended to `.noob-code/memory.md`
- `WorkingMemory` object is **discarded** — nothing carries over to the next task

---

### Turn 2 — User types "write a brief.md file and tell me its location"

A **completely new** `WorkingMemory` is built. The "hello" exchange is gone. The first
LLM call for this task receives:

```
messages = [
  {
    "role": "system",
    "content":
      "[identity block]
       [rules 1–4]
       [test policy]

       ## Project Memory
       - notes from the 'hello' task (if any were generated)

       ## Codebase Map
       ..."
  },
  {
    "role": "user",
    "content": "write a brief.md file and tell me its location"
  }
]
```

The model calls `list_dir`. The tool runs and returns results. `memory.add_exchange()`
is called. The **second** LLM call within the same task now receives:

```
messages = [
  { "role": "system",    "content": "... [same system prompt] ..." },
  { "role": "user",      "content": "write a brief.md file and tell me its location" },
  { "role": "assistant", "content": "{\"name\":\"list_dir\",\"arguments\":{\"path\":\".\"}}"},
  { "role": "user",      "content": "<tool_response>\n[directory listing]\n</tool_response>" }
]
```

Each tool call adds one `[assistant, tool_response]` pair. This grows until the model
calls `finish` or hits `MAX_ORCHESTRATION_STEPS`.

---

## `build_context()` — Priority Order of Assembly

Defined in `backend/memory/working_memory.py`:

```
Priority  Layer                         Budget rule
────────  ───────────────────────────── ───────────────────────────────────────
  1       System prompt                 Never truncated
  2       ## Project Memory (LTM)       Capped at LONG_TERM_MEMORY_MAX_TOKENS
  3       ## Codebase Map (indexer)     Capped at CODEBASE_MAP_MAX_TOKENS
  4       ## Execution Plan (plan mode) Kept if it fits, dropped if over budget
  5       <active_file> content         Capped at 30% of remaining budget
  6       Recent tool exchanges         Sliding window — oldest pair dropped first
```

---

## Context Limit Behaviour

Two thresholds are checked at each step of the tool loop:

| Threshold | Trigger | What happens |
|-----------|---------|--------------|
| **80%** full | `needs_compression()` returns True | Warning sent to UI: "Context window near capacity — oldest messages trimmed" |
| **85%** full | Inside `build_context()` | Oldest `[assistant + tool_response]` pairs are silently dropped from `_recent` until the total fits |

The model never sees an error or truncation notice. Only visible symptom: the UI
warning and the model potentially "forgetting" early tool results from the current task.

---

## What Persists and What Doesn't

| Data | Stored in | Persists across tasks? | Fed to model? |
|------|-----------|----------------------|---------------|
| Current task's tool exchanges | `WorkingMemory._recent` (RAM) | No — destroyed when task ends | Yes — in message list |
| User message text | SQLite `data/sessions.db` | Yes (resumes within 24 h) | **No** — export/display only |
| Project notes | `.noob-code/memory.md` | Yes — permanent | Yes — in system prompt |
| Codebase signatures | `_index_cache` (server RAM) | Until server restarts | Yes — in system prompt |
| Attached file content | `WorkingMemory.current_file` | No | Yes — injected as user message |

---

## Key Architectural Gap

The model has **no memory of what was said in message 1 when it receives message 2**.
Each task starts fresh. The only cross-task continuity is:

1. **Long-term notes** — bullet points the LLM itself writes after each task about the
   project (conventions, decisions, constraints). Written to `.noob-code/memory.md`.
2. **Codebase map** — function/class signatures from the indexer, rebuilt on file saves.

For true multi-turn conversational memory, session messages from SQLite would need to
be loaded back into `WorkingMemory._recent` at the start of each task. The current
architecture does not do this — each message is an independent task with project-level
context but no conversation history.

---

## File Locations

| Purpose | Path |
|---------|------|
| Working memory logic | `backend/memory/working_memory.py` |
| Session storage (SQLite) | `data/sessions.db` |
| Long-term notes | `{workspace}/.noob-code/memory.md` |
| Codebase indexer | `backend/indexer/signatures.py` |
| Task runner | `backend/server.py` → `_run_task()`, `_execute_mode()` |
| LTM update logic | `backend/memory/long_term_memory.py` → `update_after_task()` |
