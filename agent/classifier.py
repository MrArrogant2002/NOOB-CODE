"""Hybrid rule-based + LLM error classification.

This is the core research novelty of the agent: instead of one generic
"fix this error" prompt, every failure is first bucketed into one of five
categories so `repairer.py` can apply a targeted repair prompt per category.
"""

import logging
import re

from agent.generator import call_ollama

logger = logging.getLogger(__name__)

VALID_LABELS = (
    "SyntaxError",
    "RuntimeError",
    "LogicError",
    "TimeoutError",
    "ImportError",
)

_RULE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bSyntaxError\b"), "SyntaxError"),
    (re.compile(r"\bIndentationError\b"), "SyntaxError"),
    (re.compile(r"\b(?:ImportError|ModuleNotFoundError)\b"), "ImportError"),
    (re.compile(r"\bTimeoutError\b"), "TimeoutError"),
]

_CLASSIFY_SYSTEM_PROMPT = (
    "You are an error classifier for a Python code repair system. "
    "Read the execution evidence and respond with exactly one label and "
    "no other text: SyntaxError, RuntimeError, LogicError, TimeoutError, or ImportError."
)


def classify_error(stderr: str, stdout: str, expected: str, actual: str) -> str:
    """Classify a failed execution into one of five error categories.

    Fast rule-based pattern matching runs first (cheap, deterministic);
    the LLM is only consulted for cases the rules cannot confidently decide.
    """
    for pattern, label in _RULE_PATTERNS:
        if pattern.search(stderr):
            return label

    if stderr.strip():
        return "RuntimeError"

    if actual.strip() != expected.strip():
        return "LogicError"

    return _classify_with_llm(stderr, stdout, expected, actual)


def _classify_with_llm(stderr: str, stdout: str, expected: str, actual: str) -> str:
    prompt = (
        f"stderr:\n{stderr}\n\nstdout:\n{stdout}\n\n"
        f"expected output:\n{expected}\n\nactual output:\n{actual}"
    )
    messages = [
        {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    raw = call_ollama(messages).strip()
    for label in VALID_LABELS:
        if label in raw:
            return label
    logger.warning(
        "Unrecognized LLM classification %r; defaulting to RuntimeError", raw
    )
    return "RuntimeError"
