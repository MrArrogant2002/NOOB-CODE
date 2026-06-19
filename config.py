"""Global configuration constants for the self-debugging code agent.

All tunable values live here so experiments are reproducible from a single
source instead of being scattered as magic numbers across modules. Every
value can be overridden by an environment variable of the same name, so a
fresh clone can point at a different Ollama host/model without code edits.
"""

import os

MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "5"))
TIMEOUT_SECONDS = int(os.environ.get("TIMEOUT_SECONDS", "10"))
PRIMARY_MODEL = os.environ.get("PRIMARY_MODEL", "qwen2.5-coder:7b")
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "codellama:7b")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
DOCKER_IMAGE = os.environ.get("DOCKER_IMAGE", "python:3.11-slim")
DOCKER_MEMORY_LIMIT = os.environ.get("DOCKER_MEMORY_LIMIT", "256m")
DB_PATH = os.environ.get("DB_PATH", "data/logs.db")

# Orchestrator (repo-scoped coding agent)
MAX_ORCHESTRATION_STEPS = int(os.environ.get("MAX_ORCHESTRATION_STEPS", "15"))
ORCH_SHELL_TIMEOUT = int(os.environ.get("ORCH_SHELL_TIMEOUT", "60"))

# NOOB CODE backend server
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "7867"))
BACKEND_HOST = os.environ.get("BACKEND_HOST", "127.0.0.1")
BACKEND_API_VERSION = "1"
BACKEND_VERSION = "0.1.0"
SESSION_TOKEN_PATH = os.environ.get("SESSION_TOKEN_PATH", "data/.session_token")
DAEMON_LOCK_PATH = os.environ.get("DAEMON_LOCK_PATH", "data/.daemon.lock")

# Memory system
LONG_TERM_MEMORY_MAX_TOKENS = int(os.environ.get("LONG_TERM_MEMORY_MAX_TOKENS", "500"))
WORKING_MEMORY_SLIDING_WINDOW = int(
    os.environ.get("WORKING_MEMORY_SLIDING_WINDOW", "10")
)
# How many past session messages to feed back as cross-task conversation context
CONVERSATION_HISTORY_MESSAGES = int(
    os.environ.get("CONVERSATION_HISTORY_MESSAGES", "8")
)

# Codebase indexer
INDEXER_MAX_FILE_SIZE_BYTES = int(
    os.environ.get("INDEXER_MAX_FILE_SIZE_BYTES", str(100 * 1024))
)
CODEBASE_MAP_MAX_TOKENS = int(os.environ.get("CODEBASE_MAP_MAX_TOKENS", "2000"))

# Git checkpointing
CHECKPOINT_KEEP_LAST = int(os.environ.get("CHECKPOINT_KEEP_LAST", "5"))
