"""Tests for backend.checkpoint (uses a temporary git repo where needed)."""

import subprocess


from backend.checkpoint import (
    cleanup_old_checkpoints,
    cleanup_orphaned_containers,
    create_checkpoint,
    list_checkpoints,
    restore_latest_checkpoint,
)


def _init_git_repo(path) -> None:
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    (path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True
    )


def test_create_checkpoint_on_non_git_dir_returns_none(tmp_path) -> None:
    result = create_checkpoint(str(tmp_path))
    assert result is None


def test_list_checkpoints_on_non_git_dir_returns_empty(tmp_path) -> None:
    assert list_checkpoints(str(tmp_path)) == []


def test_restore_latest_checkpoint_no_checkpoints(tmp_path) -> None:
    assert not restore_latest_checkpoint(str(tmp_path))


def test_create_checkpoint_on_clean_repo_returns_none(tmp_path) -> None:
    _init_git_repo(tmp_path)
    result = create_checkpoint(str(tmp_path))
    assert result is None  # nothing to stash on a clean repo


def test_create_checkpoint_with_changes(tmp_path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "new_file.py").write_text("print('hello')")
    result = create_checkpoint(str(tmp_path))
    assert result is not None
    checkpoints = list_checkpoints(str(tmp_path))
    assert len(checkpoints) == 1
    assert "noob-code checkpoint" in checkpoints[0]


def test_restore_latest_checkpoint(tmp_path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "new_file.py").write_text("print('hello')")
    create_checkpoint(str(tmp_path))
    assert not (tmp_path / "new_file.py").exists()  # stash removed the file
    restored = restore_latest_checkpoint(str(tmp_path))
    assert restored
    assert (tmp_path / "new_file.py").exists()  # restored


def test_cleanup_old_checkpoints(tmp_path) -> None:
    _init_git_repo(tmp_path)
    # Write a distinct new file each iteration; after create_checkpoint the
    # workspace is clean, so the next write adds one more unique stash entry.
    # We never pop, so stashes accumulate.
    for i in range(3):
        (tmp_path / f"file{i}.py").write_text(f"x = {i}")
        result = create_checkpoint(str(tmp_path))
        assert result is not None, f"Expected checkpoint for iteration {i}"

    checkpoints_before = list_checkpoints(str(tmp_path))
    assert len(checkpoints_before) >= 2
    cleanup_old_checkpoints(str(tmp_path), keep_last=1)
    checkpoints_after = list_checkpoints(str(tmp_path))
    assert len(checkpoints_after) <= 1


def test_cleanup_orphaned_containers_does_not_crash() -> None:
    # Docker may or may not be available; either way this must not raise
    cleanup_orphaned_containers()
