"""The orchestrator's agentic loop: task -> (tool call -> result)* -> final answer.

Does not rely on Ollama's structured `message.tool_calls` field (verified
unreliable even for models that advertise "tools" support; see
orchestrator/parser.py). Tool calls are parsed permissively out of the raw
assistant `content` instead, which keeps this working across local models
regardless of how strictly they follow their own chat template.
"""

import json
import logging
from typing import TypedDict

from openai import OpenAI

from config import MAX_ORCHESTRATION_STEPS, OLLAMA_BASE_URL, PRIMARY_MODEL
from orchestrator.parser import parse_tool_call
from orchestrator.schema import TOOL_SPECS, build_system_prompt
from orchestrator.tools import ToolBox, ToolError

logger = logging.getLogger(__name__)

_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


class StepLog(TypedDict):
    step: int
    tool: str | None
    arguments: dict | None
    result: str


class OrchestrationResult(TypedDict):
    completed: bool
    final_answer: str
    steps: list[StepLog]


def run_orchestrator(
    repo_root: str,
    task: str,
    model: str = PRIMARY_MODEL,
    max_steps: int = MAX_ORCHESTRATION_STEPS,
    allow_test_edits: bool = False,
) -> OrchestrationResult:
    """Drive the plan -> tool-call -> observe loop until a `finish` call or max_steps."""
    toolbox = ToolBox(repo_root, allow_test_edits=allow_test_edits, task=task)
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": build_system_prompt(toolbox.repo_root, allow_test_edits),
        },
        {"role": "user", "content": task},
    ]
    steps: list[StepLog] = []

    try:
        for step in range(1, max_steps + 1):
            response = _client.chat.completions.create(
                model=model, messages=messages, tools=TOOL_SPECS
            )
            content = response.choices[0].message.content or ""
            call = parse_tool_call(content)

            if call is None or call.name == "finish":
                final_answer = (
                    call.arguments.get("summary", content) if call else content
                )
                steps.append(
                    {
                        "step": step,
                        "tool": None,
                        "arguments": None,
                        "result": final_answer,
                    }
                )
                return {"completed": True, "final_answer": final_answer, "steps": steps}

            result_text = _dispatch(toolbox, call.name, call.arguments)
            steps.append(
                {
                    "step": step,
                    "tool": call.name,
                    "arguments": call.arguments,
                    "result": result_text,
                }
            )

            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": f"<tool_response>\n{result_text}\n</tool_response>",
                }
            )

        return {
            "completed": False,
            "final_answer": "max orchestration steps reached without a finish call",
            "steps": steps,
        }
    finally:
        toolbox.close()


_DISPATCHABLE_TOOLS = {
    "read_file",
    "write_file",
    "edit_file",
    "list_dir",
    "run_shell",
    "run_tests",
    "debug_fix",
    "git_diff",
    "git_status",
}


def _dispatch(toolbox: ToolBox, name: str, arguments: dict) -> str:
    """Invoke one of the explicitly allowed ToolBox methods by name.

    Restricted to a fixed allowlist rather than reflecting on whatever
    ToolBox happens to expose, since `name` comes from model output and
    should never be able to reach methods like `close`.
    """
    if name not in _DISPATCHABLE_TOOLS:
        return f"error: unknown tool '{name}'"
    handler = getattr(toolbox, name)
    try:
        result = handler(**arguments)
    except ToolError as exc:
        return f"error: {exc}"
    except TypeError as exc:
        return f"error: bad arguments for '{name}': {exc}"
    return result if isinstance(result, str) else json.dumps(result)
