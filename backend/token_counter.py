"""Token counting using tiktoken's cl100k_base encoding.

cl100k_base is GPT-4's tokenizer and gives a reliable approximation (within
~10-15%) for all major local model families (Qwen, Llama, CodeLlama, Mistral)
since they all use BPE variants with similar token densities for code.
"""

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


def count(text: str) -> int:
    """Count tokens in a single string."""
    return len(_ENC.encode(text, disallowed_special=()))


def count_messages(messages: list[dict]) -> int:
    """Count total tokens across a list of {role, content} message dicts."""
    total = 0
    for msg in messages:
        total += count(msg.get("content") or "")
        total += 4  # per-message overhead: role token + framing tokens
    return total


def budget_remaining(
    messages: list[dict], context_length: int, reserve_pct: float = 0.15
) -> int:
    """Return how many tokens are left before hitting the soft cap.

    reserve_pct reserves space for the model's own output and tool call text.
    """
    used = count_messages(messages)
    cap = int(context_length * (1 - reserve_pct))
    return max(0, cap - used)


def exceeds_budget(
    messages: list[dict], context_length: int, reserve_pct: float = 0.15
) -> bool:
    return budget_remaining(messages, context_length, reserve_pct) == 0
