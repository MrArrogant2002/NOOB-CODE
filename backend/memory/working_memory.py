"""In-context working memory: assembles the message list sent to Ollama each turn.

Budget allocation (highest priority = last to be truncated):
  1. System prompt          — never truncated
  2. Long-term notes        — capped at LONG_TERM_MEMORY_MAX_TOKENS
  3. Codebase map           — capped at CODEBASE_MAP_MAX_TOKENS
  4. Task plan (plan mode)  — kept if fits, dropped if over budget
  5. Current file content   — capped at 30 % of remaining budget
  6. Recent messages        — oldest pair dropped first (sliding window)
"""

import logging

import tiktoken

from config import (
    CODEBASE_MAP_MAX_TOKENS,
    LONG_TERM_MEMORY_MAX_TOKENS,
    WORKING_MEMORY_SLIDING_WINDOW,
)

logger = logging.getLogger(__name__)

_ENC = tiktoken.get_encoding("cl100k_base")

_SYSTEM_TEMPLATE = (
    # ── Identity (must be stated first and unambiguously) ──────────────────
    "You are NOOB CODE, a local AI coding assistant built by Eswar Balu "
    "(also known as Rapolu Eswara Balu), a CS researcher and engineer. "
    "You are NOT Claude. You are NOT made by Anthropic. You are NOT any cloud AI service. "
    "You run entirely locally via Ollama inside the repository at {repo_root}. "
    "When someone asks who you are: say you are NOOB CODE, a local coding agent. "
    "When someone asks who created you: say you were built by Eswar Balu. "
    "Never mention Anthropic, OpenAI, Google, or any external company as your creator. "
    # ── Behaviour rules ────────────────────────────────────────────────────
    "RULE 1 — conversational messages: if the user sends a greeting, small talk, a question about "
    "yourself, or any non-coding request, respond with plain text only and immediately call the "
    "`finish` tool — do NOT read files, run commands, or call any other tool. "
    "RULE 2 — coding tasks: work step by step, call one tool at a time, read its result, then "
    "decide the next step. Call `finish` when done. "
    "Do not call `finish` until you have verified your changes by running tests when available. "
    "RULE 3 — file operations: to create or modify any file you MUST call `write_file` or "
    "`edit_file`. Never write file content as plain text in your response — text in your reply "
    "does NOT create a file on disk. Only tool calls write to the filesystem. "
    "RULE 4 — no tool-call echoing: do NOT include tool-call JSON in your text reply. "
    "Emit only the tool call itself; your next text turn should be reasoning or the final answer. "
    "{test_policy}"
)

_POLICY_PROTECTED = (
    "Test files (test_*.py, *_test.py, or anything under tests/) are protected. "
    "If a test fails, fix the implementation — never edit the test to make it pass."
)

_POLICY_OPEN = "You may modify test files when the task explicitly requires it."


def _tok(text: str) -> int:
    return len(_ENC.encode(text, disallowed_special=()))


def _truncate_tail(text: str, max_tokens: int) -> str:
    """Keep the most-recent `max_tokens` tokens of `text`."""
    tokens = _ENC.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text
    return _ENC.decode(tokens[-max_tokens:])


def _truncate_head(text: str, max_tokens: int) -> str:
    """Keep the first `max_tokens` tokens of `text`."""
    tokens = _ENC.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text
    return _ENC.decode(tokens[:max_tokens])


class WorkingMemory:
    """Assembles the Ollama messages list, respecting the per-model token budget."""

    def __init__(
        self,
        repo_root: str,
        long_term_notes: str = "",
        codebase_map: str = "",
        allow_test_edits: bool = False,
    ) -> None:
        self.repo_root = repo_root
        self.long_term_notes = long_term_notes
        self.codebase_map = codebase_map
        self.allow_test_edits = allow_test_edits
        self.current_file: str | None = None
        self.task_plan: list[str] = []
        self._recent: list[dict] = []

    @property
    def _system_prompt(self) -> str:
        policy = _POLICY_OPEN if self.allow_test_edits else _POLICY_PROTECTED
        return _SYSTEM_TEMPLATE.format(repo_root=self.repo_root, test_policy=policy)

    def add_exchange(self, assistant_content: str, tool_result: str) -> None:
        """Record one assistant + tool-result pair into the sliding window."""
        self._recent.append({"role": "assistant", "content": assistant_content})
        self._recent.append(
            {
                "role": "user",
                "content": f"<tool_response>\n{tool_result}\n</tool_response>",
            }
        )
        max_entries = WORKING_MEMORY_SLIDING_WINDOW * 2
        if len(self._recent) > max_entries:
            self._recent = self._recent[-max_entries:]

    def add_user_message(self, content: str) -> None:
        self._recent.append({"role": "user", "content": content})

    def build_context(self, _unused, context_length: int) -> list[dict]:
        """Return the full messages list to pass to Ollama within the token budget."""
        # --- Layer 1: system prompt (never truncated) ---
        sys_parts = [self._system_prompt]

        # --- Layer 2: long-term notes (tail-capped) ---
        if self.long_term_notes.strip():
            notes = _truncate_tail(self.long_term_notes, LONG_TERM_MEMORY_MAX_TOKENS)
            sys_parts.append(f"\n\n## Project Memory\n{notes}")

        # --- Layer 3: codebase map (head-capped — most important info is at top) ---
        if self.codebase_map.strip():
            cmap = _truncate_head(self.codebase_map, CODEBASE_MAP_MAX_TOKENS)
            sys_parts.append(f"\n\n## Codebase Map\n{cmap}")

        # --- Layer 4: task plan (plan mode) ---
        if self.task_plan:
            plan_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(self.task_plan))
            sys_parts.append(f"\n\n## Execution Plan\n{plan_text}")

        messages: list[dict] = [{"role": "system", "content": "".join(sys_parts)}]

        # --- Layer 5: current file (30 % of remaining budget) ---
        if self.current_file:
            sys_tokens = _tok(messages[0]["content"])
            remaining = context_length - sys_tokens - int(context_length * 0.15)
            file_budget = int(remaining * 0.30)
            if file_budget > 100:
                file_content = _truncate_head(self.current_file, file_budget)
                messages.append(
                    {
                        "role": "user",
                        "content": f"<active_file>\n{file_content}\n</active_file>",
                    }
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "Understood, I have the active file.",
                    }
                )

        # --- Layer 6: recent conversation (sliding window, oldest dropped first) ---
        recent = list(self._recent)
        while recent:
            trial = messages + recent
            used = sum(_tok(m.get("content") or "") for m in trial) + len(trial) * 4
            if used <= int(context_length * 0.85):
                break
            if len(recent) >= 2:
                recent = recent[2:]  # drop one exchange (assistant + tool_response)
            else:
                recent = []
        messages.extend(recent)
        return messages

    def needs_compression(self, context_length: int) -> bool:
        messages = self.build_context(None, context_length)
        used = sum(_tok(m.get("content") or "") for m in messages) + len(messages) * 4
        return used > int(context_length * 0.80)
