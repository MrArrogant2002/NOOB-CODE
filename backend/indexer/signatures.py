"""Regex-based function and class signature extraction for the codebase map.

No tree-sitter dependency in Phase 1 — regex covers the common cases well
enough to build the compact map injected into the system prompt. Phase 5+
can layer in tree-sitter grammars for richer, more accurate extraction.
"""

import logging
import re
from pathlib import Path

import tiktoken

from config import CODEBASE_MAP_MAX_TOKENS, INDEXER_MAX_FILE_SIZE_BYTES

logger = logging.getLogger(__name__)

_ENC = tiktoken.get_encoding("cl100k_base")

# Per-extension: list of (pattern, group_index_or_0_for_full_match)
_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    ".py": [
        re.compile(r"^(class\s+\w+[^:]*):"),
        re.compile(r"^((?:async\s+)?def\s+\w+\s*\([^)]{0,80}\))"),
    ],
    ".js": [
        re.compile(r"^(class\s+\w+)"),
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\("),
    ],
    ".ts": [
        re.compile(r"^(?:export\s+)?(?:abstract\s+)?(class\s+\w+)"),
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(
            r"^(?:export\s+)?const\s+(\w+)\s*(?::\s*\S+)?\s*=\s*(?:async\s+)?\("
        ),
        re.compile(r"^(?:export\s+)?(?:interface|type)\s+(\w+)"),
    ],
    ".java": [
        re.compile(
            r"^\s*(?:public|private|protected|static|\s)*(?:class|interface|enum)\s+(\w+)"
        ),
        re.compile(
            r"^\s*(?:public|private|protected|static|\s)*\w[\w<>[\]]*\s+(\w+)\s*\("
        ),
    ],
    ".go": [
        re.compile(r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\("),
        re.compile(r"^type\s+(\w+)\s+struct"),
    ],
    ".rs": [
        re.compile(r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"),
        re.compile(r"^(?:pub\s+)?struct\s+(\w+)"),
        re.compile(r"^(?:pub\s+)?impl\s+(\w+)"),
    ],
}


def _extract_signatures(file_path: Path) -> list[str]:
    ext = file_path.suffix.lower()
    patterns = _PATTERNS.get(ext)
    if not patterns:
        return []
    try:
        if file_path.stat().st_size > INDEXER_MAX_FILE_SIZE_BYTES:
            return ["(file too large)"]
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    sigs: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        for pat in patterns:
            m = pat.match(stripped)
            if m:
                sig = next((g for g in m.groups() if g is not None), m.group(0))
                sigs.append(sig.strip())
                break
        if len(sigs) >= 30:
            break
    return sigs


def build_codebase_map(
    workspace_path: str, file_tree: str, max_tokens: int = CODEBASE_MAP_MAX_TOKENS
) -> str:
    """Build a compact codebase map: file paths + their key signatures.

    Always injected into the system prompt so the agent knows what exists in
    the repo without reading full file contents into context.
    """
    root = Path(workspace_path)
    lines: list[str] = []

    for rel_str in file_tree.splitlines():
        if rel_str.startswith("..."):
            break
        file_path = root / rel_str
        sigs = _extract_signatures(file_path)
        line = f"{rel_str}: {', '.join(sigs)}" if sigs else rel_str
        lines.append(line)

        current_tokens = len(_ENC.encode("\n".join(lines), disallowed_special=()))
        if current_tokens > max_tokens:
            lines[-1] = "... (map truncated at token limit)"
            break

    return "\n".join(lines)
