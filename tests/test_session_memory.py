"""Tests for backend.memory.session_memory (uses tmp_path, no external services)."""

import backend.memory.session_memory as sm


def _patch_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sm, "_SESSIONS_DB", str(tmp_path / "test_sessions.db"))


def test_create_and_load_session(tmp_path, monkeypatch) -> None:
    _patch_db(tmp_path, monkeypatch)
    sid = sm.create_session("/repo/project", "qwen2.5-coder:7b")
    assert len(sid) == 32
    session = sm.load_session(sid)
    assert session is not None
    assert session["workspace_path"] == "/repo/project"
    assert session["model"] == "qwen2.5-coder:7b"
    assert session["messages"] == []


def test_load_session_missing_returns_none(tmp_path, monkeypatch) -> None:
    _patch_db(tmp_path, monkeypatch)
    assert sm.load_session("nonexistent") is None


def test_append_message(tmp_path, monkeypatch) -> None:
    _patch_db(tmp_path, monkeypatch)
    sid = sm.create_session("/repo/project", "model")
    sm.append_message(sid, "user", "hello")
    sm.append_message(sid, "assistant", "hi there")
    session = sm.load_session(sid)
    assert session is not None
    assert len(session["messages"]) == 2
    assert session["messages"][0]["role"] == "user"
    assert session["messages"][1]["content"] == "hi there"


def test_get_or_create_returns_same_session_within_24h(tmp_path, monkeypatch) -> None:
    _patch_db(tmp_path, monkeypatch)
    session1, resumed1 = sm.get_or_create_for_workspace("/repo/project", "model")
    assert not resumed1  # first call always creates

    session2, resumed2 = sm.get_or_create_for_workspace("/repo/project", "model")
    assert resumed2  # second call within 24h should resume
    assert session1["session_id"] == session2["session_id"]


def test_list_recent_sessions(tmp_path, monkeypatch) -> None:
    _patch_db(tmp_path, monkeypatch)
    sm.create_session("/repo/a", "model")
    sm.create_session("/repo/a", "model")
    sessions = sm.list_recent_sessions("/repo/a", limit=5)
    assert len(sessions) == 2
    assert "session_id" in sessions[0]
    assert "message_count" in sessions[0]


def test_export_to_markdown(tmp_path, monkeypatch) -> None:
    _patch_db(tmp_path, monkeypatch)
    sid = sm.create_session("/repo/project", "model")
    sm.append_message(sid, "user", "Fix the bug")
    sm.append_message(sid, "assistant", "Done, fixed the add function.")
    out = str(tmp_path / "export.md")
    sm.export_to_markdown(sid, out)
    content = (tmp_path / "export.md").read_text(encoding="utf-8")
    assert "Fix the bug" in content
    assert "ASSISTANT" in content
