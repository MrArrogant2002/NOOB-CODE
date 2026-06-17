"""Unit tests for the permissive tool-call parser (orchestrator/parser.py)."""

from orchestrator.parser import parse_tool_call


def test_parses_tag_wrapped_call() -> None:
    content = '<tool_call>\n{"name": "read_file", "arguments": {"path": "a.py"}}\n</tool_call>'
    call = parse_tool_call(content)
    assert call is not None
    assert call.name == "read_file"
    assert call.arguments == {"path": "a.py"}


def test_parses_bare_json_call() -> None:
    content = (
        '{\n  "name": "read_file",\n  "arguments": {\n    "path": "config.py"\n  }\n}'
    )
    call = parse_tool_call(content)
    assert call is not None
    assert call.name == "read_file"
    assert call.arguments == {"path": "config.py"}


def test_parses_fenced_json_call() -> None:
    content = '```json\n{"name": "list_dir", "arguments": {}}\n```'
    call = parse_tool_call(content)
    assert call is not None
    assert call.name == "list_dir"
    assert call.arguments == {}


def test_parses_json_embedded_in_prose() -> None:
    content = 'Sure, I will read it now: {"name": "read_file", "arguments": {"path": "x.py"}} let me check.'
    call = parse_tool_call(content)
    assert call is not None
    assert call.name == "read_file"
    assert call.arguments == {"path": "x.py"}


def test_handles_nested_arguments() -> None:
    content = '{"name": "write_file", "arguments": {"path": "a.py", "content": "x = {\\"a\\": 1}"}}'
    call = parse_tool_call(content)
    assert call is not None
    assert call.name == "write_file"
    assert call.arguments["content"] == 'x = {"a": 1}'


def test_plain_answer_returns_none() -> None:
    content = "The function looks correct; no changes are needed."
    assert parse_tool_call(content) is None


def test_finish_call_parses() -> None:
    content = (
        '<tool_call>{"name": "finish", "arguments": {"summary": "done"}}</tool_call>'
    )
    call = parse_tool_call(content)
    assert call is not None
    assert call.name == "finish"
    assert call.arguments["summary"] == "done"
