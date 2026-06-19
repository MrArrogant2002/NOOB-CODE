# NOOB CODE — Complete Technical Report

**Project:** Self-Debugging-Coding-Agent  
**Stack:** Python 3.11 · FastAPI · Ollama · Docker · TypeScript · VS Code Extension API  
**Date:** 2026-06-17  

---

## 1. What This Project Is

NOOB CODE is a **local, offline AI coding agent** that runs entirely on your own machine. It integrates directly into VS Code as a sidebar extension and uses any Ollama model (no cloud API, no API keys) to read files, write code, run tests, and fix bugs autonomously — with human approval gates before any destructive action.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│              VS Code Extension (TypeScript)          │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ panel.ts │  │streaming │  │  extension.ts     │  │
│  │ (sidebar │  │   .ts    │  │  (activation,     │  │
│  │  webview)│  │(WS client│  │   commands,       │  │
│  └────┬─────┘  └────┬─────┘  │   backend spawn)  │  │
│       │              │        └───────────────────┘  │
│       └──────────────┘                               │
│              │ postMessage / WebSocket                │
└──────────────┼──────────────────────────────────────┘
               │ ws://127.0.0.1:7867/ws?token=<hex>
┌──────────────┼──────────────────────────────────────┐
│              ▼  FastAPI Backend (Python)              │
│  ┌───────────────────────────────────────────────┐  │
│  │             backend/server.py                  │  │
│  │  • Authenticates WS token                     │  │
│  │  • Dispatches task messages to _run_task()    │  │
│  │  • Streams LLM tokens back over WS            │  │
│  │  • Manages interactive gates (edit/perm/plan) │  │
│  └───┬──────────┬──────────┬──────────┬──────────┘  │
│      │          │          │          │              │
│  ┌───▼──┐  ┌───▼──┐  ┌───▼──┐  ┌───▼──────────┐   │
│  │Ollama│  │Docker│  │SQLite│  │  File System  │   │
│  │ API  │  │Sandbox│ │  DB  │  │ (workspace)   │   │
│  └──────┘  └──────┘  └──────┘  └──────────────┘   │
└─────────────────────────────────────────────────────┘
```

Every component runs locally. Nothing ever leaves the machine.

---

## 3. Startup Sequence (What Happens When VS Code Opens)

### 3.1 Extension Activation (`extension.ts`)

The extension activates on `onStartupFinished` (after VS Code UI is fully loaded).

**Step 1 — Immediate UI registration:**
```
activate() called
  → create "NOOB CODE Backend" output channel
  → register WebviewViewProvider (sidebar panel) immediately
  → register all commands (noobCode.newTask, reindex, etc.)
  → register file-save listener for debounced reindex
```
The sidebar is available to click *before* the backend starts. It shows a "connecting…" state.

**Step 2 — Background backend startup (async, non-blocking):**
```
void (async () => {
  checkHealth(port)           ← 1.5 s timeout HTTP GET /health
  if not running:
    startBackend()            ← spawn Python uvicorn process
    waitForHealth(30 s)       ← poll /health every 500 ms
  readSessionToken()          ← read data/.session_token from backendRoot
  client.connect(port, token) ← open WebSocket
})()
```

**Step 3 — `startBackend()` details:**
- Reads `noobCode.backendRoot` from VS Code user settings (written by `setup.py`)
- Finds `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python3` (Linux/macOS)
- Spawns: `<venv_python> -m uvicorn backend.server:app --host 127.0.0.1 --port 7867`
- Working directory: the project root (the NOOB CODE repo, not the user's workspace)
- All stdout/stderr piped to "NOOB CODE Backend" output channel

### 3.2 Backend Startup (`server.py` lifespan)

When uvicorn starts the FastAPI app:
```python
cleanup_orphaned_containers()    # kill selfdebug-orch-* Docker containers from crashes
_SESSION_TOKEN = get_or_create_session_token()  # read/create data/.session_token
_ASYNC_CLIENT = AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
asyncio.create_task(_warm())     # fire dummy 1-token request to pre-load model
```

The warm-up runs in the background. `/health` returns `warmed_up: false` until it completes.

---

## 4. WebSocket Protocol

Every message is JSON. Connection URL: `ws://127.0.0.1:7867/ws?token=<32-byte-hex>`

### 4.1 Authentication & Handshake

```
Client connects → token checked against data/.session_token
  Bad token → server closes with code 4001 (Unauthorized), extension shows error
  Good token → server sends:
    {"type": "hello", "api_version": "1", "backend_version": "0.1.0"}
  Client responds:
    {"type": "hello_ack", "api_version": "1"}
  Version mismatch → server sends error + closes connection
```

### 4.2 Messages: Extension → Backend

| Message type | Purpose | Key fields |
|---|---|---|
| `task` | Send a user task to the agent | `task`, `workspace`, `model`, `plan_mode`, `permission_mode`, `session_id`, `file_mentions` |
| `cancel` | Cancel the running task | `session_id` |
| `approval` | User approved/rejected a file edit | `request_id`, `decision` (`approve`/`reject`/`approve_all`) |
| `permission` | User allowed/denied a shell action | `request_id`, `decision` (`allow`/`deny`/`always_allow`) |
| `plan_execute` | User clicked "Execute Plan" in plan mode | — |
| `list_models` | Request the Ollama model list | — |
| `reindex` | Rebuild codebase map immediately | `workspace` |
| `file_changed` | File saved — trigger debounced reindex | `path`, `workspace` |
| `get_history` | Load past session messages | `session_id` |
| `export_session` | Save session to Markdown file | `output_path` |

### 4.3 Messages: Backend → Extension → Webview

| Message type | Purpose | Key fields |
|---|---|---|
| `hello` | Initial handshake | `api_version`, `backend_version` |
| `session_info` | Session ID for this task | `session_id`, `resumed`, `message_count` |
| `token` | One streamed LLM text token | `content` |
| `tool_start` | Agent is executing a tool | `request_id`, `name`, `args` |
| `tool_result` | Tool execution complete | `request_id`, `name`, `result` |
| `edit_request` | Agent wants to write a file (awaits approval) | `request_id`, `path`, `diff`, `new_content` |
| `permission_request` | Agent wants to run shell/git (awaits allow/deny) | `request_id`, `action`, `command` |
| `plan_ready` | Plan mode plan shown (awaits execute) | `steps` (list of strings) |
| `done` | Task finished | `final_answer` |
| `warning` | Non-fatal warning (e.g. context nearing limit) | `message` |
| `error` | Fatal task error | `message` |
| `info` | Informational notice | `message` |
| `models_list` | Ollama model list response | `models` (list of `{name}`) |

---

## 5. Task Execution Flow (`_run_task`)

When the user sends a message, this is what happens inside the backend:

```
1. get_or_create_for_workspace(workspace, model)
       → SQLite: find session < 24 h old for this workspace
       → if found: resume it (is_resumed=True)
       → if not: create new session
   send session_info to client

2. load_ltm(workspace)
       → read <workspace>/.noob-code/memory.md
       → cap at 500 tokens (most recent tail kept)

3. _reindex_workspace(workspace)  [if not already cached]
       → build_file_tree(): walk workspace, skip node_modules/.git/etc.
       → build_codebase_map(): extract function/class signatures
       → store in _index_cache[workspace]

4. WorkingMemory.build_context(context_length)
       → assemble messages list:
           [system prompt + ltm notes + codebase map]
           + [task plan if plan mode]
           + [current file if set]
           + [recent conversation (sliding window, oldest dropped first)]

5. ORCHESTRATION LOOP (up to MAX_ORCHESTRATION_STEPS=15):

   a. _stream_llm(messages, model)
          → POST to Ollama /v1/chat/completions (streaming)
          → stream text tokens → send {"type":"token","content":"..."} over WS
          → if model uses native tool_calls instead of text:
              collect tool_call deltas, convert to JSON text for parser
          → return full content string

   b. parse_tool_call(content)
          → look for <tool_call>…</tool_call> in text
          → fall back to ```json ... ``` code fence
          → fall back to bare JSON object with "name" + "arguments"
          → return ToolCall(name, arguments) or None

   c. if call is None or call.name == "finish":
          → send {"type":"done","final_answer":...}
          → exit loop

   d. Permission check:
          FileRead   → always allowed
          FileWrite  → ask mode: send edit_request, AWAIT user approval
          ShellExec  → ask mode: send permission_request, AWAIT allow/deny
          GitOp      → ask mode: send permission_request, AWAIT allow/deny
          NetworkCall→ always denied

   e. if file write: create git stash checkpoint (once per task)

   f. _dispatch(toolbox, call.name, call.arguments)
          → run the tool (read_file / write_file / edit_file /
            run_shell / run_tests / debug_fix / git_diff / git_status)
          → shell tools use Docker container (created lazily on first use)
          → send tool_start + tool_result over WS

   g. memory.add_exchange(content, result_text)
          → append to sliding window

6. After loop: update_after_task(task, summary, workspace, model)
       → ask LLM to write 1-3 bullet notes about the task
       → append to .noob-code/memory.md
```

---

## 6. Three-Layer Memory System

### Layer 1 — Working Memory (in-context, per-task)

**File:** `backend/memory/working_memory.py`  
**Class:** `WorkingMemory`

Assembled fresh every LLM call. Priority budget allocation (highest = last truncated):

| Priority | Layer | Cap |
|---|---|---|
| 1 (never cut) | System prompt | — |
| 2 | Long-term notes | 500 tokens |
| 3 | Codebase map | 2000 tokens |
| 4 | Task plan (plan mode) | fits or dropped |
| 5 | Current file content | 30% of remaining budget |
| 6 | Recent conversation | Sliding window, oldest pair dropped first |

Sliding window hard cap: `WORKING_MEMORY_SLIDING_WINDOW * 2 = 20` entries. When full, oldest assistant+tool_response pair is dropped.

`needs_compression()` returns `True` when the built context exceeds 80% of the model's context length — triggers a warning message to the user.

### Layer 2 — Session Memory (SQLite, per-workspace)

**File:** `backend/memory/session_memory.py`  
**Database:** `data/sessions.db`

Schema:
```sql
CREATE TABLE sessions (
    session_id     TEXT PRIMARY KEY,
    workspace_path TEXT NOT NULL,
    model          TEXT NOT NULL,
    messages       TEXT NOT NULL DEFAULT '[]',  -- JSON array
    created_at     TEXT NOT NULL,
    last_active    TEXT NOT NULL
)
```

- Sessions are keyed by `workspace_path`
- If `last_active` < 24 hours ago: session is **resumed** (conversation continues)
- If > 24 hours: **new session** created
- Messages appended after each task via `append_message()`
- Exportable to Markdown via `export_to_markdown()`

### Layer 3 — Long-Term Memory (file, per-workspace, permanent)

**File:** `backend/memory/long_term_memory.py`  
**Location in workspace:** `.noob-code/memory.md`

After every completed task, the LLM is asked to distil 1–3 bullet points:
- Code conventions it discovered
- Important decisions made
- Constraints to remember

These accumulate across restarts and sessions. On next task, the most recent 500 tokens are injected into the system prompt under `## Project Memory`.

---

## 7. Codebase Indexer

**Files:** `backend/indexer/file_tree.py`, `backend/indexer/codebase_map.py`, `backend/indexer/signatures.py`

### 7.1 File Tree (`build_file_tree`)

Walks the workspace with `os.walk`. Always skips:

**Directories:** `node_modules`, `.venv`, `venv`, `__pycache__`, `.git`, `dist`, `build`, `.next`, `.nuxt`, `target`, `.gradle`, `.idea`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `__mocks__`, `coverage`, `.nyc_output`, `.tox`, any dir starting with `.`

**File extensions:** `.pyc`, `.pyo`, `.pyd`, `.min.js`, `.min.css`, `.map`, `.whl`, `.egg-info`, `.lock`

Respects `.noodcodeignore` (gitignore-format) in the workspace root. Truncates at 500 files.

### 7.2 Codebase Map (`build_codebase_map`)

For each file in the tree, extracts top-level signatures using regex patterns. Caps total output at `CODEBASE_MAP_MAX_TOKENS = 2000` tokens. Supports: Python, JavaScript, TypeScript, Java, C, C++. Falls back to filename-only for unsupported types.

### 7.3 Cache & Debounced Reindex

```python
_index_cache: dict[str, str] = {}      # workspace → codebase_map
_debounce_tasks: dict[str, asyncio.Task] = {}  # pending reindex tasks
```

- Built on first task for a workspace
- Rebuilt immediately on `reindex` message
- Rebuilt after 30 s debounce on every `file_changed` message (file save in VS Code)

---

## 8. Permission System

**File:** `backend/permissions.py`  
**Per-workspace config:** `.noob-code/permissions.json`

Five action categories with three levels each:

| Action | Default level | Meaning |
|---|---|---|
| `FileRead` | `always` | Auto-approve, no prompt |
| `FileWrite` | `ask` | Show diff, await user Approve/Reject |
| `ShellExec` | `ask` | Show command, await Allow/Deny |
| `GitOp` | `ask` | Show command, await Allow/Deny |
| `NetworkCall` | `deny` | Always rejected, no prompt |

**Global override modes** (set via `noobCode.permissionMode`):
- `ask` — per-action gates as above (default)
- `auto-approve` — skip all interactive gates, run everything automatically
- `yolo` — skip gates AND skip edit diffs

**"Allow Always"** — clicking this upgrades an action to `"always"` and saves it to `permissions.json`. Subsequent tasks with that action type skip the prompt.

---

## 9. Interactive Gates (How the Agent Waits for User Input)

When the agent needs approval, the backend uses an `asyncio.Future` to block the task coroutine until the user responds:

```python
# 1. Create a Future and store it
fut = asyncio.get_event_loop().create_future()
conn.pending[request_id] = fut

# 2. Send the gate message to the client
await _send(websocket, {"type": "edit_request", "request_id": request_id, ...})

# 3. BLOCK here — the task coroutine suspends
result = await asyncio.wait_for(fut, timeout=300.0)

# 4. When user clicks Approve/Reject in the webview:
#    The WS message handler calls fut.set_result(msg)
#    The task coroutine resumes here
```

The event loop keeps processing other WebSocket messages (like `approval`, `permission`, `cancel`) while the task is suspended. This is why the UI stays responsive.

Three gate types:
- **Edit gate** — `edit_request` / `approval` — shows a unified diff
- **Permission gate** — `permission_request` / `permission` — shows the command
- **Plan gate** — `plan_ready` / `plan_execute` — shows numbered plan steps

---

## 10. Git Checkpointing

**File:** `backend/checkpoint.py`

Before the **first file write** in any task, the backend creates a git stash:
```bash
git stash push -u -m "noob-code checkpoint <ISO-timestamp>"
```

This captures the entire workspace state (including untracked files via `-u`). If the agent crashes mid-task, the user can run `git stash pop` to restore the pre-task state.

Only the most recent `CHECKPOINT_KEEP_LAST = 5` checkpoints are kept. Older ones are dropped automatically.

On every backend startup, `cleanup_orphaned_containers()` kills any Docker containers named `selfdebug-orch-*` that were left running from a previous crash.

---

## 11. Docker Sandbox

**File:** `orchestrator/tools.py` — `DockerSession` class

Shell commands (`run_shell`, `run_tests`) execute inside a Docker container:
```bash
docker run -d --rm --name selfdebug-orch-<uuid12> \
  -v <workspace>:/workspace \
  -w /workspace \
  --memory 256m \
  python:3.11-slim \
  tail -f /dev/null
```

The container is created **lazily** on the first shell call. Pure file-editing tasks pay zero Docker startup cost. Commands run as:
```bash
docker exec <container> timeout 60s sh -c "<command>"
```

The container is destroyed on task completion via `toolbox.close()`.

---

## 12. VS Code Extension Structure

```
vscode-extension/
├── src/
│   ├── extension.ts    — activate(), startBackend(), WebSocket lifecycle
│   ├── streaming.ts    — NoobCodeClient: WS connect, send, reconnect backoff
│   ├── panel.ts        — NoobCodePanel: WebviewViewProvider, message routing
│   ├── diff.ts         — In-memory diff content provider for VS Code diff editor
│   ├── permissions.ts  — showPermissionPopup() VS Code notification
│   └── settings.ts     — readSettings() helper
├── webview/
│   ├── panel.html      — Sidebar HTML shell
│   ├── panel.css       — Dark-theme chat styles
│   └── panel.js        — All chat UI logic (no framework, plain JS)
├── package.json        — Extension manifest, commands, keybindings, settings
├── tsconfig.json
├── LICENSE
└── README.md
```

### 12.1 WebSocket Reconnection (`streaming.ts`)

Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s (6 attempts).  
Close code `4001` (auth failure) does NOT trigger retry — shows an error instead.  
After 6 failed attempts, shows "Backend disconnected after multiple retries" notification.

### 12.2 Model Listing Bug (Fixed)

The backend's `list_models` handler was sending `{"models": [...]}` over WebSocket without a `"type"` field. The webview listener checks `msg.type === "models_list"`, so it never fired. Fixed: handler now sends `{"type": "models_list", "models": [...]}`.

### 12.3 Tool Call Silence Bug (Fixed)

`_stream_llm` was using `.text_stream` from the OpenAI SDK's high-level streaming API. When `qwen2.5-coder:7b` responds with a native `tool_calls` field instead of text content, `.text_stream` yields nothing → `content = ""` → orchestration loop exits after step 1. Fixed: now uses raw `chat.completions.create(stream=True)` and collects BOTH `delta.content` (text) AND `delta.tool_calls` (native structured response), converting native tool_calls to the JSON text format that `parse_tool_call()` already handles.

---

## 13. Tool Call Parsing (`orchestrator/parser.py`)

The agent uses a three-pass permissive parser so models don't need to follow a strict format:

**Pass 1:** Look for `<tool_call>…</tool_call>` XML tags (Ollama's standard format when `tools=` is passed)  
**Pass 2:** Look for ` ```json … ``` ` fenced code blocks  
**Pass 3:** Try to parse the entire response as a JSON object  
**Fallback:** Scan for the first balanced `{…}` substring and try to parse it

In all cases it looks for a dict with `"name"` and `"arguments"` keys. If found, returns `ToolCall(name, arguments)`. If nothing parses, returns `None` → treated as a plain text answer → `finish` is called.

---

## 14. Available Tools

| Tool | Category | What it does |
|---|---|---|
| `read_file` | FileRead | Read file contents by relative path |
| `list_dir` | FileRead | List directory contents |
| `write_file` | FileWrite | Create/overwrite a file entirely |
| `edit_file` | FileWrite | Replace one unique substring in a file |
| `debug_fix` | FileWrite | Run tests; if they fail, classify + repair the file |
| `run_shell` | ShellExec | Run arbitrary shell command in Docker sandbox |
| `run_tests` | ShellExec | Run `pytest -q` (or custom command) in Docker sandbox |
| `git_diff` | GitOp | Show uncommitted diff |
| `git_status` | GitOp | Show `git status --short` |
| `finish` | — | Signal task complete with a summary |

Test files are **protected** by default: `write_file` and `edit_file` refuse to touch `test_*.py`, `*_test.py`, or anything under `tests/`. The agent must fix the implementation instead.

`debug_fix` uses the `agent/classifier.py` + `agent/repairer.py` pipeline to classify the error type and apply a targeted repair — the same mechanism as the standalone self-debugging agent this project originally implemented.

---

## 15. Configuration Reference

All values are read from environment variables; defaults shown.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama API endpoint |
| `PRIMARY_MODEL` | `qwen2.5-coder:7b` | Default model |
| `FALLBACK_MODEL` | `codellama:7b` | Fallback model |
| `MAX_ORCHESTRATION_STEPS` | `15` | Max tool-call steps per task |
| `ORCH_SHELL_TIMEOUT` | `60` | Per-command timeout (seconds) |
| `BACKEND_PORT` | `7867` | WebSocket server port |
| `SESSION_TOKEN_PATH` | `data/.session_token` | Auth token file |
| `DAEMON_LOCK_PATH` | `data/.daemon.lock` | Single-instance lockfile |
| `LONG_TERM_MEMORY_MAX_TOKENS` | `500` | Cap on memory.md injected into context |
| `WORKING_MEMORY_SLIDING_WINDOW` | `10` | Max exchange pairs in working memory |
| `CODEBASE_MAP_MAX_TOKENS` | `2000` | Cap on codebase map in context |
| `CHECKPOINT_KEEP_LAST` | `5` | Number of git stash checkpoints to keep |
| `DOCKER_IMAGE` | `python:3.11-slim` | Docker sandbox image |
| `DOCKER_MEMORY_LIMIT` | `256m` | Container memory cap |

VS Code settings (set in Settings UI or `settings.json`):

| Setting | Default | Purpose |
|---|---|---|
| `noobCode.backendRoot` | `""` | Absolute path to NOOB CODE project dir (set by setup.py) |
| `noobCode.defaultModel` | `qwen2.5-coder:7b` | Ollama model |
| `noobCode.backendPort` | `7867` | Backend port |
| `noobCode.permissionMode` | `ask` | `ask` / `auto-approve` / `yolo` |
| `noobCode.planModeDefault` | `false` | Start every task in plan mode |
| `noobCode.ollamaUrl` | `http://localhost:11434/v1` | Ollama URL |
| `noobCode.dockerEnabled` | `true` | Use Docker sandbox |
| `noobCode.maxContextTokens` | `0` | Override context length (0 = auto) |
| `noobCode.gpuLayers` | `-1` | Ollama GPU layers |

---

## 16. Setup Flow (`setup.py`)

```
python setup.py
  1. check_python()         — Python 3.11+
  2. check_ollama()         — GET http://localhost:11434/api/tags
  3. check_docker()         — docker info
  4. check_node()           — node --version
  5. check_vscode_cli()     — which code
  6. install_python_deps()  — pip install -r requirements.txt
  7. build_extension()
       → npm install        (in vscode-extension/)
       → npm run compile    (tsc -p ./)
       → npm run package    (npx vsce package)
  8. install_extension()
       → code --install-extension noob-code-0.1.0.vsix
  9. write_vscode_setting("noobCode.backendRoot", str(ROOT))
       → writes to ~/AppData/Roaming/Code/User/settings.json (Windows)
       → writes to ~/.config/Code/User/settings.json (Linux)
       → writes to ~/Library/Application Support/Code/User/settings.json (macOS)
```

`python setup.py --update` skips steps 1–5 (no prereq checks).

---

## 17. Data Directory Layout

```
data/
├── .session_token    — 32-byte hex auth token (git-ignored)
├── .daemon.lock      — JSON: {"pid": <int>, "port": <int>}
├── sessions.db       — SQLite: conversation sessions
└── logs.db           — SQLite: legacy benchmark logs (not used by extension)

<user's workspace>/
└── .noob-code/
    ├── memory.md         — Long-term memory notes (appended by LLM after each task)
    ├── permissions.json  — Per-action permission levels
    └── (git-ignored by .noodcodeignore)
```

---

## 18. Test Suite

```
tests/
├── test_token_counter.py     — tiktoken token counting
├── test_session_memory.py    — SQLite session CRUD + 24h resume logic
├── test_permissions.py       — PermissionStore defaults, set/get, persist
├── test_checkpoint.py        — git stash create/restore/cleanup (real git, 8 tests, ~5 min)
├── test_indexer.py           — build_file_tree + build_codebase_map (11 tests)
├── test_memory_integration.py — All 3 memory layers end-to-end (18 tests)
└── risk_verification.md      — Manual test procedures for 10 identified risks
```

**Run:** `pytest tests/ -v` — all tests except `test_checkpoint.py` complete in under 10 seconds. Checkpoint tests take ~5 minutes because they use real git stash operations.

No external services are required — Ollama, Docker, and VS Code are all mocked.

---

## 19. Known Issues & Current Status

| Issue | Status |
|---|---|
| Models dropdown empty | Fixed — `list_models` WS response was missing `"type": "models_list"` |
| Agent silent on first message | Fixed — `_stream_llm` now handles native `tool_calls` + text content |
| No error shown on task crash | Fixed — `_run_task` now has `except Exception` that sends error to webview |
| `session_info` not sent on first task | Fixed — always sent now, not only on session resume |
| Extension installed but panel blank | Fixed — panel now registers immediately; backend starts in background |
| Token mismatch / auth loops | Fixed — `readSessionToken` now uses `backendRoot` setting, not `extensionPath` |
| `npm` not found on Windows | Fixed — `_resolve_cmd()` in setup.py tries `npm.cmd` on Win32 |
| LICENSE missing in .vsix | Fixed — LICENSE copied to `vscode-extension/` |
| README missing in extension info | Fixed — `vscode-extension/README.md` created |
