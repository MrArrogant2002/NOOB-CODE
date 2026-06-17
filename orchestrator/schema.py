"""Tool specifications (OpenAI function-calling format) and system prompt.

Passing `tools` in the chat completion request still matters even though we
don't trust the structured `tool_calls` response field (see parser.py):
Ollama's chat template injects a "# Tools" section plus the `<tool_call>`
instruction into the prompt whenever `tools` is set, which is what gets the
model naming the right tool and arguments in the first place.
"""

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a local coding agent operating inside the repository at {repo_root}. "
    "You can only affect files within this repository. "
    "Work step by step: call one tool at a time, read its result, then decide the next step. "
    "When the task is complete, call the `finish` tool with a `summary` of what you did. "
    "Do not call `finish` until you have verified your changes by running tests, when tests are available. "
    "{test_policy}"
)

_TEST_POLICY_PROTECTED = (
    "Test files (test_*.py, *_test.py, or anything under a tests/ directory) are "
    "protected and cannot be modified. If a test fails, fix the implementation it is "
    "testing — never edit the test to make it pass."
)

_TEST_POLICY_UNRESTRICTED = "You may modify test files when the task requires it."


def build_system_prompt(repo_root: object, allow_test_edits: bool) -> str:
    """Render the system prompt, choosing the test-file policy sentence to include."""
    test_policy = (
        _TEST_POLICY_UNRESTRICTED if allow_test_edits else _TEST_POLICY_PROTECTED
    )
    return _SYSTEM_PROMPT_TEMPLATE.format(repo_root=repo_root, test_policy=test_policy)


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file, given a path relative to the repo root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a file or overwrite it entirely with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace one exact, unique occurrence of old_string with new_string in a file. "
                "Fails if old_string is missing or appears more than once."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List the immediate contents of a directory relative to the repo root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "defaults to repo root"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Run a shell command inside the repo's sandboxed container and return "
                "stdout/stderr/exit_code."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the project's test command (default 'pytest -q') inside the sandboxed container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "defaults to 'pytest -q'",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "debug_fix",
            "description": (
                "Run a command (default 'pytest -q'); if it fails, automatically classify "
                "the failure into an error category and apply a targeted repair to the "
                "given implementation file. Prefer this over manually reading the traceback "
                "and calling edit_file yourself. Cannot target test files. Re-run the "
                "command afterward to verify the fix actually worked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "implementation file to repair",
                    },
                    "command": {
                        "type": "string",
                        "description": "defaults to 'pytest -q'",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show the current uncommitted git diff for the repository.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show the current git status (short form) for the repository.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Signal that the task is complete and report a summary of what changed.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
]
