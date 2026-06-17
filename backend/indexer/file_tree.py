"""Workspace file-tree builder — produces a compact string listing all relevant files.

Respects .noodcodeignore (gitignore-format) plus a hardcoded always-skip list
so node_modules, __pycache__, build artefacts, etc. never pollute the map.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ALWAYS_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        ".gradle",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__mocks__",
        "coverage",
        ".nyc_output",
        ".tox",
    }
)

_ALWAYS_SKIP_EXTS = frozenset(
    {
        ".pyc",
        ".pyo",
        ".pyd",
        ".min.js",
        ".min.css",
        ".map",
        ".whl",
        ".egg-info",
        ".lock",
    }
)


def _load_ignore_patterns(workspace_path: str) -> frozenset[str]:
    ignore_file = Path(workspace_path) / ".noodcodeignore"
    if not ignore_file.exists():
        return frozenset()
    patterns: set[str] = set()
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.add(line.rstrip("/"))
    return frozenset(patterns)


def _skip_dir(name: str, extra: frozenset[str]) -> bool:
    return name in _ALWAYS_SKIP_DIRS or name in extra or name.startswith(".")


def build_file_tree(workspace_path: str, max_files: int = 500) -> str:
    """Return a compact newline-separated file listing of the workspace.

    Typically 50–300 tokens for most real projects — small enough to keep
    permanently in the system prompt as a codebase map preamble.
    """
    extra_ignore = _load_ignore_patterns(workspace_path)
    root = Path(workspace_path)
    lines: list[str] = []

    try:
        for dirpath, dirnames, filenames in os.walk(workspace_path, topdown=True):
            rel_dir = Path(dirpath).relative_to(root)
            dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d, extra_ignore))

            for fname in sorted(filenames):
                fname_lower = fname.lower()
                if any(fname_lower.endswith(ext) for ext in _ALWAYS_SKIP_EXTS):
                    continue
                rel = (rel_dir / fname).as_posix()
                lines.append(rel)
                if len(lines) >= max_files:
                    lines.append(f"... (truncated at {max_files} files)")
                    return "\n".join(lines)

    except OSError as exc:
        logger.warning("Error walking %s: %s", workspace_path, exc)

    return "\n".join(lines)
