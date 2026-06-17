# Self-Debugging Coding Agent

A local, model-agnostic coding agent built on Ollama. It ships two entrypoints:

- **`main.py`** — a single-problem agent: generate code for a problem, run it in a sandboxed Docker container, classify the failure into one of 5 categories (SyntaxError, RuntimeError, LogicError, TimeoutError, ImportError), apply a targeted repair prompt per category, and loop until it passes or hits a max-iteration budget. Every iteration is logged to SQLite.
- **`orchestrator_cli.py`** — a scoped, repo-aware coding agent (a small Claude-Code-style loop): the model calls tools (read/write/edit files, run shell commands and tests inside a sandboxed container, git diff/status) to accomplish a task against a real repository, including a `debug_fix` tool that reuses the same classification-guided repair logic targeted at a real file.

Everything runs against a **local** Ollama model — no cloud LLM API is used anywhere in this project.

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed and running locally
- [Docker](https://www.docker.com/products/docker-desktop/) installed and running (used to sandbox all code execution — the agent never uses `eval()`/`exec()` directly)
- A pulled Ollama model with decent code/tool-use ability, e.g.:
  ```bash
  ollama pull qwen2.5-coder:7b
  ```

## Setup

```bash
git clone <this-repo-url>
cd Self-Debugging-Coding-Agent
pip install -r requirements.txt
```

No API keys or secrets are required anywhere in this project.

## Configuration

All settings in [config.py](config.py) can be overridden by an environment variable of the same name — no code edits needed to point this at a different Ollama host or model:

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint. Change this if Ollama runs on a different host/port. |
| `PRIMARY_MODEL` | `qwen2.5-coder:7b` | Default model for generation/repair (also overridable per-run via `--model`). |
| `FALLBACK_MODEL` | `codellama:7b` | Used by `main.py` if the primary model call fails. |
| `MAX_ITERATIONS` | `5` | Max repair iterations for the single-problem agent. |
| `TIMEOUT_SECONDS` | `10` | Execution timeout for the single-problem agent's judge sandbox. |
| `DOCKER_IMAGE` | `python:3.11-slim` | Sandbox base image. |
| `DOCKER_MEMORY_LIMIT` | `256m` | Sandbox container memory cap. |
| `MAX_ORCHESTRATION_STEPS` | `15` | Max tool-call steps for the orchestrator. |
| `ORCH_SHELL_TIMEOUT` | `60` | Per-command timeout for the orchestrator's shell/test tools. |

Example:
```bash
export OLLAMA_BASE_URL=http://192.168.1.50:11434/v1
export PRIMARY_MODEL=qwen2.5-coder:14b
```

**Model requirement:** the orchestrator's tool-calling does not rely on Ollama's structured `tool_calls` response field — it parses tool calls directly out of the model's text output (see [orchestrator/parser.py](orchestrator/parser.py)), since that field has been observed to stay empty even for models that advertise tool-calling support. This means most instruction-following code models work, not just ones Ollama lists as officially "tools"-capable — but small/weak models will plan less reliably in multi-step tool use than larger ones.

## Usage

### Single-problem agent
```bash
python main.py --problem "Print the sum of integers 1 to 10 inclusive." --expected "55"
```
Prints iteration-by-iteration progress, the final code, and (on success) generated pytest tests. Every iteration is logged to `data/logs.db`.

### Repo-aware orchestrator
```bash
python orchestrator_cli.py --repo /path/to/some/project --task "Run the test suite and fix any failing tests."
```
Flags: `--model`, `--max-steps`, `--allow-test-edits` (off by default — the agent cannot modify test files unless this is passed, so it can't make a failing test pass by weakening the test instead of fixing the bug).

By default, `run_shell`/`run_tests`/`debug_fix` execute inside a Docker container with your repo bind-mounted (network enabled, so the agent can `pip install`/`npm install` real dependencies) — not your host shell directly.

### Benchmarks (HumanEval / MBPP)
```python
from eval.benchmark import run_benchmark
run_benchmark("humaneval", limit=10)
```
Downloads the dataset to `data/` on first use and prints pass@1 (and pass@5 if `num_samples >= 5`).

## Running tests

```bash
pytest tests/ -v
```
All tests mock the LLM and Docker calls, so the suite runs without Ollama or Docker available.

## Known limitations

- **Model planning variance**: small local models (7B-class) sometimes flounder in multi-step tool use — hallucinating a tool name, retrying a failing command without adapting, or needing the full step budget for tasks that a larger model finishes in a few steps. The orchestrator's mechanics (error reporting, container cleanup, step budget) stay robust in every case observed; only the model's judgment varies run to run.
- **No automatic model fallback in the orchestrator** (unlike `main.py`, which falls back from `PRIMARY_MODEL` to `FALLBACK_MODEL` on API failure).
- **Windows + Docker Desktop bind-mount I/O** can be significantly slower than native Linux for many-small-file operations (e.g. creating a virtualenv inside the sandboxed container) — this can cause an otherwise-fine command to hit `ORCH_SHELL_TIMEOUT`.
