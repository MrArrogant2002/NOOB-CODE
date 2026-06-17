"""Error-type-specific repair prompt templates and the LLM repair call.

Each of the five error categories gets its own targeted prompt rather than a
single generic "fix this error" instruction — this is what the classifier
feeds into.
"""

import logging

from agent.generator import call_ollama, strip_markdown_fences
from config import PRIMARY_MODEL

logger = logging.getLogger(__name__)

_REPAIR_SYSTEM_PROMPT = (
    "You are an expert Python debugger. "
    "Return only the corrected raw Python code, no explanation, no markdown."
)

_REPAIR_TEMPLATES: dict[str, str] = {
    "SyntaxError": (
        "The following Python code fails to parse with a SyntaxError.\n"
        "Problem statement:\n{problem}\n\n"
        "Broken code:\n{code}\n\n"
        "Traceback:\n{traceback}\n\n"
        "Fix only the syntax issue(s) so the code parses and still solves the problem. "
        "Check indentation, matching brackets/quotes, and missing colons."
    ),
    "RuntimeError": (
        "The following Python code raises a runtime exception during execution.\n"
        "Problem statement:\n{problem}\n\n"
        "Broken code:\n{code}\n\n"
        "Traceback:\n{traceback}\n\n"
        "Identify the line that raises the exception and fix the underlying cause "
        "(e.g. out-of-bounds access, type mismatch, missing key) without changing the "
        "intended behavior."
    ),
    "LogicError": (
        "The following Python code runs without crashing but produces incorrect output.\n"
        "Problem statement:\n{problem}\n\n"
        "Current code:\n{code}\n\n"
        "Observed discrepancy:\n{traceback}\n\n"
        "Trace through the algorithm and fix the logic so the output matches the expected "
        "behavior described in the problem statement."
    ),
    "TimeoutError": (
        "The following Python code exceeds the execution time limit.\n"
        "Problem statement:\n{problem}\n\n"
        "Broken code:\n{code}\n\n"
        "Traceback:\n{traceback}\n\n"
        "Rewrite the code to be more efficient (avoid unbounded loops, redundant "
        "recomputation, or exponential-time approaches) while preserving correctness."
    ),
    "ImportError": (
        "The following Python code fails due to a missing or incorrect import.\n"
        "Problem statement:\n{problem}\n\n"
        "Broken code:\n{code}\n\n"
        "Traceback:\n{traceback}\n\n"
        "Fix the import statement(s) using only Python standard library modules, "
        "or remove the import if it is unnecessary."
    ),
}


def repair_code(
    problem: str,
    code: str,
    error_type: str,
    traceback: str,
    model: str = PRIMARY_MODEL,
) -> str:
    """Generate a repaired version of `code` using the prompt template for `error_type`."""
    template = _REPAIR_TEMPLATES.get(error_type)
    if template is None:
        logger.warning("Unknown error_type %r; using RuntimeError template", error_type)
        template = _REPAIR_TEMPLATES["RuntimeError"]

    user_prompt = template.format(problem=problem, code=code, traceback=traceback)
    messages = [
        {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return strip_markdown_fences(call_ollama(messages, model=model))
