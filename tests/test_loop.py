"""Unit tests for agent.loop.run_agent, with LLM/Docker calls mocked out."""

from unittest.mock import patch

from agent import loop


def _execute_success(code: str, timeout: int) -> dict:
    return {"stdout": "4\n", "stderr": "", "exit_code": 0, "timed_out": False}


def _execute_runtime_failure(code: str, timeout: int) -> dict:
    return {
        "stdout": "",
        "stderr": "Traceback...\nIndexError: list index out of range",
        "exit_code": 1,
        "timed_out": False,
    }


def test_run_agent_succeeds_on_first_try(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(loop, "DB_PATH", str(tmp_path / "logs.db"))
    with (
        patch.object(loop, "generate_code", return_value="print(2 + 2)"),
        patch.object(loop, "execute_code", side_effect=_execute_success),
        patch.object(loop, "generate_tests", return_value="def test_ok(): assert True"),
    ):
        result = loop.run_agent("add two numbers", "4")

    assert result["success"] is True
    assert result["iterations"] == 1
    assert result["final_code"] == "print(2 + 2)"
    assert "def test_ok" in result["test_code"]
    assert result["logs"][0]["success"] is True


def test_run_agent_repairs_then_succeeds(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(loop, "DB_PATH", str(tmp_path / "logs.db"))
    execute_results = [_execute_runtime_failure("", 0), _execute_success("", 0)]

    with (
        patch.object(loop, "generate_code", return_value="broken code"),
        patch.object(loop, "execute_code", side_effect=execute_results),
        patch.object(loop, "classify_error", return_value="RuntimeError"),
        patch.object(loop, "repair_code", return_value="print(2 + 2)"),
        patch.object(loop, "generate_tests", return_value="def test_ok(): assert True"),
    ):
        result = loop.run_agent("add two numbers", "4")

    assert result["success"] is True
    assert result["iterations"] == 2
    assert result["logs"][0]["error_type"] == "RuntimeError"
    assert result["logs"][1]["success"] is True


def test_run_agent_fails_after_max_iterations(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(loop, "DB_PATH", str(tmp_path / "logs.db"))

    with (
        patch.object(loop, "generate_code", return_value="broken code"),
        patch.object(loop, "execute_code", side_effect=_execute_runtime_failure),
        patch.object(loop, "classify_error", return_value="RuntimeError"),
        patch.object(loop, "repair_code", return_value="still broken"),
    ):
        result = loop.run_agent("add two numbers", "4", max_iterations=2)

    assert result["success"] is False
    assert result["iterations"] == 2
    assert result["final_code"] == "still broken"
    assert len(result["logs"]) == 2
