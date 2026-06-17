# NOOB CODE

A local, fully-featured VS Code coding agent powered by any Ollama model.
Works completely offline on your own hardware — no cloud API, no API keys.

Provides a Claude Code-style interface with:

- Streaming token-by-token responses in a sidebar chat panel
- Edit approval with side-by-side diffs before any file is written
- Shell/git permission gates (ask / auto-approve / yolo modes)
- Plan mode: review numbered steps before the agent executes anything
- Three-layer memory: in-context working memory, SQLite session store, and a per-workspace `memory.md` that persists facts across sessions
- Compact codebase map injected into every prompt so the agent knows what's in the repo
- `@file` mentions in the chat to attach file content to the task
- One-command keyboard shortcuts (`Ctrl+Shift+N` new task, `Ctrl+Shift+D` debug fix)

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | Backend server |
| [Ollama](https://ollama.com) | latest | Must be running locally |
| [Docker](https://www.docker.com/products/docker-desktop/) | latest | Sandbox for shell/test execution |
| [Node.js](https://nodejs.org) | 18+ | Building the VS Code extension |
| VS Code | 1.85+ | Target editor |

Pull a model before first use:
```bash
ollama pull qwen2.5-coder:7b
```

---

## Setup

```bash
git clone <this-repo-url>
cd Self-Debugging-Coding-Agent
python setup.py
```

`setup.py` checks all prerequisites, installs Python dependencies, compiles the TypeScript extension, packages the `.vsix`, and installs it into VS Code automatically.

After setup, reload VS Code (`Ctrl+Shift+P` → **Reload Window**) and click the robot icon in the activity bar.

### Update backend only (after pulling new commits)

```bash
python setup.py --update
```

---

## Usage

1. Open any project folder in VS Code.
2. Click the **NOOB CODE** robot icon in the activity bar to open the chat panel.
3. Type a task and press **Send** (or `Ctrl+Enter`).
4. Use `@filename` in your message to attach a file's content to the task context.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+N` | Open panel / new task |
| `Ctrl+Shift+D` | Debug fix — runs tests on the current file, repairs failures automatically |

### Commands (`Ctrl+Shift+P`)

| Command | Description |
|---|---|
| NOOB CODE: New Task | Open the panel |
| NOOB CODE: Debug Fix Current File | Auto-send a debug-fix task for the active file |
| NOOB CODE: New Session | Start a fresh session (clears chat) |
| NOOB CODE: Export Session to Markdown | Save the conversation to a `.md` file |
| NOOB CODE: Re-index Workspace | Rebuild the codebase map immediately |

---

## Configuration

All settings are available under **Settings → NOOB CODE** or via `noobCode.*` in `settings.json`:

| Setting | Default | Description |
|---|---|---|
| `noobCode.defaultModel` | `qwen2.5-coder:7b` | Ollama model to use |
| `noobCode.backendPort` | `7867` | Port for the local backend server |
| `noobCode.permissionMode` | `ask` | `ask` / `auto-approve` / `yolo` |
| `noobCode.planModeDefault` | `false` | Start every task in plan mode |
| `noobCode.ollamaUrl` | `http://localhost:11434/v1` | Ollama base URL |
| `noobCode.dockerEnabled` | `true` | Use Docker sandbox for code execution |
| `noobCode.maxContextTokens` | `0` | Override context window size (0 = auto-detect) |
| `noobCode.gpuLayers` | `-1` | Ollama GPU layers (-1 = auto) |

Backend constants (override via environment variables, same names as in `config.py`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `PRIMARY_MODEL` | `qwen2.5-coder:7b` | Default model |
| `MAX_ORCHESTRATION_STEPS` | `15` | Max tool-call steps per task |
| `ORCH_SHELL_TIMEOUT` | `60` | Per-command timeout (seconds) |
| `LONG_TERM_MEMORY_MAX_TOKENS` | `500` | Cap on memory.md injected into context |
| `CODEBASE_MAP_MAX_TOKENS` | `2000` | Cap on codebase map in context |
| `CHECKPOINT_KEEP_LAST` | `5` | Number of git stash checkpoints to keep |

---

## How it works

```text
[VS Code Extension — TypeScript]
         ↕  WebSocket  ws://127.0.0.1:7867/ws?token=<session_token>
[FastAPI Backend — Python]
         ↕
[Ollama API] + [Docker Sandbox] + [SQLite] + [File System]
```

- The extension is pure UI — all intelligence is in the backend.
- The backend streams LLM tokens over WebSocket in real time.
- Every task is protected by a git stash checkpoint before the first file write, so a crash mid-edit can be fully rolled back.
- The session token (`data/.session_token`) prevents other local processes from connecting to your backend.

---

## Running tests

```bash
pytest tests/ -v
```

All backend tests run without Ollama, Docker, or VS Code — external calls are mocked.

---

## Known limitations

- **Model planning variance**: 7B-class models sometimes struggle with multi-step tool use — they may retry a failing command without adapting or exhaust the step budget on tasks a larger model finishes quickly. The agent mechanics stay robust; only the model's judgment varies.
- **Windows + Docker Desktop bind-mount I/O** can be significantly slower than native Linux for many-small-file operations inside sandboxed containers, which may cause a command to hit `ORCH_SHELL_TIMEOUT`.
- **Tool-call format**: The parser reads tool calls from the model's text content (not from Ollama's `tool_calls` field), so most instruction-following code models work — not just officially "tools"-capable ones.
