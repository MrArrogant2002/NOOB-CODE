# NOOB CODE

A local AI coding agent for VS Code powered by any [Ollama](https://ollama.com) model.
Works completely offline — no API keys, no cloud.

## Features

- Streaming token-by-token chat in a sidebar panel
- Edit approval with side-by-side diff before any file is written
- Shell / git permission gates (`ask` / `auto-approve` / `yolo`)
- Plan mode — review numbered steps before the agent executes anything
- Three-layer memory: working context, SQLite session store, per-workspace `memory.md`
- Compact codebase map injected into every prompt
- `@file` mentions to attach file content inline
- Auto re-indexes the workspace on every file save (30 s debounce)

## Requirements

| Tool | Version |
| --- | --- |
| [Ollama](https://ollama.com) | latest — must be running |
| Python | 3.11+ |
| [Docker](https://www.docker.com/products/docker-desktop/) | latest |

Pull a model before first use:

```bash
ollama pull qwen2.5-coder:7b
```

## Getting started

Run the setup script from the project root once:

```bash
python setup.py
```

Then reload VS Code (`Ctrl+Shift+P` → **Reload Window**) and click the robot icon.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+Shift+N` | Open panel / new task |
| `Ctrl+Shift+D` | Debug-fix the current file |

## Extension settings

| Setting | Default | Description |
| --- | --- | --- |
| `noobCode.defaultModel` | `qwen2.5-coder:7b` | Ollama model |
| `noobCode.backendPort` | `7867` | Backend server port |
| `noobCode.permissionMode` | `ask` | `ask` / `auto-approve` / `yolo` |
| `noobCode.planModeDefault` | `false` | Start every task in plan mode |
| `noobCode.ollamaUrl` | `http://localhost:11434/v1` | Ollama base URL |
| `noobCode.dockerEnabled` | `true` | Use Docker sandbox for code execution |
| `noobCode.maxContextTokens` | `0` | Context window override (0 = auto) |
| `noobCode.gpuLayers` | `-1` | Ollama GPU layers (-1 = auto) |

## Privacy

All processing happens on your local machine. No data leaves your computer.
