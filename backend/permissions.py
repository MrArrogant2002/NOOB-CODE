"""Per-project permission store for NOOB CODE.

Permissions live in <workspace>/.noob-code/permissions.json.
Three levels:
  "always" — proceed without prompting (used for FileRead by default)
  "ask"    — send permission_request over WebSocket and wait (Phase 3 gates)
             Phase 1: auto-approves with a log message
  "deny"   — reject immediately without asking
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PERMISSION_FILE = ".noob-code/permissions.json"

DEFAULTS: dict[str, str] = {
    "FileRead": "always",
    "FileWrite": "ask",
    "ShellExec": "ask",
    "GitOp": "ask",
    "NetworkCall": "deny",
}

VALID_LEVELS = frozenset({"always", "ask", "deny"})


class PermissionStore:
    """Loads and persists per-action permission levels for one workspace."""

    def __init__(self, workspace_path: str) -> None:
        self._path = Path(workspace_path) / _PERMISSION_FILE
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data = {k: v for k, v in loaded.items() if v in VALID_LEVELS}
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "Unreadable permissions file %s — using defaults", self._path
                )
        for action, level in DEFAULTS.items():
            self._data.setdefault(action, level)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def check(self, action: str) -> str:
        """Return the permission level: "always", "ask", or "deny"."""
        return self._data.get(action, "ask")

    def set_level(self, action: str, level: str) -> None:
        if level not in VALID_LEVELS:
            raise ValueError(f"Invalid permission level: {level!r}")
        self._data[action] = level
        self._save()

    def set_always(self, action: str) -> None:
        """Upgrade an action to always-allow and persist it (called on 'Allow Always')."""
        self.set_level(action, "always")

    def get_all(self) -> dict[str, str]:
        return dict(self._data)
