"""Unit tests for orchestrator.planner.run_orchestrator, with the LLM client mocked out.

Uses real ToolBox file/git operations against tmp_path (no Docker touched,
since these tasks never call run_shell/run_tests).
"""

from unittest.mock import MagicMock, patch

from orchestrator import planner


def _response_with_content(content: str) -> MagicMock:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_run_orchestrator_finishes_immediately(tmp_path) -> None:
    finish_call = '<tool_call>{"name": "finish", "arguments": {"summary": "nothing to do"}}</tool_call>'

    with patch.object(
        planner._client.chat.completions,
        "create",
        return_value=_response_with_content(finish_call),
    ):
        result = planner.run_orchestrator(str(tmp_path), "do nothing")

    assert result["completed"] is True
    assert result["final_answer"] == "nothing to do"
    assert len(result["steps"]) == 1


def test_run_orchestrator_calls_tool_then_finishes(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    read_call = (
        '<tool_call>{"name": "read_file", "arguments": {"path": "a.txt"}}</tool_call>'
    )
    finish_call = '<tool_call>{"name": "finish", "arguments": {"summary": "read the file"}}</tool_call>'

    with patch.object(
        planner._client.chat.completions,
        "create",
        side_effect=[
            _response_with_content(read_call),
            _response_with_content(finish_call),
        ],
    ):
        result = planner.run_orchestrator(str(tmp_path), "read a.txt")

    assert result["completed"] is True
    assert result["steps"][0]["tool"] == "read_file"
    assert result["steps"][0]["result"] == "hello"
    assert result["final_answer"] == "read the file"


def test_run_orchestrator_reports_tool_error_without_crashing(tmp_path) -> None:
    bad_call = '<tool_call>{"name": "read_file", "arguments": {"path": "missing.txt"}}</tool_call>'
    finish_call = (
        '<tool_call>{"name": "finish", "arguments": {"summary": "gave up"}}</tool_call>'
    )

    with patch.object(
        planner._client.chat.completions,
        "create",
        side_effect=[
            _response_with_content(bad_call),
            _response_with_content(finish_call),
        ],
    ):
        result = planner.run_orchestrator(str(tmp_path), "read missing.txt")

    assert result["steps"][0]["result"].startswith("error:")
    assert result["completed"] is True


def test_run_orchestrator_stops_at_max_steps(tmp_path) -> None:
    loop_call = '<tool_call>{"name": "git_status", "arguments": {}}</tool_call>'

    with patch.object(
        planner._client.chat.completions,
        "create",
        return_value=_response_with_content(loop_call),
    ):
        result = planner.run_orchestrator(str(tmp_path), "loop forever", max_steps=2)

    assert result["completed"] is False
    assert len(result["steps"]) == 2


def test_run_orchestrator_rejects_unknown_tool_name(tmp_path) -> None:
    bad_tool_call = '<tool_call>{"name": "close", "arguments": {}}</tool_call>'
    finish_call = (
        '<tool_call>{"name": "finish", "arguments": {"summary": "done"}}</tool_call>'
    )

    with patch.object(
        planner._client.chat.completions,
        "create",
        side_effect=[
            _response_with_content(bad_tool_call),
            _response_with_content(finish_call),
        ],
    ):
        result = planner.run_orchestrator(str(tmp_path), "try to close the session")

    assert result["steps"][0]["result"] == "error: unknown tool 'close'"


def test_run_orchestrator_blocks_test_file_edit_by_default(tmp_path) -> None:
    (tmp_path / "test_calc.py").write_text("assert add(2, 3) == 5", encoding="utf-8")
    edit_call = (
        '<tool_call>{"name": "edit_file", "arguments": '
        '{"path": "test_calc.py", "old_string": "== 5", "new_string": "== -1"}}</tool_call>'
    )
    finish_call = (
        '<tool_call>{"name": "finish", "arguments": {"summary": "done"}}</tool_call>'
    )

    with patch.object(
        planner._client.chat.completions,
        "create",
        side_effect=[
            _response_with_content(edit_call),
            _response_with_content(finish_call),
        ],
    ):
        result = planner.run_orchestrator(
            str(tmp_path), "make the test pass by editing it"
        )

    assert result["steps"][0]["result"].startswith(
        "error: refusing to modify test file"
    )
    assert (tmp_path / "test_calc.py").read_text(
        encoding="utf-8"
    ) == "assert add(2, 3) == 5"
