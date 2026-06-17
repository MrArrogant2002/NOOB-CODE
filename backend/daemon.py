"""Single-instance lock, session token, and model warm-up for the NOOB CODE backend."""

import json
import logging
import os
import secrets

from openai import AsyncOpenAI, OpenAIError

from config import (
    BACKEND_API_VERSION,
    BACKEND_VERSION,
    DAEMON_LOCK_PATH,
    OLLAMA_BASE_URL,
    PRIMARY_MODEL,
    SESSION_TOKEN_PATH,
)

logger = logging.getLogger(__name__)

API_VERSION = BACKEND_API_VERSION
SERVER_VERSION = BACKEND_VERSION


def acquire_or_connect(port: int) -> tuple[bool, int]:
    """Check whether another backend instance is already running.

    Returns (is_owner, actual_port).
    If a live instance exists, returns (False, its_port) — caller should
    connect to that port instead of spawning a new process.
    If no live instance, claims the port by writing the lockfile.
    """
    if os.path.exists(DAEMON_LOCK_PATH):
        try:
            with open(DAEMON_LOCK_PATH) as f:
                data = json.load(f)
            pid = int(data["pid"])
            existing_port = int(data.get("port", port))
            try:
                os.kill(pid, 0)  # raises if PID is dead
                logger.info("Existing backend on port %s (PID %s)", existing_port, pid)
                return False, existing_port
            except (ProcessLookupError, PermissionError):
                pass  # stale lockfile — fall through and claim it
        except (json.JSONDecodeError, KeyError, OSError, ValueError):
            pass

    os.makedirs(os.path.dirname(DAEMON_LOCK_PATH) or ".", exist_ok=True)
    with open(DAEMON_LOCK_PATH, "w") as f:
        json.dump({"pid": os.getpid(), "port": port}, f)
    return True, port


def release_lock() -> None:
    """Remove the lockfile on clean shutdown."""
    try:
        os.remove(DAEMON_LOCK_PATH)
    except OSError:
        pass


def get_or_create_session_token() -> str:
    """Return the persistent session token, generating one on first run.

    The token is written to SESSION_TOKEN_PATH so the VS Code extension can
    read it and include it as a query parameter on every WebSocket connection.
    """
    if os.path.exists(SESSION_TOKEN_PATH):
        with open(SESSION_TOKEN_PATH) as f:
            token = f.read().strip()
        if token:
            return token

    os.makedirs(os.path.dirname(SESSION_TOKEN_PATH) or ".", exist_ok=True)
    token = secrets.token_hex(32)
    with open(SESSION_TOKEN_PATH, "w") as f:
        f.write(token)
    logger.info("Generated new session token at %s", SESSION_TOKEN_PATH)
    return token


async def warm_up_model(
    model: str = PRIMARY_MODEL, base_url: str = OLLAMA_BASE_URL
) -> bool:
    """Send a trivial prompt to pre-load the model into Ollama's VRAM/RAM cache.

    Called as a background asyncio task at server startup so the first real
    user request does not block 5-30 s on model loading.
    """
    client = AsyncOpenAI(base_url=base_url, api_key="ollama")
    try:
        await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        logger.info("Model %s warmed up", model)
        return True
    except OpenAIError as exc:
        logger.warning("Warm-up failed (non-fatal): %s", exc)
        return False
