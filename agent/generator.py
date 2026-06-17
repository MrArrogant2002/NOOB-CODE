"""LLM-backed code generation via a local Ollama model (OpenAI-compatible API).

Houses the single shared `call_ollama` helper (with primary -> fallback model
retry) and markdown-fence stripping used by both generation and repair, since
both need to talk to the same local endpoint the same way.
"""

import logging
import re

from openai import OpenAI, OpenAIError

from config import FALLBACK_MODEL, OLLAMA_BASE_URL, PRIMARY_MODEL

logger = logging.getLogger(__name__)

_GENERATE_SYSTEM_PROMPT = (
    "You are an expert Python programmer. "
    "Return only raw Python code, no explanation, no markdown."
)

_TEST_SYSTEM_PROMPT = (
    "You are an expert Python test engineer. "
    "Return only raw pytest unit test code, no explanation, no markdown."
)

_CODE_FENCE_PATTERN = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)

_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def strip_markdown_fences(text: str) -> str:
    """Strip a single ```python ... ``` fence from an LLM response, if present."""
    match = _CODE_FENCE_PATTERN.search(text)
    return match.group(1).strip() if match else text.strip()


def call_ollama(messages: list[dict[str, str]], model: str = PRIMARY_MODEL) -> str:
    """Send a chat completion request to the local Ollama server.

    Falls back from PRIMARY_MODEL to FALLBACK_MODEL once if the primary call
    fails (e.g. model not pulled, server overloaded); re-raises otherwise.
    """
    try:
        response = _client.chat.completions.create(model=model, messages=messages)
        return response.choices[0].message.content or ""
    except OpenAIError:
        if model != PRIMARY_MODEL:
            raise
        logger.warning("Model %s failed, falling back to %s", model, FALLBACK_MODEL)
        return call_ollama(messages, model=FALLBACK_MODEL)


def generate_code(problem: str, model: str = PRIMARY_MODEL) -> str:
    """Generate an initial Python solution for `problem`."""
    messages = [
        {"role": "system", "content": _GENERATE_SYSTEM_PROMPT},
        {"role": "user", "content": problem},
    ]
    return strip_markdown_fences(call_ollama(messages, model=model))


def generate_tests(problem: str, code: str, model: str = PRIMARY_MODEL) -> str:
    """Generate a pytest test module exercising the solution to `problem`."""
    user_prompt = (
        f"Problem statement:\n{problem}\n\nSolution code:\n{code}\n\n"
        "Write pytest test functions covering typical cases and edge cases for this solution."
    )
    messages = [
        {"role": "system", "content": _TEST_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return strip_markdown_fences(call_ollama(messages, model=model))
