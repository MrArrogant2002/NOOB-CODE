# NOOB CODE — Complete Build Plan

## Project Identity

- **Product name:** NOOB CODE
- **Extension ID:** `noob-code`
- **Description:** A local, fully-featured VS Code coding agent powered by any Ollama model.
  Works offline, runs on the user's own hardware, provides a Claude Code-style interface
  with model selection, plan mode, edit approval, permission gates, and hierarchical memory.
- **Existing CLI tools (`main.py`, `orchestrator_cli.py`):** retired once the extension is stable.
  The underlying logic in `agent/`, `orchestrator/`, `sandbox/` is preserved and used by the backend.

---

## Architecture

```
[VS Code Extension — TypeScript]
         ↕  WebSocket  ws://localhost:7867/ws?token=<session_token>
[FastAPI Backend — Python]
         ↕
[Ollama API] + [Docker Sandbox] + [SQLite] + [File System]
```

The extension is pure UI. The backend is the brain. WebSocket is used (not HTTP) because
it supports real-time token-by-token streaming output like Claude Code's live interface.

---

## Technology Stack

| Layer | Technology | Reason |
|---|---|---|
| Extension UI | TypeScript + VS Code API | Required for VS Code extensions |
| Webview panel | Vanilla HTML + CSS + JS | No React build step in MVP — simpler |
| Backend server | Python 3.11+, FastAPI, asyncio | Wraps existing agent code |
| LLM interface | Ollama (any local model) | Already integrated |
| Code sandbox | Docker | Already integrated |
| Session store | SQLite | Already integrated |
| Token counting | `tiktoken` (cl100k_base) | Good approximation for all major model families |
| File indexing | `tree-sitter` (Python bindings) | Compact codebase map without loading full files |

---

## Complete Folder Structure (Final State)

```
noob-code/                              ← rename repo folder
├── backend/
│   ├── server.py                       # FastAPI app + WebSocket handler
│   ├── daemon.py                       # Single-instance lock, warm-up, session token
│   ├── checkpoint.py                   # Git stash checkpointing before edits
│   ├── permissions.py                  # Per-project permission store
│   ├── token_counter.py                # tiktoken-based token budget tracking
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── working_memory.py           # In-context: task plan + active file + recent msgs
│   │   ├── session_memory.py           # SQLite session store
│   │   └── long_term_memory.py         # .noob-code/memory.md read/write
│   └── indexer/
│       ├── __init__.py
│       ├── file_tree.py                # Walk workspace, respect .noodcodeignore
│       └── signatures.py              # Tree-sitter: extract function/class signatures
├── agent/                              # EXISTING — do not modify
│   ├── __init__.py
│   ├── generator.py
│   ├── classifier.py
│   ├── repairer.py
│   └── loop.py
├── orchestrator/                       # EXISTING — do not modify
│   ├── __init__.py
│   ├── parser.py
│   ├── planner.py
│   ├── schema.py
│   └── tools.py
├── sandbox/                            # EXISTING — do not modify
│   ├── __init__.py
│   └── executor.py
├── eval/                               # EXISTING — do not modify
│   ├── __init__.py
│   ├── benchmark.py
│   └── metrics.py
├── data/                               # Generated at runtime, gitignored
│   ├── logs.db
│   ├── .daemon.lock
│   └── .session_token
├── vscode-extension/
│   ├── src/
│   │   ├── extension.ts                # Activation entry point, backend lifecycle
│   │   ├── panel.ts                    # Sidebar webview panel management
│   │   ├── streaming.ts                # WebSocket client + message dispatch
│   │   ├── diff.ts                     # Edit approval diff viewer
│   │   ├── permissions.ts              # Permission gate dialogs
│   │   ├── models.ts                   # Fetch available Ollama models
│   │   └── settings.ts                 # VS Code settings → backend config bridge
│   ├── webview/
│   │   ├── panel.html                  # Chat UI
│   │   ├── panel.css                   # Styles (VS Code theme-aware CSS variables)
│   │   └── panel.js                    # Vanilla JS: send/receive messages, render output
│   ├── package.json                    # Extension manifest (see spec below)
│   ├── tsconfig.json
│   └── .vscodeignore
├── tests/
│   ├── test_loop.py                    # EXISTING
│   ├── test_parser.py                  # EXISTING
│   ├── test_orchestrator_tools.py      # EXISTING
│   ├── test_planner.py                 # EXISTING
│   ├── test_session_memory.py          # NEW
│   ├── test_permissions.py             # NEW
│   ├── test_token_counter.py           # NEW
│   └── test_checkpoint.py              # NEW
├── config.py                           # EXISTING + new constants (see below)
├── conftest.py                         # EXISTING
├── setup.py                            # NEW — one-click install script
├── requirements.txt                    # UPDATE — add new deps
├── .gitignore                          # UPDATE — add extension node_modules etc.
├── plan.md                             # THIS FILE
├── LICENSE
└── README.md                           # UPDATE for new setup flow
```

---

## WebSocket Message Protocol (Version 1)

All messages are JSON objects. Field `type` is always present.

### Extension → Backend (Client → Server)

```json
// Start a task
{
  "type": "task",
  "task": "Fix the failing tests in calc.py",
  "workspace": "/absolute/path/to/project",
  "model": "qwen2.5-coder:7b",
  "session_id": "abc123",         // omit for new session
  "plan_mode": false              // true = show plan before executing
}

// User approves/rejects a pending file edit
{"type": "approval", "request_id": "req_001", "decision": "approve"}
// decision options: "approve" | "reject" | "approve_all"

// User responds to a shell/git permission request
{"type": "permission", "request_id": "req_002", "decision": "allow"}
// decision options: "allow" | "deny" | "always_allow"

// User confirms plan execution (after reviewing plan_ready)
{"type": "plan_execute", "session_id": "abc123"}

// User cancels the running task
{"type": "cancel", "session_id": "abc123"}

// Fetch available Ollama models
{"type": "list_models"}

// Fetch conversation history for a session
{"type": "get_history", "session_id": "abc123"}

// Version handshake acknowledgement
{"type": "hello_ack", "api_version": "1"}
```

### Backend → Extension (Server → Client)

```json
// Version handshake (sent immediately on connection)
{"type": "hello", "api_version": "1", "backend_version": "0.1.0"}

// Streaming token from LLM
{"type": "token", "content": "I will read calc.py first..."}

// Tool about to execute — show spinner with label
{"type": "tool_start", "request_id": "req_001", "name": "read_file", "args": {"path": "calc.py"}}

// Tool result — show collapsible block
{"type": "tool_result", "request_id": "req_001", "name": "read_file", "result": "def add(a, b):\n    return a - b\n"}

// File edit needs user approval — open VS Code diff editor
{"type": "edit_request", "request_id": "req_001", "path": "calc.py", "diff": "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"}

// Shell or git command needs permission
{"type": "permission_request", "request_id": "req_002", "action": "run_shell", "command": "pytest -q"}

// Plan ready for review (plan_mode only) — show numbered steps + Execute/Cancel buttons
{"type": "plan_ready", "steps": ["1. Read the failing test output.", "2. Read calc.py.", "3. Fix the add() function.", "4. Re-run tests to confirm."]}

// Task complete
{"type": "done", "final_answer": "Fixed add() in calc.py. All tests pass."}

// Non-fatal warning
{"type": "warning", "message": "Context window 85% full, compressing old messages."}

// Fatal error
{"type": "error", "message": "Ollama connection refused. Run: ollama serve"}

// Available models response
{"type": "models_list", "models": [{"name": "qwen2.5-coder:7b", "context_length": 32768, "size": "4.7 GB"}, ...]}

// Session info
{"type": "session_info", "session_id": "abc123", "created_at": "2026-06-17T10:00:00Z", "message_count": 12}
```

---

## config.py — New Constants to Add

```python
# Backend server
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "7867"))
BACKEND_HOST = os.environ.get("BACKEND_HOST", "127.0.0.1")
SESSION_TOKEN_PATH = os.environ.get("SESSION_TOKEN_PATH", "data/.session_token")
DAEMON_LOCK_PATH = os.environ.get("DAEMON_LOCK_PATH", "data/.daemon.lock")

# Indexer
INDEXER_MAX_FILE_SIZE_BYTES = int(os.environ.get("INDEXER_MAX_FILE_SIZE_BYTES", str(100 * 1024)))
CODEBASE_MAP_MAX_TOKENS = int(os.environ.get("CODEBASE_MAP_MAX_TOKENS", "2000"))

# Memory
LONG_TERM_MEMORY_MAX_TOKENS = int(os.environ.get("LONG_TERM_MEMORY_MAX_TOKENS", "500"))
WORKING_MEMORY_SLIDING_WINDOW = int(os.environ.get("WORKING_MEMORY_SLIDING_WINDOW", "10"))

# Checkpointing
CHECKPOINT_KEEP_LAST = int(os.environ.get("CHECKPOINT_KEEP_LAST", "5"))
```

---

## requirements.txt — Final State

```
# LLM + agent
openai>=1.0.0

# Backend server
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
websockets>=12.0.0

# Token counting
tiktoken>=0.7.0

# File indexing
tree-sitter>=0.23.0

# Sandbox
docker>=7.0.0

# Testing
pytest>=8.0.0
```

---

## vscode-extension/package.json Spec

```json
{
  "name": "noob-code",
  "displayName": "NOOB CODE",
  "description": "Local AI coding agent powered by Ollama — works offline on your own hardware",
  "version": "0.1.0",
  "publisher": "noob-code",
  "engines": { "vscode": "^1.85.0" },
  "categories": ["AI", "Other"],
  "activationEvents": ["onStartupFinished"],
  "main": "./out/extension.js",
  "contributes": {
    "viewsContainers": {
      "activitybar": [{ "id": "noob-code-container", "title": "NOOB CODE", "icon": "$(robot)" }]
    },
    "views": {
      "noob-code-container": [{ "type": "webview", "id": "noobCodePanel", "name": "NOOB CODE" }]
    },
    "commands": [
      { "command": "noobCode.newTask",   "title": "NOOB CODE: New Task" },
      { "command": "noobCode.debugFix",  "title": "NOOB CODE: Debug Fix Current File" },
      { "command": "noobCode.openPanel", "title": "NOOB CODE: Open Panel" },
      { "command": "noobCode.newSession","title": "NOOB CODE: New Session" },
      { "command": "noobCode.exportSession", "title": "NOOB CODE: Export Session to Markdown" },
      { "command": "noobCode.reindexWorkspace", "title": "NOOB CODE: Re-index Workspace" }
    ],
    "configuration": {
      "title": "NOOB CODE",
      "properties": {
        "noobCode.ollamaUrl":         { "type": "string",  "default": "http://localhost:11434/v1", "description": "Ollama base URL" },
        "noobCode.defaultModel":      { "type": "string",  "default": "qwen2.5-coder:7b",         "description": "Default model" },
        "noobCode.backendPort":       { "type": "number",  "default": 7867,                        "description": "Backend port" },
        "noobCode.planModeDefault":   { "type": "boolean", "default": false,                       "description": "Start every task in plan mode" },
        "noobCode.permissionMode":    { "type": "string",  "default": "ask", "enum": ["ask", "auto-approve", "yolo"], "description": "Permission level for file/shell operations" },
        "noobCode.gpuLayers":         { "type": "number",  "default": -1,                          "description": "Ollama GPU layers (-1 = auto)" },
        "noobCode.maxContextTokens":  { "type": "number",  "default": 0,                           "description": "Override context window size (0 = auto-detect from model)" },
        "noobCode.dockerEnabled":     { "type": "boolean", "default": true,                        "description": "Use Docker sandbox for code execution" }
      }
    },
    "keybindings": [
      { "command": "noobCode.newTask",  "key": "ctrl+shift+n", "when": "editorFocus" },
      { "command": "noobCode.debugFix", "key": "ctrl+shift+d", "when": "editorFocus" }
    ]
  },
  "scripts": {
    "compile": "tsc -p ./",
    "watch":   "tsc -watch -p ./",
    "package": "npx vsce package --no-dependencies"
  },
  "devDependencies": {
    "@types/vscode": "^1.85.0",
    "@types/node": "^20.0.0",
    "typescript": "^5.0.0",
    "@vscode/vsce": "^2.0.0"
  }
}
```

---

## All 10 Risk Mitigations — Implementation Specs

### Risk 1: Multiple VS Code windows → port conflict
**Location:** `backend/daemon.py` + `vscode-extension/src/extension.ts`

`daemon.py`:
```python
def acquire_or_connect(port: int, lock_path: str) -> tuple[bool, int]:
    """Returns (is_owner, actual_port).
    
    If lockfile exists with a live PID, returns (False, port_in_lockfile).
    Otherwise writes our PID+port to lockfile and returns (True, port).
    """
    if os.path.exists(lock_path):
        with open(lock_path) as f:
            data = json.load(f)
        try:
            os.kill(data["pid"], 0)   # check if PID is alive
            return False, data["port"]  # another instance is live, connect to it
        except (ProcessLookupError, PermissionError):
            pass  # stale lockfile, claim it
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "w") as f:
        json.dump({"pid": os.getpid(), "port": port}, f)
    return True, port
```

`extension.ts`: before spawning backend, read lockfile. If live PID → connect to existing backend on its port. Skip spawning.

### Risk 2: Model cold-start latency (5–30s on first request)
**Location:** `backend/daemon.py`

On startup, after the server is listening, fire an async background task:
```python
async def warm_up_model(model: str, ollama_url: str) -> None:
    client = AsyncOpenAI(base_url=ollama_url, api_key="ollama")
    try:
        await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
    except Exception:
        pass   # warm-up failure is non-fatal
```
Trigger this on startup for `PRIMARY_MODEL`. Extension shows status bar item "NOOB CODE: warming up..." that disappears once warm-up completes (signalled via an internal flag checked by the health endpoint).

### Risk 3: Small model tool-call format variance
**Location:** `orchestrator/parser.py` (already built)

Add a per-model configurable `tool_call_style` setting:
- `"auto"` (default): try to parse from `tool_calls` field first, fall back to content parsing
- `"text"`: skip `tool_calls` field, always parse from content (for models known to be unreliable)
- `"structured"`: only trust `tool_calls` field

Store as `{"model_name": "style"}` in `data/model_styles.json`. The extension exposes "Tool Call Style" in per-model settings.

### Risk 4: Large repo + small context window
**Location:** `backend/indexer/`

`file_tree.py`:
- Walk workspace, skip anything in `.noodcodeignore` OR these default patterns:
  `node_modules/`, `.venv/`, `venv/`, `__pycache__/`, `.git/`, `dist/`, `build/`, `*.pyc`, `*.min.js`, `*.lock`, `package-lock.json`
- Output: compact file tree string, one path per line. Typically 50–300 tokens.

`signatures.py`:
- Use `tree-sitter` to extract function signatures + class names per file
- If tree-sitter grammar not available for that language: use first 15 lines as fallback
- Cap each file's contribution at 150 tokens
- Cap total codebase map at `CODEBASE_MAP_MAX_TOKENS` (default 2000 tokens)
- Output format:
  ```
  calc.py: def add(a, b), def subtract(a, b)
  test_calc.py: def test_add(), def test_subtract()
  ```

Inject the full codebase map into every system prompt. It stays in context permanently (it's small enough).

Re-indexing: trigger on workspace open, on "Re-index Workspace" command, and debounced 30s after any file save.

### Risk 5: Streaming + tool execution interleaving
**Location:** `backend/server.py`

Use Python `asyncio` throughout. The WebSocket handler is a single `async def` coroutine.
Tools that block (Docker exec, git operations) run in `asyncio.get_event_loop().run_in_executor(None, blocking_fn)` so they don't block the event loop.

Message sequence the extension must handle:
```
token → token → token → tool_start (show spinner) → [blocking tool runs async]
→ tool_result (hide spinner, show collapsible block) → token → token → done
```

Extension's `streaming.ts` maintains a message queue and dispatches by `type`. `tool_start` triggers a spinner keyed to `request_id`. `tool_result` with the same `request_id` hides that spinner and shows the result block.

### Risk 6: Local server security — unauthorized callers
**Location:** `backend/daemon.py` + `backend/server.py`

On first backend startup, generate a 32-byte hex token and write to `data/.session_token`:
```python
def get_or_create_session_token(path: str) -> str:
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    token = secrets.token_hex(32)
    with open(path, "w") as f:
        f.write(token)
    return token
```

Every WebSocket connection must include `?token=<value>` query parameter. Server validates against the stored token. Invalid token → close with code 4001 + message "Unauthorized".

The extension reads the token from `data/.session_token` at startup (it knows the backend's working directory since it spawned it or knows the repo path).

### Risk 7: Partial edits on crash / orphaned Docker containers
**Location:** `backend/checkpoint.py`

```python
def create_checkpoint(workspace_path: str) -> str | None:
    """Create a git stash before the first file write in a task session."""
    result = subprocess.run(
        ["git", "stash", "push", "-u", "-m", f"noob-code checkpoint {datetime.now(timezone.utc).isoformat()}"],
        cwd=workspace_path, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode == 0 and "No local changes" not in result.stdout:
        return result.stdout.strip()
    return None

def cleanup_orphaned_containers() -> None:
    """Kill any noob-code sandbox containers left from a previous crashed session."""
    subprocess.run(
        ["docker", "rm", "-f", "$(docker ps -q --filter name=selfdebug-orch)"],
        shell=True, capture_output=True
    )
```

Call `cleanup_orphaned_containers()` at every backend startup.
Call `create_checkpoint()` before the first `write_file`/`edit_file`/`run_shell` in each task.
Keep last `CHECKPOINT_KEEP_LAST` (5) checkpoints, clean up older ones automatically.

On crash recovery: backend startup checks if previous session had a checkpoint but no `done` message logged. If so, sends a `warning` to the extension on next connect: "Previous session ended without finishing. A git stash checkpoint exists. Use NOOB CODE: Restore Checkpoint to roll back."

### Risk 8: Permission fatigue
**Location:** `backend/permissions.py`

Per-project store at `<workspace>/.noob-code/permissions.json`:
```json
{
  "FileRead":  "always",
  "FileWrite": "ask",
  "ShellExec": "ask",
  "GitOp":     "ask",
  "NetworkCall": "deny"
}
```

Three levels:
- `"always"`: proceed without asking (used for FileRead automatically)
- `"ask"`: send `permission_request` over WebSocket, block until user responds
- `"deny"`: return error immediately without asking

When user clicks "Allow Always" in the extension:
1. Extension sends `{"type": "permission", "request_id": "...", "decision": "always_allow"}`
2. Backend updates `permissions.json` for that action type to `"always"`
3. Future calls of that action type skip the permission gate entirely

Three global modes (VS Code setting `noobCode.permissionMode`):
- `"ask"` — use per-action levels above (default)
- `"auto-approve"` — treat all actions as "always" (for trusted local projects)
- `"yolo"` — same as auto-approve but also skips edit diff review (power user mode)

### Risk 9: Conversation context drift on long sessions
**Location:** `backend/memory/long_term_memory.py`

After every task completion, the backend calls:
```python
async def update_long_term_memory(task: str, summary: str, workspace_path: str, model: str) -> None:
    """Append a compact note about what was discovered/decided to .noob-code/memory.md."""
    existing = load_long_term_memory(workspace_path)
    prompt = (
        f"Existing notes:\n{existing}\n\n"
        f"Task just completed: {task}\n"
        f"Outcome: {summary}\n\n"
        "Append 1-3 new bullet points to the notes capturing: any convention discovered, "
        "any important architectural decision made, any constraint to remember. "
        "Do not duplicate existing notes. Return ONLY the new bullet points, no other text."
    )
    response = await call_ollama_async([{"role": "user", "content": prompt}], model=model)
    append_to_long_term_memory(workspace_path, response)
```

At the start of every task, read `.noob-code/memory.md` and inject it into the system prompt (capped at `LONG_TERM_MEMORY_MAX_TOKENS` = 500 tokens). This means past discoveries persist across sessions and resist context-drift even through summarization cycles.

### Risk 10: Extension + backend version mismatch
**Location:** `backend/server.py` + `vscode-extension/src/streaming.ts`

Both sides maintain `API_VERSION = "1"`.

On every new WebSocket connection, backend immediately sends:
```json
{"type": "hello", "api_version": "1", "backend_version": "0.1.0"}
```

Extension responds with:
```json
{"type": "hello_ack", "api_version": "1"}
```

If extension's `api_version` ≠ server's `api_version`:
- Server sends `{"type": "error", "message": "API version mismatch. Please update the NOOB CODE backend: python setup.py --update"}`
- Server closes the connection
- Extension shows a VS Code error notification with the message

---

## Memory System — Option D (Hierarchical, 3 Layers)

### Layer 1: Working Memory (In-Context)

`backend/memory/working_memory.py`

```python
class WorkingMemory:
    system_prompt: str           # always present, never truncated
    long_term_notes: str         # from .noob-code/memory.md — capped at 500 tokens
    codebase_map: str            # from indexer — capped at 2000 tokens
    current_file: str | None     # content of the @-mentioned or active file
    task_plan: list[str]         # from plan mode (empty if plan mode off)
    recent_messages: list[dict]  # sliding window of last N turns
```

`build_context(token_counter, context_length) -> list[dict]`:
Token budget allocation (priority, highest = last truncated):
1. System prompt — never truncated
2. Long-term notes — capped at `LONG_TERM_MEMORY_MAX_TOKENS`
3. Codebase map — capped at `CODEBASE_MAP_MAX_TOKENS`
4. Task plan — kept if fits, dropped if over budget
5. Current file content — capped at 30% of remaining budget
6. Recent messages — sliding window, oldest dropped first

When recent messages + other layers exceed 85% of `context_length`:
- Drop oldest messages until under 75%
- If still over after dropping all messages: trigger summarization

Summarization trigger:
```python
async def compress_history(messages: list[dict], model: str) -> str:
    """Summarize conversation history into ≤ 5 bullet points."""
    content = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    prompt = f"Summarize this conversation in 5 bullet points:\n{content}"
    return await call_ollama_async([{"role": "user", "content": prompt}], model=model)
```
Replace dropped messages with `{"role": "system", "content": "Previous conversation summary:\n<bullets>"}`.
Send `{"type": "warning", "message": "Context window 85% full — compressing older messages."}` to extension.

### Layer 2: Session Memory (SQLite)

`backend/memory/session_memory.py`

Schema:
```sql
CREATE TABLE sessions (
    session_id    TEXT PRIMARY KEY,
    workspace_path TEXT NOT NULL,
    model         TEXT NOT NULL,
    messages      TEXT NOT NULL DEFAULT '[]',   -- JSON array of {role, content, timestamp}
    created_at    TEXT NOT NULL,
    last_active   TEXT NOT NULL
);
```

Key functions:
- `create_session(workspace_path, model) -> str` — returns new UUID session_id
- `load_session(session_id) -> dict | None`
- `get_or_create_for_workspace(workspace_path, model) -> tuple[dict, bool]` — (session, is_resumed)
- `append_message(session_id, role, content)` — adds to messages JSON array
- `list_recent_sessions(workspace_path, limit=5) -> list[dict]`
- `export_to_markdown(session_id, output_path: str)` — saves session as readable `.md` file

Resume logic: if a session for the same workspace exists and `last_active` is within 24 hours, offer to resume. Extension shows: "Resume previous session? (N messages, last active X hours ago)" via VS Code info message with [Resume] [New Session] buttons.

### Layer 3: Long-Term Memory (`.noob-code/memory.md`)

`backend/memory/long_term_memory.py`

- File lives at `<workspace_path>/.noob-code/memory.md`
- Created automatically on first task completion if it doesn't exist
- Format: plain markdown bullet points
- Read at session start, injected into working memory as `long_term_notes`
- Updated after every task completion (see Risk 9 implementation above)
- Capped read at `LONG_TERM_MEMORY_MAX_TOKENS` (500 tokens) — if file is longer, read the most recent entries (tail)

The `.noob-code/` directory also stores:
- `permissions.json` (Risk 8)
- `checkpoint.log` (records of checkpoints created by Risk 7)

Users should add `.noob-code/` to their project's `.gitignore` if they don't want it committed (it contains local agent state, not source code).

---

## Build Phases

### Phase 0 — Repo Restructure + New Dependencies

**Goal:** Get the new structure in place without breaking any existing tests.

Steps:
1. Create `backend/`, `backend/memory/`, `backend/indexer/` directories with empty `__init__.py` files
2. Create empty stub files: `backend/server.py`, `backend/daemon.py`, `backend/checkpoint.py`, `backend/permissions.py`, `backend/token_counter.py`, `backend/memory/working_memory.py`, `backend/memory/session_memory.py`, `backend/memory/long_term_memory.py`, `backend/indexer/file_tree.py`, `backend/indexer/signatures.py`
3. Create `vscode-extension/` directory with `package.json`, `tsconfig.json`, empty `src/extension.ts`
4. Add to `requirements.txt`: `fastapi>=0.110.0`, `uvicorn[standard]>=0.29.0`, `websockets>=12.0.0`, `tiktoken>=0.7.0`, `tree-sitter>=0.23.0`
5. Add to `config.py`: all new constants from the config section above
6. Update `.gitignore`:
   ```
   vscode-extension/node_modules/
   vscode-extension/out/
   *.vsix
   data/.daemon.lock
   data/.session_token
   ```
7. Run `py -3.11 -m pytest tests/ -q` → must still show `32 passed`

**Exit criteria:** 32 existing tests pass. `python -c "import backend.server"` works without error.

---

### Phase 1 — Backend Server

**Goal:** Working FastAPI + WebSocket backend with all risk mitigations built in from the start.

#### Phase 1.1 — Daemon, Token Auth, Warm-up, Version Handshake (Risks 1, 2, 6, 10)

Implement `backend/daemon.py`:
- `acquire_or_connect(port, lock_path) -> tuple[bool, int]` (Risk 1 — single instance)
- `get_or_create_session_token(path) -> str` (Risk 6 — token auth)
- `async warm_up_model(model, ollama_url)` (Risk 2 — cold start)
- API_VERSION constant (Risk 10 — version handshake)

Implement core of `backend/server.py`:
- FastAPI app
- `GET /health` — returns `{"status": "ok", "api_version": "1", "backend_version": "0.1.0", "warmed_up": bool}`
- `GET /models` — calls `ollama list` subprocess, parses output, returns model list with context lengths
- `WS /ws` — validates token query param, sends `hello` message, awaits `hello_ack`

#### Phase 1.2 — Token Counter (Risk 4 prerequisite)

Implement `backend/token_counter.py`:
- `class TokenCounter` wrapping `tiktoken.get_encoding("cl100k_base")`
- `count(text: str) -> int`
- `count_messages(messages: list[dict]) -> int`
- `budget_remaining(messages, context_length: int, reserve_pct: float = 0.15) -> int`

Write `tests/test_token_counter.py` — verify counts are within 15% of actual for representative code samples.

#### Phase 1.3 — Session Memory (Layer 2)

Implement `backend/memory/session_memory.py` with full SQLite schema and all functions listed above.
Write `tests/test_session_memory.py` — test create/load/resume/export using `tmp_path` fixture.

#### Phase 1.4 — Working Memory + Context Overflow (Layer 1)

Implement `backend/memory/working_memory.py`:
- `WorkingMemory` dataclass with all fields
- `build_context(token_counter, context_length) -> list[dict]` with priority-based budget allocation
- `compress_history(messages, model) -> str` (async, summarizes dropped messages)

#### Phase 1.5 — Long-Term Memory (Layer 3)

Implement `backend/memory/long_term_memory.py`:
- `load(workspace_path) -> str` — reads `.noob-code/memory.md`, returns empty string if not found
- `append(workspace_path, new_notes: str)` — appends bullet points to the file
- `async update_after_task(task, summary, workspace_path, model)` — calls LLM to generate new notes and appends

#### Phase 1.6 — Permissions System (Risk 8)

Implement `backend/permissions.py`:
- `PermissionStore(workspace_path)` — loads/saves `.noob-code/permissions.json`
- `check(action: str) -> str` — returns "always" | "ask" | "deny"
- `set_always(action: str)` — upgrades action to "always" (called when user clicks Allow Always)
- Default levels: `FileRead=always`, `FileWrite=ask`, `ShellExec=ask`, `GitOp=ask`, `NetworkCall=deny`

Write `tests/test_permissions.py` — test all three levels and that `set_always` persists correctly.

#### Phase 1.7 — Codebase Indexer (Risk 4)

Implement `backend/indexer/file_tree.py`:
- `build_file_tree(workspace_path, ignore_file=".noodcodeignore") -> str`
- Parse `.noodcodeignore` exactly like `.gitignore`
- Always-skip list (hardcoded): `node_modules/`, `.venv/`, `__pycache__/`, `.git/`, `dist/`, `build/`

Implement `backend/indexer/signatures.py`:
- `extract_signatures(file_path: str) -> str | None`
- Install tree-sitter grammars for Python, JavaScript, TypeScript, Java, C, C++ at minimum
- Fallback (unsupported language): return first 15 lines of file
- `build_codebase_map(workspace_path, token_counter, max_tokens) -> str` — combines all per-file summaries, truncates to `max_tokens`

#### Phase 1.8 — Git Checkpointing (Risk 7)

Implement `backend/checkpoint.py`:
- `create_checkpoint(workspace_path) -> str | None`
- `list_checkpoints(workspace_path) -> list[str]`
- `restore_latest_checkpoint(workspace_path) -> bool`
- `cleanup_old_checkpoints(workspace_path, keep_last: int)`
- `cleanup_orphaned_containers()` — called on every backend startup

Write `tests/test_checkpoint.py` — test with a temp git repo created via `git init` in `tmp_path`.

#### Phase 1.9 — Wire the Full WebSocket Handler

Flesh out `backend/server.py` `WS /ws` handler to process all message types:

On `{"type": "task"}`:
1. `cleanup_orphaned_containers()`
2. `get_or_create_for_workspace(workspace_path, model)`
3. `load_long_term_memory(workspace_path)` → inject into working memory
4. `build_codebase_map(workspace_path)` → inject into working memory
5. `build_context(token_counter, context_length)` → messages list
6. Start streaming LLM call; yield `token` messages as they arrive
7. On each tool call from `parser.parse_tool_call(content)`:
   - Check `permissions.check(action_type)` — if "ask", send `permission_request`, await response
   - If edit tool: send `edit_request`, await `approval` response
   - Send `tool_start`, execute the tool async, send `tool_result`
   - Create checkpoint before first file write in this task
8. On task completion: send `done`, call `update_after_task`, append messages to session
9. `cleanup_old_checkpoints(workspace_path, keep_last=5)`

On `{"type": "cancel"}`: cancel the running coroutine for that session.

**Phase 1 exit criteria:**
- `python backend/server.py` starts cleanly
- WebSocket connects, version handshake completes
- All 4 new test files pass plus the original 32 = **36+ tests passing**
- Session persists across backend restart
- Permission gates fire and update `permissions.json` correctly
- Token counter correctly trims context when simulated conversation exceeds the budget

---

### Phase 2 — VS Code Extension (Panel + Streaming)

**Goal:** A working sidebar panel that connects to the backend and displays streaming output.

#### Phase 2.1 — Extension Scaffold

Create `vscode-extension/tsconfig.json`:
```json
{
  "compilerOptions": {
    "module": "commonjs",
    "target": "ES2020",
    "outDir": "out",
    "lib": ["ES2020"],
    "sourceMap": true,
    "strict": true,
    "rootDir": "src"
  },
  "exclude": ["node_modules", ".vscode-test"]
}
```

`vscode-extension/src/extension.ts`:
- `activate(context)`:
  1. Read `data/.session_token`
  2. Check `GET http://localhost:7867/health`
  3. If not running: spawn `python backend/server.py` as a child process, redirect stdout to an output channel named "NOOB CODE Backend"
  4. Wait for health endpoint to return `{"warmed_up": true}` (poll with 500ms interval, 30s timeout)
  5. Register all commands from `package.json`
  6. Create `NoobCodePanel` (sidebar webview)
- `deactivate()`: if we own the backend process, kill it

#### Phase 2.2 — Backend Process Management in Extension (Risk 1, extension side)

In `extension.ts` before spawning:
1. Read `data/.daemon.lock`
2. If file exists and PID is alive (try `process.kill(pid, 0)` — no error means alive):
   - Read the port from lockfile
   - Connect to that port (don't spawn)
3. Otherwise: spawn backend, write our PID to the lockfile

#### Phase 2.3 — WebSocket Client

`vscode-extension/src/streaming.ts`:
```typescript
class NoobCodeClient {
  connect(port: number, token: string): void
  disconnect(): void
  sendTask(params: TaskParams): void
  sendApproval(requestId: string, decision: 'approve'|'reject'|'approve_all'): void
  sendPermission(requestId: string, decision: 'allow'|'deny'|'always_allow'): void
  cancel(sessionId: string): void
  on(event: MessageType, callback: (msg: any) => void): void
  off(event: MessageType, callback: (msg: any) => void): void
}
```

Reconnect strategy: exponential backoff (1s, 2s, 4s, 8s, max 30s). After 3 failed reconnects: show VS Code error notification "NOOB CODE backend disconnected. Restarting..."

#### Phase 2.4 — Chat Webview UI

`vscode-extension/webview/panel.html`:
```
┌─────────────────────────────────────────────┐
│ NOOB CODE           [model ▼] [Plan ●] [⚙] │
├─────────────────────────────────────────────┤
│                                             │
│  ┌──────────────────────────────────────┐  │
│  │ 🤖 I will read calc.py first...      │  │
│  │ ▶ read_file ("calc.py")  ▼           │  │
│  │   def add(a, b): return a - b        │  │
│  │ The bug is on line 2: should be +    │  │
│  └──────────────────────────────────────┘  │
│                                             │
│  ┌──────────────────────────────────────┐  │
│  │ You: Fix the add function            │  │
│  └──────────────────────────────────────┘  │
│                                             │
├─────────────────────────────────────────────┤
│ [Type a task... @file to mention a file]    │
│                        [Cancel] [New] [▶]   │
└─────────────────────────────────────────────┘
```

CSS: use VS Code CSS variables (`--vscode-editor-background`, `--vscode-editor-foreground`, `--vscode-button-background`, etc.) so the panel matches whatever VS Code theme the user has.

Message rendering in `panel.js`:
- `token` → append text to the current agent message bubble (streaming effect)
- `tool_start` → insert a collapsible `<details>` block with a spinner inside, keyed by `request_id`
- `tool_result` → fill in the same `<details>` block, remove spinner, collapse by default
- `edit_request` → insert a diff block with [Approve] [Reject] [Approve All] buttons
- `permission_request` → insert an inline permission prompt with [Allow] [Allow Always] [Deny]
- `plan_ready` → insert numbered steps with [Execute Plan] and [Cancel] buttons
- `warning` → yellow notice bar
- `done` → insert a green "✓ Done" chip, re-enable the input
- `error` → red error block

#### Phase 2.5 — Model Dropdown

`vscode-extension/src/models.ts`:
- On panel init: `GET /models` → populate `<select>` dropdown in the webview
- Format: `"qwen2.5-coder:7b (32k ctx, 4.7 GB)"`
- On model change: `POST /settings {"model": "..."}` (backend updates its active model for next task)
- Store selection in VS Code settings `noobCode.defaultModel`

**Phase 2 exit criteria:**
- Extension installs and activates without error
- Sidebar panel opens with chat interface
- User types a task → sees streaming response in panel
- Tool calls show spinner → result block correctly
- Session info shown in panel header (session ID, message count)

---

### Phase 3 — Full Claude Code Feature Parity

#### Phase 3.1 — Edit Approval (Diff Viewer)

`vscode-extension/src/diff.ts`:
- On `edit_request` message:
  1. Write original and proposed content to temp files
  2. Open VS Code diff: `vscode.commands.executeCommand('vscode.diff', originalUri, proposedUri, 'NOOB CODE: calc.py')`
  3. Show [Approve] [Reject] [Approve All] in the webview panel (not the diff editor — keep them in the chat flow)
  4. On [Approve]: close diff, send `approval`, proceed
  5. On [Reject]: close diff, send rejection, agent receives the rejection as a tool error and can try a different approach

Backend change in `orchestrator/tools.py`:
- When permission mode is NOT "yolo": before `write_file`/`edit_file`, generate a unified diff, send `edit_request` over the active WebSocket, await the approval future before writing.

#### Phase 3.2 — Permission Gate UI

`vscode-extension/src/permissions.ts`:
- On `permission_request`: show VS Code information message:
  ```
  NOOB CODE wants to run: pytest -q
  ```
  with buttons [Allow] [Allow Always] [Deny]
- Send the appropriate `permission` response
- "Allow Always" updates local display to indicate that action type won't be asked again

#### Phase 3.3 — Plan Mode

Backend: when `plan_mode: true` in task message:
1. Run a planning prompt: "You are planning a task. List the numbered steps you will take. Do NOT use any tools — only produce the plan."
2. Parse the numbered steps from the response
3. Send `plan_ready` with steps list
4. Enter an async wait for `plan_execute` or `cancel`
5. On `plan_execute`: run the normal tool-calling loop

Extension: on `plan_ready`:
- Show steps as a numbered list with checkboxes (unchecked)
- Show [Execute Plan] and [Cancel] buttons below the steps
- Dim the input box (not accepting new input while plan is pending review)
- On [Execute Plan]: send `plan_execute`, start checking off steps as tool calls complete

#### Phase 3.4 — `@file` Mentions

`panel.js`: detect `@word` patterns in user input:
- Highlight them inline while typing
- On send: expand each `@filename` by calling `GET /resolve_file?name=<filename>&workspace=<path>`
- Backend endpoint walks the workspace, finds the best match (exact name, then fuzzy), returns the full absolute path
- Send the expanded paths along with the task: `"file_mentions": ["/abs/path/to/file.py", ...]`
- Backend reads all mentioned files and adds them to `working_memory.current_file` (or multiple files)

#### Phase 3.5 — "Debug Fix" Command (Keyboard Shortcut)

`noobCode.debugFix` command in `extension.ts`:
1. Get the currently active editor file path
2. Get the active workspace folder
3. Open the NOOB CODE panel (if not already open)
4. Send a task: `"Run tests. If they fail, use debug_fix on <current_file_name> to repair the issue."`
5. Model is pre-filled, session is the active one for this workspace

This makes the `debug_fix` tool accessible with one keyboard shortcut (`Ctrl+Shift+D`) — no typing needed.

**Phase 3 exit criteria:**
- Edit diff appears for every file write (except in yolo mode)
- Permission gates work correctly for ShellExec and GitOp
- Plan mode shows plan, waits for user confirmation, then executes
- Model switcher shows context length and updates the backend
- `@file` mentions correctly attach file content to task context
- `Ctrl+Shift+D` triggers a debug-fix task on the current file

---

### Phase 4 — Memory System Integration Tests

**Goal:** All three memory layers work together end-to-end.

Tests to run/add:
1. Start a session, complete a task → verify `.noob-code/memory.md` updated with relevant notes
2. Restart VS Code (simulate by restarting backend), start new session for same workspace → verify memory.md contents appear in working memory context
3. Have a very long conversation that exceeds context window → verify summarization fires, `warning` message appears, old messages replaced by summary bullet points, agent continues coherently
4. Resume a session after 1 hour → correct messages loaded from SQLite, offered resume prompt
5. Export a session → verify output markdown file contains all messages in readable format

---

### Phase 5 — Large Codebase Support (Indexer Integration)

**Goal:** Agent can navigate any-size repo without context overflow.

Steps:
1. Wire indexer into `backend/server.py`: on every task, run `build_codebase_map(workspace_path, token_counter, CODEBASE_MAP_MAX_TOKENS)` and inject into working memory
2. Test with a large project (e.g., a medium-sized open source Python project) — verify map fits in budget, agent navigates with it
3. Implement `.noodcodeignore` support: place a test `.noodcodeignore` with exclusions, verify excluded dirs don't appear in the codebase map
4. Wire debounced re-indexing on file save (30s cooldown): VS Code extension sends `{"type": "file_changed", "path": "..."}` on file save → backend triggers async re-index
5. Add "Re-index Workspace" command that triggers immediate re-index

---

### Phase 6 — All 10 Risk Verifications

Run the risk verification checklist (see risk mitigations section). Each item becomes a manual test case documented in `tests/risk_verification.md`.

---

### Phase 7 — Setup Script + Documentation

`setup.py` implementation:
```python
#!/usr/bin/env python3
"""NOOB CODE one-time setup script."""
import subprocess, sys, os, json

REQUIRED_PYTHON = (3, 11)

def check(label, cond, fix_msg):
    if not cond:
        print(f"✗ {label}\n  Fix: {fix_msg}")
        sys.exit(1)
    print(f"✓ {label}")

check("Python 3.11+", sys.version_info >= REQUIRED_PYTHON, "Install Python 3.11 or newer")
check("Ollama running", _ollama_reachable(), "Run: ollama serve")
check("Docker running", _docker_reachable(), "Start Docker Desktop")
check("Node.js installed", _node_available(), "Install Node.js 18+ from nodejs.org")

subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
subprocess.check_call(["npm", "install"], cwd="vscode-extension")
subprocess.check_call(["npm", "run", "compile"], cwd="vscode-extension")
subprocess.check_call(["npm", "run", "package"], cwd="vscode-extension")
subprocess.check_call(["code", "--install-extension", "vscode-extension/noob-code.vsix"])

print("\n✓ NOOB CODE installed successfully.")
print("  Reload VS Code (Ctrl+Shift+P → Reload Window) to activate.")
```

Also add `setup.py --update` flag for backend-only updates (re-runs pip install + rebuilds vsix without re-checking prerequisites).

Update `README.md`:
- Remove CLI usage documentation
- Replace with: Prerequisites → Setup → First Use → Configuration → Keyboard shortcuts

---

### Phase 8 — Retire CLI Tools

Once all Phases 1–7 are complete and the extension is confirmed stable:
1. Delete `main.py`
2. Delete `orchestrator_cli.py`
3. Update `README.md` to remove any CLI documentation
4. Run `py -3.11 -m pytest tests/ -q` — verify no tests imported from retired files
5. Commit: `"retire CLI entrypoints: main.py and orchestrator_cli.py — all functionality lives in the VS Code extension"`

---

## Implementation Order Within Each Phase

For every module: implement in this order to avoid working blind:
1. Data models and types (TypedDict, dataclasses, enums)
2. Pure logic (no I/O, no external calls)
3. I/O layer (SQLite, filesystem, subprocess)
4. Unit tests
5. Integration with the layer above

**Never start the next phase until all tests for the current phase pass.**

---

## Testing Strategy

| Test Type | Tool | What It Covers |
|---|---|---|
| Backend unit tests | pytest | session memory, permissions, token counter, checkpoint, working memory, indexer |
| Backend integration | pytest + real SQLite | full WebSocket message sequence with a real FastAPI test client |
| Extension unit tests | `@vscode/test-electron` | WebSocket client, message parsing, settings bridge |
| Extension UI | Manual | diff viewer, permission dialogs, plan mode, model switcher |
| Risk verification | Manual checklist | All 10 risks from the risk verification checklist |

All backend tests must be runnable without VS Code, without Ollama, and without Docker — mock all external calls.

---

## Pending After Phase 8 (Future Enhancements, Not In This Plan)

- **RAG / semantic search:** ChromaDB + `nomic-embed-text` via Ollama for very large codebases. Adds ~3 days of work. Implement after all 8 phases are stable.
- **VS Code Marketplace publication:** requires a verified publisher account at `marketplace.visualstudio.com`. Once polished, publish under the user's account.
- **Multi-file batch diff approval:** show all pending edits as a batch before executing any (Phase 3 does one-at-a-time).
- **Parallel sub-agents:** spawn independent agents for independent file targets. Complex conflict detection needed.
- **Multi-language tree-sitter grammars:** add grammars for Rust, Go, Ruby, PHP as the user base grows beyond Python/JS.
