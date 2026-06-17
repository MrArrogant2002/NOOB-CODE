"""SQLite-backed conversation session store for NOOB CODE.

Each session belongs to one workspace folder. On open the store either
resumes the most recent session (if last_active is within 24 h) or
creates a fresh one, letting users pick up where they left off.
"""

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_SESSIONS_DB: str = os.environ.get("SESSIONS_DB_PATH", "data/sessions.db")


def _connect() -> sqlite3.Connection:
    db_path = _SESSIONS_DB
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id     TEXT PRIMARY KEY,
            workspace_path TEXT NOT NULL,
            model          TEXT NOT NULL,
            messages       TEXT NOT NULL DEFAULT '[]',
            created_at     TEXT NOT NULL,
            last_active    TEXT NOT NULL
        )
        """)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(workspace_path: str, model: str) -> str:
    session_id = uuid.uuid4().hex
    now = _now()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO sessions (session_id, workspace_path, model, messages, created_at, last_active) VALUES (?,?,?,?,?,?)",
            (session_id, workspace_path, model, "[]", now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def load_session(session_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["messages"] = json.loads(d["messages"])
        return d
    finally:
        conn.close()


def get_or_create_for_workspace(workspace_path: str, model: str) -> tuple[dict, bool]:
    """Return (session_dict, is_resumed).

    Resumes the most recent session for this workspace if last_active is
    within 24 hours; otherwise creates a new session.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE workspace_path=? ORDER BY last_active DESC LIMIT 1",
            (workspace_path,),
        ).fetchone()
        if row:
            d = dict(row)
            d["messages"] = json.loads(d["messages"])
            last = datetime.fromisoformat(d["last_active"])
            if datetime.now(timezone.utc) - last < timedelta(hours=24):
                return d, True
    finally:
        conn.close()

    new_id = create_session(workspace_path, model)
    return load_session(new_id), False  # type: ignore[return-value]


def append_message(session_id: str, role: str, content: str) -> None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT messages FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            return
        messages: list = json.loads(row["messages"])
        messages.append({"role": role, "content": content, "ts": _now()})
        conn.execute(
            "UPDATE sessions SET messages=?, last_active=? WHERE session_id=?",
            (json.dumps(messages), _now(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_recent_sessions(workspace_path: str, limit: int = 5) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT session_id, model, created_at, last_active, messages FROM sessions "
            "WHERE workspace_path=? ORDER BY last_active DESC LIMIT ?",
            (workspace_path, limit),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["message_count"] = len(json.loads(d.pop("messages")))
            result.append(d)
        return result
    finally:
        conn.close()


def export_to_markdown(session_id: str, output_path: str) -> None:
    session = load_session(session_id)
    if session is None:
        raise ValueError(f"Session {session_id!r} not found")
    lines = [
        "# NOOB CODE Session Export",
        "",
        f"**Session ID:** {session_id}",
        f"**Workspace:** {session['workspace_path']}",
        f"**Model:** {session['model']}",
        f"**Created:** {session['created_at']}",
        f"**Last active:** {session['last_active']}",
        "",
        "---",
        "",
    ]
    for msg in session["messages"]:
        role = msg["role"].upper()
        lines += [f"### {role}", msg["content"], ""]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
