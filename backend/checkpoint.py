"""Git-stash-based workspace checkpointing before risky edits.

Creates a labelled git stash before the first file-write in a NOOB CODE task
so the workspace can be fully rolled back if the agent crashes mid-edit.
Also cleans up any orphaned Docker sandbox containers from crashed sessions.
"""

import logging
import subprocess
from datetime import datetime, timezone

from config import CHECKPOINT_KEEP_LAST

logger = logging.getLogger(__name__)

_LABEL = "noob-code checkpoint"


def create_checkpoint(workspace_path: str) -> str | None:
    """Stash all local changes with a timestamped label.

    Returns the stash output string on success, or None if there was nothing
    to stash or the workspace is not a git repo.
    """
    label = f"{_LABEL} {datetime.now(timezone.utc).isoformat()}"
    result = subprocess.run(
        ["git", "stash", "push", "-u", "-m", label],
        cwd=workspace_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or "No local changes" in result.stdout:
        logger.debug(
            "Checkpoint skipped (%s): %s", workspace_path, result.stdout.strip()
        )
        return None
    logger.info("Checkpoint created: %s", label)
    return result.stdout.strip()


def list_checkpoints(workspace_path: str) -> list[str]:
    """Return stash-list lines that were created by NOOB CODE."""
    result = subprocess.run(
        ["git", "stash", "list"],
        cwd=workspace_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if _LABEL in line]


def restore_latest_checkpoint(workspace_path: str) -> bool:
    """Pop the most recent NOOB CODE stash. Returns True on success."""
    checkpoints = list_checkpoints(workspace_path)
    if not checkpoints:
        logger.info("No checkpoints to restore in %s", workspace_path)
        return False
    stash_ref = checkpoints[0].split(":")[0].strip()
    result = subprocess.run(
        ["git", "stash", "pop", stash_ref],
        cwd=workspace_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        logger.info("Restored checkpoint %s", stash_ref)
        return True
    logger.warning("Failed to restore checkpoint: %s", result.stderr.strip())
    return False


def cleanup_old_checkpoints(
    workspace_path: str, keep_last: int = CHECKPOINT_KEEP_LAST
) -> None:
    """Drop all but the most recent `keep_last` NOOB CODE checkpoints.

    Drops from the highest stash index downward so that dropping stash@{N}
    does not renumber stash@{N+1}, which would cause subsequent drops to miss.
    """
    to_drop = list_checkpoints(workspace_path)[keep_last:]
    for entry in reversed(to_drop):
        ref = entry.split(":")[0].strip()
        subprocess.run(
            ["git", "stash", "drop", ref],
            cwd=workspace_path,
            capture_output=True,
            check=False,
        )
        logger.debug("Dropped old checkpoint %s", ref)


def cleanup_orphaned_containers() -> None:
    """Kill any selfdebug-orch-* containers left from a previous crashed session."""
    result = subprocess.run(
        ["docker", "ps", "-q", "--filter", "name=selfdebug-orch"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if ids:
        subprocess.run(["docker", "rm", "-f"] + ids, capture_output=True, check=False)
        logger.info("Cleaned up %d orphaned container(s)", len(ids))
