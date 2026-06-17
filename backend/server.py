"""NOOB CODE — FastAPI + WebSocket backend server.

Streams LLM tokens to the VS Code extension, executes tools, manages
sessions, memory, indexing, and checkpointing. The extension connects
over a single authenticated WebSocket and receives a JSON message stream.

Phase 3 additions (interactive gates):
  - permission_request: sent over WS; task runner blocks until the user
    clicks Allow / Deny in the webview or the VS Code notification popup.
  - edit_request: sent before every file-write with a unified diff; task
    runner blocks until the user clicks Approve / Reject.
  - plan_execute: plan mode now pauses after plan_ready and waits for the
    user to click "Execute Plan" before running tools.

Run via:
    uvicorn backend.server:app --host 127.0.0.1 --port 7867
"""

import asyncio
import dataclasses
import difflib
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI, OpenAIError

from backend.checkpoint import cleanup_orphaned_containers, create_checkpoint
from backend.daemon import get_or_create_session_token, release_lock, warm_up_model
from backend.indexer.file_tree import build_file_tree
from backend.memory.long_term_memory import load as load_ltm
from backend.memory.long_term_memory import update_after_task
from backend.memory.session_memory import (
    append_message,
    export_to_markdown,
    get_or_create_for_workspace,
    list_recent_sessions,
    load_session,
)
from backend.memory.working_memory import WorkingMemory
from backend.permissions import PermissionStore
from config import (
    BACKEND_API_VERSION,
    BACKEND_PORT,
    BACKEND_VERSION,
    MAX_ORCHESTRATION_STEPS,
    OLLAMA_BASE_URL,
    PRIMARY_MODEL,
)
from orchestrator.parser import parse_tool_call
from orchestrator.schema import TOOL_SPECS
from orchestrator.tools import ToolBox, ToolError

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

_SESSION_TOKEN: str = ""
_WARMED_UP: bool = False
_ASYNC_CLIENT: AsyncOpenAI | None = None

# Workspace → codebase_map string (rebuilt on reindex / file_changed)
_index_cache: dict[str, str] = {}
# Workspace → pending debounce Task for file_changed
_debounce_tasks: dict[str, asyncio.Task] = {}

_REINDEX_DEBOUNCE_SECONDS = 30.0


# ── Per-connection state ──────────────────────────────────────────────────────


@dataclasses.dataclass
class ConnectionState:
    """Holds all mutable state for one WebSocket connection lifetime."""

    # session_id → running asyncio.Task
    active_tasks: dict[str, asyncio.Task] = dataclasses.field(default_factory=dict)
    # request_id → Future that resolves when the user responds to a gate
    pending: dict[str, "asyncio.Future[dict]"] = dataclasses.field(default_factory=dict)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _SESSION_TOKEN, _ASYNC_CLIENT, _WARMED_UP
    cleanup_orphaned_containers()
    _SESSION_TOKEN = get_or_create_session_token()
    _ASYNC_CLIENT = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    async def _warm() -> None:
        global _WARMED_UP
        _WARMED_UP = await warm_up_model()

    asyncio.create_task(_warm())
    yield
    release_lock()


app = FastAPI(title="NOOB CODE", version=BACKEND_VERSION, lifespan=lifespan)


# ── REST endpoints ────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "api_version": BACKEND_API_VERSION,
        "backend_version": BACKEND_VERSION,
        "warmed_up": _WARMED_UP,
    }


@app.get("/models")
async def list_models() -> JSONResponse:
    import subprocess

    result = await asyncio.to_thread(
        lambda: subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    )
    models = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append({"name": parts[0]})
    return JSONResponse({"models": models})


@app.get("/resolve_file")
async def resolve_file(name: str, workspace: str = "") -> JSONResponse:
    """Best-effort file resolution for @mention expansion.

    Walks the workspace tree and returns the first file whose name or
    relative path matches (case-insensitive).  Returns {"path": null} if
    not found.
    """
    if not workspace:
        workspace = os.getcwd()
    tree = await asyncio.to_thread(build_file_tree, workspace)
    lower = name.lower()
    for rel in tree.splitlines():
        if rel.lower().endswith(lower) or lower in rel.lower():
            return JSONResponse({"path": rel, "abs": os.path.join(workspace, rel)})
    return JSONResponse({"path": None})


# ── WebSocket ─────────────────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = "") -> None:
    if token != _SESSION_TOKEN:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    conn = ConnectionState()

    # Version handshake
    await _send(
        websocket,
        {
            "type": "hello",
            "api_version": BACKEND_API_VERSION,
            "backend_version": BACKEND_VERSION,
        },
    )
    try:
        ack = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except (asyncio.TimeoutError, Exception):
        await websocket.close(code=4002, reason="Handshake timeout")
        return

    client_version = ack.get("api_version", "")
    if client_version != BACKEND_API_VERSION:
        await _send(
            websocket,
            {
                "type": "error",
                "message": (
                    f"API version mismatch: extension has v{client_version}, "
                    f"backend needs v{BACKEND_API_VERSION}. "
                    "Run: python setup.py --update"
                ),
            },
        )
        await websocket.close()
        return

    try:
        while True:
            try:
                msg = await websocket.receive_json()
            except (WebSocketDisconnect, Exception):
                break

            msg_type = msg.get("type")

            if msg_type == "task":
                sid = msg.get("session_id") or uuid.uuid4().hex
                if sid in conn.active_tasks and not conn.active_tasks[sid].done():
                    conn.active_tasks[sid].cancel()
                    await asyncio.gather(conn.active_tasks[sid], return_exceptions=True)
                task = asyncio.create_task(_run_task(websocket, conn, msg))
                conn.active_tasks[sid] = task

            elif msg_type == "cancel":
                sid = msg.get("session_id", "")
                if sid in conn.active_tasks and not conn.active_tasks[sid].done():
                    conn.active_tasks[sid].cancel()
                # Also resolve any pending gate with a "deny/reject" so the
                # task runner unblocks and can handle CancelledError cleanly.
                for fut in conn.pending.values():
                    if not fut.done():
                        fut.set_result({"decision": "reject"})
                await _send(websocket, {"type": "info", "message": "Task cancelled."})

            # Gate responses — resolve the waiting Future in the task runner
            elif msg_type == "approval":
                req_id = msg.get("request_id", "")
                fut = conn.pending.get(req_id)
                if fut and not fut.done():
                    fut.set_result(msg)

            elif msg_type == "permission":
                req_id = msg.get("request_id", "")
                fut = conn.pending.get(req_id)
                if fut and not fut.done():
                    fut.set_result(msg)

            elif msg_type == "plan_execute":
                fut = conn.pending.get("__plan__")
                if fut and not fut.done():
                    fut.set_result({"execute": True})

            elif msg_type == "reindex":
                workspace = msg.get("workspace", os.getcwd())
                await _reindex_workspace(workspace)
                await _send(
                    websocket, {"type": "info", "message": "Workspace re-indexed."}
                )

            elif msg_type == "file_changed":
                workspace = msg.get("workspace", os.getcwd())
                _schedule_debounced_reindex(workspace)

            elif msg_type == "list_models":
                resp = await list_models()
                await _send(websocket, json.loads(resp.body))

            elif msg_type == "get_history":
                sid = msg.get("session_id", "")
                session = await asyncio.to_thread(load_session, sid) if sid else None
                await _send(
                    websocket,
                    {
                        "type": "session_history",
                        "session_id": sid,
                        "messages": session["messages"] if session else [],
                    },
                )

            elif msg_type == "list_sessions":
                workspace = msg.get("workspace", os.getcwd())
                sessions = await asyncio.to_thread(list_recent_sessions, workspace)
                await _send(websocket, {"type": "sessions_list", "sessions": sessions})

            elif msg_type == "export_session":
                sid = msg.get("session_id", "")
                out = msg.get("output_path", f"noob-code-session-{sid[:8]}.md")
                try:
                    await asyncio.to_thread(export_to_markdown, sid, out)
                    await _send(
                        websocket, {"type": "info", "message": f"Exported to {out}"}
                    )
                except ValueError as exc:
                    await _send(websocket, {"type": "error", "message": str(exc)})

    finally:
        for t in conn.active_tasks.values():
            t.cancel()
        conn.active_tasks.clear()
        conn.pending.clear()


# ── Task runner ───────────────────────────────────────────────────────────────


async def _run_task(websocket: WebSocket, conn: ConnectionState, msg: dict) -> None:
    task_text = msg.get("task", "")
    workspace = msg.get("workspace", os.getcwd())
    model = msg.get("model", PRIMARY_MODEL)
    plan_mode = bool(msg.get("plan_mode", False))
    allow_test_edits = bool(msg.get("allow_test_edits", False))
    permission_mode = msg.get("permission_mode", "ask")  # ask | auto-approve | yolo

    # Session
    session, is_resumed = await asyncio.to_thread(
        get_or_create_for_workspace, workspace, model
    )
    session_id: str = session["session_id"]

    if is_resumed:
        await _send(
            websocket,
            {
                "type": "session_info",
                "session_id": session_id,
                "resumed": True,
                "message_count": len(session["messages"]),
            },
        )

    # Memory + indexing (use cached map when available; build on first use)
    ltm_notes = await asyncio.to_thread(load_ltm, workspace)
    if workspace not in _index_cache:
        await _reindex_workspace(workspace)
    codebase_map = _index_cache.get(workspace, "")

    memory = WorkingMemory(
        repo_root=workspace,
        long_term_notes=ltm_notes,
        codebase_map=codebase_map,
        allow_test_edits=allow_test_edits,
    )
    memory.add_user_message(task_text)

    context_length = await _get_context_length(model)
    perms = await asyncio.to_thread(PermissionStore, workspace)
    toolbox = ToolBox(workspace, allow_test_edits=allow_test_edits, task=task_text)
    checkpoint_done = False

    async def maybe_checkpoint() -> None:
        nonlocal checkpoint_done
        if not checkpoint_done:
            await asyncio.to_thread(create_checkpoint, workspace)
            checkpoint_done = True

    try:
        if plan_mode:
            await _plan_mode(websocket, conn, memory, model, context_length)
        else:
            final = await _execute_mode(
                websocket,
                conn,
                memory,
                model,
                context_length,
                toolbox,
                perms,
                permission_mode,
                maybe_checkpoint,
                workspace,
            )
            await asyncio.to_thread(append_message, session_id, "user", task_text)
            if final:
                await asyncio.to_thread(
                    update_after_task, task_text, final, workspace, model
                )
    except asyncio.CancelledError:
        await _send(websocket, {"type": "info", "message": "Task cancelled."})
    finally:
        await asyncio.to_thread(toolbox.close)


async def _execute_mode(
    websocket: WebSocket,
    conn: ConnectionState,
    memory: WorkingMemory,
    model: str,
    context_length: int,
    toolbox: ToolBox,
    perms: PermissionStore,
    permission_mode: str,
    maybe_checkpoint,
    workspace: str,
) -> str | None:
    """Stream the LLM + tool loop until `finish` or max steps."""

    for _step in range(1, MAX_ORCHESTRATION_STEPS + 1):
        messages = memory.build_context(None, context_length)

        if memory.needs_compression(context_length):
            await _send(
                websocket,
                {
                    "type": "warning",
                    "message": "Context window nearing limit — compressing older messages.",
                },
            )

        content = await _stream_llm(websocket, messages, model)
        if not content:
            break

        call = parse_tool_call(content)

        if call is None or call.name == "finish":
            final = call.arguments.get("summary", content) if call else content
            await _send(websocket, {"type": "done", "final_answer": final})
            return final

        action_type = _ACTION_MAP.get(call.name, "ShellExec")
        perm_level = perms.check(action_type)

        # ── Global override modes ──────────────────────────────────────────
        if permission_mode == "yolo":
            # Skip all gates including edit diffs
            pass
        elif permission_mode == "auto-approve":
            # Skip interactive gates but still run the tool
            pass
        else:
            # "ask" mode — interactive gates

            if perm_level == "deny":
                result_text = (
                    f"error: action '{call.name}' is denied by project permissions."
                )
                memory.add_exchange(content, result_text)
                continue

            # File-write gate: send edit_request and await approval
            if call.name in ("write_file", "edit_file", "debug_fix"):
                approved = await _request_edit_approval(
                    websocket, conn, call.name, call.arguments, workspace
                )
                if not approved:
                    result_text = "error: edit rejected by user."
                    memory.add_exchange(content, result_text)
                    continue

            # Shell/Git gate: send permission_request and await allow/deny
            elif perm_level == "ask" and action_type in ("ShellExec", "GitOp"):
                allowed, always = await _request_permission(
                    websocket, conn, call.name, action_type, call.arguments
                )
                if always:
                    await asyncio.to_thread(perms.set_always, action_type)
                if not allowed:
                    result_text = f"error: '{call.name}' denied by user."
                    memory.add_exchange(content, result_text)
                    continue

        # ── Checkpoint before first file mutation ─────────────────────────
        if call.name in ("write_file", "edit_file", "debug_fix"):
            await maybe_checkpoint()

        req_id = uuid.uuid4().hex[:8]
        await _send(
            websocket,
            {
                "type": "tool_start",
                "request_id": req_id,
                "name": call.name,
                "args": call.arguments,
            },
        )

        result = await asyncio.to_thread(_dispatch, toolbox, call.name, call.arguments)
        result_text = result if isinstance(result, str) else json.dumps(result)

        await _send(
            websocket,
            {
                "type": "tool_result",
                "request_id": req_id,
                "name": call.name,
                "result": result_text[:3000],
            },
        )

        memory.add_exchange(content, result_text)

    await _send(
        websocket,
        {"type": "done", "final_answer": "Reached maximum steps without finishing."},
    )
    return None


async def _plan_mode(
    websocket: WebSocket,
    conn: ConnectionState,
    memory: WorkingMemory,
    model: str,
    context_length: int,
) -> None:
    """Generate a plan, show it to the user, and wait for plan_execute."""
    plan_memory = WorkingMemory(
        repo_root=memory.repo_root,
        long_term_notes=memory.long_term_notes,
        codebase_map=memory.codebase_map,
        allow_test_edits=memory.allow_test_edits,
    )
    user_msg = memory._recent[-1]["content"] if memory._recent else ""
    plan_memory.add_user_message(
        f"Task: {user_msg}\n\n"
        "List the numbered steps you will take. Do NOT call any tools — only produce the plan. "
        "Be specific about which files you will read/edit and what commands you will run."
    )
    messages = plan_memory.build_context(None, context_length)
    plan_content = await _stream_llm(websocket, messages, model, emit_tokens=False)

    steps = [
        line.strip()
        for line in plan_content.splitlines()
        if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith("-"))
    ]
    await _send(websocket, {"type": "plan_ready", "steps": steps or [plan_content]})

    # Block until the user clicks "Execute Plan" or "Cancel"
    fut: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
    conn.pending["__plan__"] = fut
    try:
        response = await asyncio.wait_for(fut, timeout=600.0)  # 10 min timeout
        if not response.get("execute"):
            await _send(websocket, {"type": "info", "message": "Plan cancelled."})
            return
    except asyncio.TimeoutError:
        await _send(
            websocket, {"type": "info", "message": "Plan timed out waiting for user."}
        )
        return
    finally:
        conn.pending.pop("__plan__", None)

    # User confirmed: run the tool loop with the plan in working memory
    memory.task_plan = steps
    # Re-use the same memory to execute (plan steps are now injected into context)
    await _execute_mode(
        websocket,
        conn,
        memory,
        model,
        context_length,
        ToolBox(memory.repo_root, task=user_msg),
        PermissionStore(memory.repo_root),
        "ask",
        _noop_checkpoint,
        memory.repo_root,
    )


async def _noop_checkpoint() -> None:
    pass


# ── Indexer cache + debounce ──────────────────────────────────────────────────


async def _reindex_workspace(workspace: str) -> None:
    """Rebuild the codebase map for *workspace* and store it in the global cache."""
    file_tree = await asyncio.to_thread(build_file_tree, workspace)
    codebase_map = await asyncio.to_thread(
        build_codebase_map, workspace, file_tree, CODEBASE_MAP_MAX_TOKENS
    )
    _index_cache[workspace] = codebase_map
    logger.info("Index rebuilt for %s (%d chars)", workspace, len(codebase_map))


def _schedule_debounced_reindex(workspace: str) -> None:
    """Cancel any pending debounce for *workspace* and schedule a fresh one."""
    existing = _debounce_tasks.get(workspace)
    if existing and not existing.done():
        existing.cancel()

    async def _delayed() -> None:
        await asyncio.sleep(_REINDEX_DEBOUNCE_SECONDS)
        await _reindex_workspace(workspace)

    _debounce_tasks[workspace] = asyncio.create_task(_delayed())


# ── Interactive gate helpers ──────────────────────────────────────────────────


async def _request_edit_approval(
    websocket: WebSocket,
    conn: ConnectionState,
    tool_name: str,
    arguments: dict,
    workspace: str,
) -> bool:
    """Send edit_request with a unified diff; await user approval."""
    req_id = uuid.uuid4().hex[:8]
    file_path = arguments.get("path", "")
    abs_path = (
        file_path if os.path.isabs(file_path) else os.path.join(workspace, file_path)
    )

    # Compute diff for display
    diff_text = ""
    new_content: str | None = None

    if tool_name == "write_file":
        new_content = arguments.get("content", "")
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                old_content = f.read()
        except OSError:
            old_content = ""
        diff_lines = list(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
            )
        )
        diff_text = "".join(diff_lines) if diff_lines else "(new file)"

    elif tool_name in ("edit_file", "debug_fix"):
        # Show the patch/action arguments as the diff
        patch = arguments.get("patch", "") or arguments.get("new_content", "")
        diff_text = patch or str(arguments)

    await _send(
        websocket,
        {
            "type": "edit_request",
            "request_id": req_id,
            "path": file_path,
            "diff": diff_text,
            "new_content": new_content,
        },
    )

    fut: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
    conn.pending[req_id] = fut
    try:
        response = await asyncio.wait_for(fut, timeout=300.0)
        return response.get("decision") in ("approve", "approve_all")
    except asyncio.TimeoutError:
        return False
    finally:
        conn.pending.pop(req_id, None)


async def _request_permission(
    websocket: WebSocket,
    conn: ConnectionState,
    tool_name: str,
    action_type: str,
    arguments: dict,
) -> tuple[bool, bool]:
    """Send permission_request; returns (allowed, always_allow)."""
    req_id = uuid.uuid4().hex[:8]
    command = arguments.get("command", "") or arguments.get("cmd", "") or tool_name

    await _send(
        websocket,
        {
            "type": "permission_request",
            "request_id": req_id,
            "action": action_type,
            "command": command,
        },
    )

    fut: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
    conn.pending[req_id] = fut
    try:
        response = await asyncio.wait_for(fut, timeout=120.0)
        decision = response.get("decision", "deny")
        return decision in ("allow", "always_allow"), decision == "always_allow"
    except asyncio.TimeoutError:
        return False, False
    finally:
        conn.pending.pop(req_id, None)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _stream_llm(
    websocket: WebSocket,
    messages: list[dict],
    model: str,
    emit_tokens: bool = True,
) -> str:
    assert _ASYNC_CLIENT is not None
    parts: list[str] = []
    try:
        async with _ASYNC_CLIENT.chat.completions.stream(
            model=model,
            messages=messages,
            tools=TOOL_SPECS,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    parts.append(text)
                    if emit_tokens:
                        await _send(websocket, {"type": "token", "content": text})
    except OpenAIError as exc:
        msg = f"LLM error: {exc}"
        await _send(websocket, {"type": "error", "message": msg})
        return msg
    return "".join(parts)


async def _get_context_length(model: str) -> int:
    import subprocess

    result = await asyncio.to_thread(
        lambda: subprocess.run(
            ["ollama", "show", model, "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    )
    try:
        data = json.loads(result.stdout)
        info = data.get("model_info", data.get("details", {}))
        ctx = (
            info.get("llama.context_length")
            or info.get("context_length")
            or data.get("context_length")
            or 4096
        )
        return int(ctx)
    except (json.JSONDecodeError, ValueError, TypeError):
        return 4096


async def _send(websocket: WebSocket, data: dict) -> None:
    try:
        await websocket.send_json(data)
    except Exception:
        pass


_ACTION_MAP: dict[str, str] = {
    "read_file": "FileRead",
    "list_dir": "FileRead",
    "git_diff": "GitOp",
    "git_status": "GitOp",
    "write_file": "FileWrite",
    "edit_file": "FileWrite",
    "debug_fix": "FileWrite",
    "run_shell": "ShellExec",
    "run_tests": "ShellExec",
    "finish": "FileRead",
}

_DISPATCHABLE: frozenset[str] = frozenset(
    {
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
)


def _dispatch(toolbox: ToolBox, name: str, arguments: dict) -> Any:
    if name not in _DISPATCHABLE:
        return f"error: unknown tool '{name}'"
    handler = getattr(toolbox, name)
    try:
        return handler(**arguments)
    except ToolError as exc:
        return f"error: {exc}"
    except TypeError as exc:
        return f"error: bad arguments for '{name}': {exc}"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.server:app", host="127.0.0.1", port=BACKEND_PORT, log_level="info"
    )
