"""Tests for backend.token_counter."""

from backend.token_counter import (
    budget_remaining,
    count,
    count_messages,
    exceeds_budget,
)


def test_count_returns_positive_int() -> None:
    assert count("def add(a, b): return a + b") > 0


def test_count_empty_string() -> None:
    assert count("") == 0


def test_count_messages_sums_content() -> None:
    msgs = [
        {"role": "user", "content": "hello world"},
        {"role": "assistant", "content": "hi there"},
    ]
    total = count_messages(msgs)
    assert total >= count("hello world") + count("hi there")


def test_count_messages_empty_list() -> None:
    assert count_messages([]) == 0


def test_budget_remaining_full_budget() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    remaining = budget_remaining(msgs, context_length=4096)
    assert remaining > 0
    assert remaining < 4096


def test_budget_remaining_large_context_leaves_room() -> None:
    msgs = [{"role": "user", "content": "short message"}]
    remaining = budget_remaining(msgs, context_length=32768)
    assert remaining > 1000


def test_exceeds_budget_false_for_small_conversation() -> None:
    msgs = [{"role": "user", "content": "Fix my code"}]
    assert not exceeds_budget(msgs, context_length=4096)


def test_exceeds_budget_true_when_content_too_large() -> None:
    # A message that fills the entire context
    huge_content = "x " * 4000
    msgs = [{"role": "user", "content": huge_content}]
    assert exceeds_budget(msgs, context_length=512)
