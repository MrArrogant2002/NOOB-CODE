"""Tests for backend.permissions.PermissionStore."""

import pytest

from backend.permissions import DEFAULTS, PermissionStore


def test_defaults_loaded_on_fresh_workspace(tmp_path) -> None:
    store = PermissionStore(str(tmp_path))
    assert store.check("FileRead") == "always"
    assert store.check("FileWrite") == "ask"
    assert store.check("ShellExec") == "ask"
    assert store.check("GitOp") == "ask"
    assert store.check("NetworkCall") == "deny"


def test_unknown_action_defaults_to_ask(tmp_path) -> None:
    store = PermissionStore(str(tmp_path))
    assert store.check("SomeRandomAction") == "ask"


def test_set_always_persists(tmp_path) -> None:
    store = PermissionStore(str(tmp_path))
    store.set_always("FileWrite")
    assert store.check("FileWrite") == "always"

    # Load fresh instance — should see the persisted value
    store2 = PermissionStore(str(tmp_path))
    assert store2.check("FileWrite") == "always"


def test_set_level_deny(tmp_path) -> None:
    store = PermissionStore(str(tmp_path))
    store.set_level("ShellExec", "deny")
    assert store.check("ShellExec") == "deny"


def test_set_level_invalid_raises(tmp_path) -> None:
    store = PermissionStore(str(tmp_path))
    with pytest.raises(ValueError):
        store.set_level("FileWrite", "maybe")


def test_get_all_returns_all_actions(tmp_path) -> None:
    store = PermissionStore(str(tmp_path))
    all_perms = store.get_all()
    for action in DEFAULTS:
        assert action in all_perms


def test_corrupt_file_falls_back_to_defaults(tmp_path) -> None:
    perm_dir = tmp_path / ".noob-code"
    perm_dir.mkdir()
    (perm_dir / "permissions.json").write_text("NOT JSON", encoding="utf-8")
    store = PermissionStore(str(tmp_path))
    assert store.check("FileRead") == "always"
