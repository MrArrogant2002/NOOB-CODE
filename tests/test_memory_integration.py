"""Phase 4 integration tests — all three memory layers working end-to-end.

Covers:
- Long-term memory (filesystem): append, load, token cap, injection into context
- Working memory (in-context): sliding window, budget trimming, compression flag
- Session memory (SQLite): create/resume/stale/export
- Cross-layer: update_after_task writes notes to memory.md (LLM mocked)

All tests run without Ollama, VS Code, or Docker.
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import backend.memory.long_term_memory as ltm
import backend.memory.session_memory as sm
from backend.memory.working_memory import WorkingMemory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sm, "_SESSIONS_DB", str(tmp_path / "sessions.db"))


def _encode(text: str) -> list[int]:
    import tiktoken

    return tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=())


# ---------------------------------------------------------------------------
# Layer 3: Long-term memory (filesystem — .noob-code/memory.md)
# ---------------------------------------------------------------------------


def test_long_term_memory_append_and_load(tmp_path) -> None:
    """Notes written to memory.md are readable on the next load."""
    ws = str(tmp_path)
    ltm.append(ws, "- project uses black for formatting")
    ltm.append(ws, "- tests live in tests/ directory")
    content = ltm.load(ws)
    assert "black for formatting" in content
    assert "tests/" in content


def test_long_term_memory_load_on_missing_workspace_returns_empty(tmp_path) -> None:
    """load() returns empty string when memory.md does not exist."""
    result = ltm.load(str(tmp_path / "nonexistent_workspace"))
    assert result == ""


def test_long_term_memory_token_cap(tmp_path, monkeypatch) -> None:
    """load() truncates to LONG_TERM_MEMORY_MAX_TOKENS tokens (keeps the recent tail)."""
    monkeypatch.setattr(ltm, "LONG_TERM_MEMORY_MAX_TOKENS", 20)
    ws = str(tmp_path)
    # Write roughly 80 unique tokens so truncation must fire
    big_note = " ".join(f"word{i}" for i in range(80))
    ltm.append(ws, big_note)

    result = ltm.load(ws)
    assert len(_encode(result)) <= 20


def test_long_term_notes_injected_into_working_memory_context(tmp_path) -> None:
    """Long-term notes from memory.md appear in the built system prompt."""
    ws = str(tmp_path)
    ltm.append(ws, "- always use type hints in this project")
    notes = ltm.load(ws)

    wm = WorkingMemory(repo_root=ws, long_term_notes=notes)
    context = wm.build_context(None, context_length=8192)

    system_content = context[0]["content"]
    assert "Project Memory" in system_content
    assert "type hints" in system_content


def test_codebase_map_injected_into_working_memory_context() -> None:
    """Codebase map is included in the built system prompt."""
    wm = WorkingMemory(
        repo_root="/tmp/project",
        codebase_map="calc.py: def add(a, b), def subtract(a, b)",
    )
    context = wm.build_context(None, context_length=8192)
    system_content = context[0]["content"]
    assert "Codebase Map" in system_content
    assert "calc.py" in system_content


# ---------------------------------------------------------------------------
# Layer 1: Working memory (in-context, sliding window, budget trimming)
# ---------------------------------------------------------------------------


def test_working_memory_sliding_window_hard_limit() -> None:
    """add_exchange() keeps at most WORKING_MEMORY_SLIDING_WINDOW * 2 messages."""
    from config import WORKING_MEMORY_SLIDING_WINDOW

    wm = WorkingMemory(repo_root="/tmp/project")
    for i in range(WORKING_MEMORY_SLIDING_WINDOW + 2):
        wm.add_exchange(f"assistant turn {i}", f"tool result {i}")

    assert len(wm._recent) == WORKING_MEMORY_SLIDING_WINDOW * 2


def test_working_memory_oldest_exchange_dropped_first() -> None:
    """The oldest assistant/tool pair is removed first when the window overflows."""
    from config import WORKING_MEMORY_SLIDING_WINDOW

    wm = WorkingMemory(repo_root="/tmp/project")
    for i in range(WORKING_MEMORY_SLIDING_WINDOW + 1):
        wm.add_exchange(f"assistant turn {i}", f"tool result {i}")

    # After overflow the oldest exchange (turn 0) must no longer be in _recent
    all_content = " ".join(m["content"] for m in wm._recent)
    assert "assistant turn 0" not in all_content
    assert "assistant turn 1" in all_content


def test_working_memory_build_context_stays_in_token_budget() -> None:
    """build_context() trims recent messages so total token usage ≤ 85% of budget."""
    context_length = 512
    wm = WorkingMemory(repo_root="/tmp/project")
    long_msg = "A" * 300  # forces budget pressure
    for _ in range(20):
        wm.add_exchange(long_msg, long_msg)

    messages = wm.build_context(None, context_length)
    used = (
        sum(len(_encode(m.get("content") or "")) for m in messages)
        + len(messages) * 4  # same overhead term the code uses
    )
    assert used <= int(context_length * 0.85)


def test_working_memory_needs_compression_true_when_budget_exhausted() -> None:
    """needs_compression() returns True when the non-sliding layers already fill the budget."""
    wm = WorkingMemory(
        repo_root="/tmp/project",
        long_term_notes="- note\n" * 60,
        codebase_map="file.py: def fn()\n" * 60,
    )
    # With only 50 tokens budget the system prompt alone far exceeds 80%
    assert wm.needs_compression(context_length=50)


def test_working_memory_needs_compression_false_with_ample_budget() -> None:
    """needs_compression() is False when there is plenty of context remaining."""
    wm = WorkingMemory(repo_root="/tmp/project")
    wm.add_exchange("hello", "world")
    assert not wm.needs_compression(context_length=32768)


def test_working_memory_current_file_injected_as_user_message() -> None:
    """Active file content is added to context as a user message."""
    wm = WorkingMemory(repo_root="/tmp/project")
    wm.current_file = "def add(a, b):\n    return a + b\n"

    context = wm.build_context(None, context_length=8192)
    all_content = " ".join(m.get("content", "") for m in context)
    assert "active_file" in all_content
    assert "def add" in all_content


def test_working_memory_task_plan_in_system_prompt() -> None:
    """Plan steps set on WorkingMemory appear in the assembled system prompt."""
    wm = WorkingMemory(repo_root="/tmp/project")
    wm.task_plan = [
        "Read the failing test output",
        "Fix the bug in calc.py",
        "Re-run tests",
    ]

    context = wm.build_context(None, context_length=8192)
    system_content = context[0]["content"]
    assert "Execution Plan" in system_content
    assert "Fix the bug" in system_content


# ---------------------------------------------------------------------------
# Layer 2: Session memory (SQLite)
# ---------------------------------------------------------------------------


def test_session_resumed_within_24h(tmp_path, monkeypatch) -> None:
    """get_or_create_for_workspace returns is_resumed=True for a recent session."""
    _patch_db(tmp_path, monkeypatch)
    _, resumed1 = sm.get_or_create_for_workspace("/ws/project", "model")
    assert not resumed1  # first call always creates a fresh session

    session2, resumed2 = sm.get_or_create_for_workspace("/ws/project", "model")
    assert resumed2
    assert session2["workspace_path"] == "/ws/project"


def test_session_not_resumed_after_stale_timestamp(tmp_path, monkeypatch) -> None:
    """get_or_create_for_workspace creates a new session when last_active > 24 h ago."""
    _patch_db(tmp_path, monkeypatch)
    db_path = str(tmp_path / "sessions.db")
    sid = sm.create_session("/ws/project", "model")

    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE sessions SET last_active=? WHERE session_id=?", (stale_ts, sid)
    )
    conn.commit()
    conn.close()

    new_session, resumed = sm.get_or_create_for_workspace("/ws/project", "model")
    assert not resumed
    assert new_session["session_id"] != sid


def test_session_messages_persist_across_loads(tmp_path, monkeypatch) -> None:
    """Messages appended to a session survive a full reload from SQLite."""
    _patch_db(tmp_path, monkeypatch)
    sid = sm.create_session("/ws/project", "model")
    sm.append_message(sid, "user", "Fix the bug")
    sm.append_message(sid, "assistant", "Changed `return a - b` to `return a + b`")

    loaded = sm.load_session(sid)
    assert loaded is not None
    assert len(loaded["messages"]) == 2
    assert loaded["messages"][0]["role"] == "user"
    assert "return a + b" in loaded["messages"][1]["content"]


def test_export_session_markdown_contains_all_messages(tmp_path, monkeypatch) -> None:
    """export_to_markdown() writes a readable file with every conversation turn."""
    _patch_db(tmp_path, monkeypatch)
    sid = sm.create_session("/ws/project", "qwen2.5-coder:7b")
    sm.append_message(sid, "user", "Explain the project layout")
    sm.append_message(
        sid, "assistant", "The project has a backend/ and vscode-extension/ folder."
    )

    out_path = str(tmp_path / "export" / "session.md")
    sm.export_to_markdown(sid, out_path)

    content = (tmp_path / "export" / "session.md").read_text(encoding="utf-8")
    assert "Explain the project layout" in content
    assert "backend/" in content
    assert "qwen2.5-coder:7b" in content
    assert "ASSISTANT" in content
    assert "USER" in content


# ---------------------------------------------------------------------------
# Cross-layer: long-term memory updated by LLM after task completion
# ---------------------------------------------------------------------------


def test_update_after_task_writes_notes_to_memory_file(tmp_path) -> None:
    """update_after_task() appends LLM-generated bullet points to memory.md."""
    ws = str(tmp_path)
    new_note = "- always seed random state before training"

    with patch("agent.generator.call_ollama", return_value=new_note):
        asyncio.run(
            ltm.update_after_task(
                task="Add reproducibility seeding",
                summary="Added torch.manual_seed(42) to train.py",
                workspace_path=ws,
                model="qwen2.5-coder:7b",
            )
        )

    content = ltm.load(ws)
    assert "seed random state" in content


def test_update_after_task_nonfatal_on_llm_error(tmp_path) -> None:
    """update_after_task() must not raise when the LLM call fails."""
    ws = str(tmp_path)

    with patch(
        "agent.generator.call_ollama",
        side_effect=RuntimeError("Ollama is down"),
    ):
        asyncio.run(
            ltm.update_after_task(
                task="something",
                summary="done",
                workspace_path=ws,
                model="any-model",
            )
        )

    # memory.md must not have been created (no successful note to persist)
    memory_path = tmp_path / ".noob-code" / "memory.md"
    assert (
        not memory_path.exists()
        or memory_path.read_text(encoding="utf-8").strip() == ""
    )
