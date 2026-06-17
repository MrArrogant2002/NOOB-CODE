"""Long-term memory stored as .noob-code/memory.md in the workspace root.

Survives across sessions. The agent reads it at session start to recall
past decisions and appends compact notes after each task, building a
growing knowledge base about the project's conventions and constraints.
"""

import logging
from pathlib import Path

import tiktoken

from config import LONG_TERM_MEMORY_MAX_TOKENS

logger = logging.getLogger(__name__)

_MEMORY_FILE = ".noob-code/memory.md"
_ENC = tiktoken.get_encoding("cl100k_base")


def _path(workspace_path: str) -> Path:
    return Path(workspace_path) / _MEMORY_FILE


def load(workspace_path: str) -> str:
    """Read .noob-code/memory.md, returning empty string if not found.

    Caps at LONG_TERM_MEMORY_MAX_TOKENS by keeping the most-recent tail —
    recent notes are more relevant than ancient ones.
    """
    p = _path(workspace_path)
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    tokens = _ENC.encode(text, disallowed_special=())
    if len(tokens) > LONG_TERM_MEMORY_MAX_TOKENS:
        tokens = tokens[-LONG_TERM_MEMORY_MAX_TOKENS:]
        text = _ENC.decode(tokens)
    return text


def append(workspace_path: str, new_notes: str) -> None:
    """Append bullet-point notes to memory.md, creating the file if needed."""
    p = _path(workspace_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    separator = "\n" if existing and not existing.endswith("\n") else ""
    p.write_text(existing + separator + new_notes.strip() + "\n", encoding="utf-8")


async def update_after_task(
    task: str, summary: str, workspace_path: str, model: str
) -> None:
    """Ask the LLM for 1-3 new memory notes and append them to memory.md.

    Non-fatal: a failure here should never interrupt the user's workflow.
    """
    from agent.generator import call_ollama  # lazy to avoid circular import

    existing = load(workspace_path)
    prompt = (
        f"Existing project notes:\n{existing}\n\n"
        f"Task just completed: {task}\n"
        f"Outcome: {summary}\n\n"
        "Append 1-3 new bullet points capturing any code convention discovered, "
        "important decision made, or constraint to remember for future tasks. "
        "Do NOT duplicate existing notes. Reply with ONLY the new bullet points "
        "(starting with -), no other text."
    )
    try:
        new_notes = call_ollama([{"role": "user", "content": prompt}], model=model)
        if new_notes.strip():
            append(workspace_path, new_notes)
            logger.info("Long-term memory updated for %s", workspace_path)
    except Exception as exc:
        logger.warning("Failed to update long-term memory (non-fatal): %s", exc)
