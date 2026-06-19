"""Permissive extraction of tool calls from raw LLM text output.

Ollama's structured `message.tool_calls` field is unreliable in practice:
models can identify the correct tool and arguments without wrapping the
JSON in the `<tool_call>...</tool_call>` tags their own chat template
requires for Ollama's parser to populate that field (verified empirically
against qwen2.5-coder:7b — see project memory). This module parses tool
calls directly out of `content` instead of trusting that field, so the
orchestrator keeps working across models regardless of how strictly they
follow their template.
"""

import json
import re
from dataclasses import dataclass

_TOOL_CALL_TAG_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class ToolCall:
    name: str
    arguments: dict


def parse_tool_call(content: str) -> ToolCall | None:
    """Extract a single tool call from `content`, or None if it reads as a plain answer."""
    candidates = []

    tag_match = _TOOL_CALL_TAG_PATTERN.search(content)
    if tag_match:
        candidates.append(tag_match.group(1))

    # Try ALL complete code fences in REVERSE order — the model sometimes prepends an
    # example fence (e.g. "Given: {path}") before the actual tool-call fence ("Invoke:
    # {"name":...}).  The last complete fence is the most likely actual tool call.
    for m in reversed(list(_CODE_FENCE_PATTERN.finditer(content))):
        candidates.append(m.group(1))

    candidates.append(content)

    for candidate in candidates:
        parsed = _parse_json_object(candidate.strip())
        if parsed is not None and "name" in parsed and "arguments" in parsed:
            return ToolCall(name=parsed["name"], arguments=parsed["arguments"])

    return None


def _parse_json_object(text: str) -> dict | None:
    """Try a direct JSON parse first; fall back to scanning for an embedded {...} object."""
    direct = _try_json_loads(text)
    if direct is not None:
        return direct

    extracted = _extract_first_json_object(text)
    if extracted is not None:
        return _try_json_loads(extracted)

    return None


def _try_json_loads(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _extract_first_json_object(text: str) -> str | None:
    """Scan for the first balanced {...} substring, respecting quoted strings."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None
