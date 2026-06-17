"""Unit tests for ToolBox file operations. No Docker required: the session
is created lazily and these tests never call run_shell/run_tests."""

import pytest

from orchestrator.tools import ToolBox, ToolError


def test_read_write_round_trip(tmp_path) -> None:
    box = ToolBox(tmp_path)
    box.write_file("a.txt", "hello")
    assert box.read_file("a.txt") == "hello"


def test_edit_file_replaces_unique_match(tmp_path) -> None:
    box = ToolBox(tmp_path)
    box.write_file("a.py", "x = 1\ny = 2\n")
    box.edit_file("a.py", "x = 1", "x = 100")
    assert box.read_file("a.py") == "x = 100\ny = 2\n"


def test_edit_file_rejects_non_unique_match(tmp_path) -> None:
    box = ToolBox(tmp_path)
    box.write_file("a.py", "x = 1\nx = 1\n")
    with pytest.raises(ToolError):
        box.edit_file("a.py", "x = 1", "x = 2")


def test_edit_file_rejects_missing_match(tmp_path) -> None:
    box = ToolBox(tmp_path)
    box.write_file("a.py", "x = 1\n")
    with pytest.raises(ToolError):
        box.edit_file("a.py", "not present", "x = 2")


def test_path_traversal_is_rejected(tmp_path) -> None:
    box = ToolBox(tmp_path)
    with pytest.raises(ToolError):
        box.read_file("../outside.txt")


def test_list_dir_reports_entries(tmp_path) -> None:
    box = ToolBox(tmp_path)
    box.write_file("a.txt", "1")
    box.write_file("sub/b.txt", "2")
    listing = box.list_dir(".")
    assert "a.txt" in listing
    assert "sub/" in listing


def test_git_status_on_non_repo_does_not_raise(tmp_path) -> None:
    box = ToolBox(tmp_path)
    assert isinstance(box.git_status(), str)


def test_write_file_rejects_test_file_by_default(tmp_path) -> None:
    box = ToolBox(tmp_path)
    with pytest.raises(ToolError):
        box.write_file("test_calc.py", "assert False")


def test_edit_file_rejects_test_file_by_default(tmp_path) -> None:
    box = ToolBox(tmp_path, allow_test_edits=True)
    box.write_file("test_calc.py", "assert add(2, 3) == 5")
    box.allow_test_edits = False
    with pytest.raises(ToolError):
        box.edit_file("test_calc.py", "== 5", "== -1")


def test_test_protection_covers_tests_directory(tmp_path) -> None:
    box = ToolBox(tmp_path)
    with pytest.raises(ToolError):
        box.write_file("tests/test_calc.py", "assert False")


def test_allow_test_edits_flag_permits_modification(tmp_path) -> None:
    box = ToolBox(tmp_path, allow_test_edits=True)
    box.write_file("test_calc.py", "assert True")
    assert box.read_file("test_calc.py") == "assert True"


def test_test_protection_does_not_block_implementation_files(tmp_path) -> None:
    box = ToolBox(tmp_path)
    box.write_file("calc.py", "def add(a, b): return a - b")
    box.edit_file("calc.py", "a - b", "a + b")
    assert "a + b" in box.read_file("calc.py")


class _FakeSession:
    """Stands in for DockerSession so debug_fix tests never touch Docker."""

    def __init__(self, result):
        self.result = result

    def exec(self, command, timeout=None):
        return self.result


def test_debug_fix_applies_repair_on_failure(tmp_path, monkeypatch) -> None:
    box = ToolBox(tmp_path, task="fix the add function")
    box.write_file("calc.py", "def add(a, b):\n    return a - b\n")
    box._session = _FakeSession(
        {
            "stdout": "",
            "stderr": "AssertionError: -1 != 5",
            "exit_code": 1,
            "timed_out": False,
        }
    )
    monkeypatch.setattr(
        "orchestrator.tools.classify_error", lambda *a, **k: "RuntimeError"
    )
    monkeypatch.setattr(
        "orchestrator.tools.repair_code",
        lambda *a, **k: "def add(a, b):\n    return a + b\n",
    )

    result = box.debug_fix("calc.py", command="pytest -q")

    assert "RuntimeError" in result
    assert box.read_file("calc.py") == "def add(a, b):\n    return a + b\n"


def test_debug_fix_noop_when_command_passes(tmp_path) -> None:
    box = ToolBox(tmp_path)
    box.write_file("calc.py", "def add(a, b):\n    return a + b\n")
    box._session = _FakeSession(
        {"stdout": "1 passed", "stderr": "", "exit_code": 0, "timed_out": False}
    )

    result = box.debug_fix("calc.py")

    assert "already passes" in result
    assert box.read_file("calc.py") == "def add(a, b):\n    return a + b\n"


def test_debug_fix_respects_test_protection(tmp_path) -> None:
    box = ToolBox(tmp_path, allow_test_edits=True)
    box.write_file("test_calc.py", "assert True")
    box.allow_test_edits = False
    box._session = _FakeSession(
        {"stdout": "", "stderr": "fail", "exit_code": 1, "timed_out": False}
    )

    with pytest.raises(ToolError):
        box.debug_fix("test_calc.py")


def test_debug_fix_does_not_repair_on_missing_command(tmp_path, monkeypatch) -> None:
    """exit 127 means the command itself is missing (e.g. pytest not installed) -
    not a code bug. debug_fix must not call classify_error/repair_code or mutate
    the file in that case."""
    box = ToolBox(tmp_path)
    box.write_file("calc.py", "def add(a, b):\n    return a - b\n")
    box._session = _FakeSession(
        {
            "stdout": "",
            "stderr": "sh: 1: pytest: not found",
            "exit_code": 127,
            "timed_out": False,
        }
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not classify/repair on a missing-command failure")

    monkeypatch.setattr("orchestrator.tools.classify_error", _fail_if_called)
    monkeypatch.setattr("orchestrator.tools.repair_code", _fail_if_called)

    result = box.debug_fix("calc.py")

    assert "command not found" in result
    assert box.read_file("calc.py") == "def add(a, b):\n    return a - b\n"
