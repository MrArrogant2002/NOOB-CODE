# NOOB CODE — Risk Verification Checklist

Manual test cases for all 10 risks identified in `plan.md`.
Each item must be verified before a release is tagged.

---

## Risk 1 — Multiple VS Code windows → port conflict

**Mitigation:** `backend/daemon.py` lockfile; extension reads lock before spawning.

**Test:**
1. Open the project in VS Code window A. Confirm the backend starts (output channel shows port 7867).
2. Open the same project in VS Code window B.
3. **Expected:** Window B's extension reads `data/.daemon.lock`, finds the live PID, and connects to the existing backend on port 7867 — it does NOT spawn a second backend process.
4. Verify: only one `uvicorn` process is running (`tasklist | findstr uvicorn`).

**Status:** ☐ Not yet verified

---

## Risk 2 — Model cold-start latency (5–30 s on first request)

**Mitigation:** `daemon.py:warm_up_model()` fires a dummy 1-token request in the background at startup.

**Test:**
1. Restart the backend with the first-time model (e.g. `qwen2.5-coder:7b`).
2. `GET /health` immediately — note `"warmed_up": false`.
3. Wait ~20 s.
4. `GET /health` again — verify `"warmed_up": true` and no visible lag on the first real task.

**Status:** ☐ Not yet verified

---

## Risk 3 — Small model tool-call format variance

**Mitigation:** `orchestrator/parser.py` tries `tool_calls` field first, falls back to content parsing.

**Test:**
1. Configure `PRIMARY_MODEL` to a model known to emit bare JSON in content (e.g. `phi3.5:latest`).
2. Send a task that requires a tool call (e.g. "list the files in the project root").
3. **Expected:** Tool call is parsed correctly from content even without a `tool_calls` field.
4. Also test with a model that does populate `tool_calls` (e.g. `qwen2.5-coder:7b`).

**Status:** ☐ Not yet verified

---

## Risk 4 — Large repo + small context window

**Mitigation:** `backend/indexer/` produces a compact codebase map (≤ 2000 tokens); `WorkingMemory.build_context()` trims on budget.

**Test:**
1. Point workspace at a medium-size Python project with 100+ files.
2. Run a task and inspect the `Codebase Map` section injected into the system prompt.
3. **Expected:** Map is ≤ `CODEBASE_MAP_MAX_TOKENS` (2000 tokens); `node_modules`, `.git`, `__pycache__` absent.
4. Also verify `.noodcodeignore` exclusions: add `private/` to `.noodcodeignore`, confirm those paths don't appear.
5. Set `noobCode.maxContextTokens` to 4096 and run a 20-turn conversation; confirm no `ContextLengthExceeded` error.

**Status:** ☐ Not yet verified

---

## Risk 5 — Streaming + tool execution interleaving

**Mitigation:** `backend/server.py` is fully async; blocking tools run in `asyncio.to_thread()`.

**Test:**
1. Send a multi-tool task (e.g. "Read main.py, then list the tests directory").
2. In the webview, verify the sequence:
   - Token stream appears (text being typed)
   - `read_file` spinner appears while tool runs
   - Spinner replaced by collapsible result block
   - Another token stream begins
3. **Expected:** UI never freezes; spinner and result appear in the correct order; no out-of-order messages.

**Status:** ☐ Not yet verified

---

## Risk 6 — Local server security — unauthorized callers

**Mitigation:** 32-byte hex token in `data/.session_token`; validated on every WS connection (code 4001 on failure).

**Test:**
1. Find the token: `cat data/.session_token`
2. Connect via `websocat ws://127.0.0.1:7867/ws?token=wrongtoken`
3. **Expected:** Connection closes immediately with code 4001.
4. Connect with the correct token — handshake succeeds.
5. Confirm the token file is not tracked by git (`git status` should not show it).

**Status:** ☐ Not yet verified

---

## Risk 7 — Partial edits on crash / orphaned Docker containers

**Mitigation:** `backend/checkpoint.py` stashes changes before the first write; `cleanup_orphaned_containers()` on startup.

**Test:**
1. Start a task that edits a file. While it is running, kill the backend process (`Ctrl+C` or `kill`).
2. Restart the backend.
3. **Expected:** On the next task for the same workspace, a `warning` message appears: "Previous session ended without finishing. A git stash checkpoint exists."
4. Confirm `git stash list` shows the checkpoint stash.
5. Verify `cleanup_orphaned_containers()` removes any `selfdebug-orch-*` containers left from the crash.

**Status:** ☐ Not yet verified

---

## Risk 8 — Permission fatigue

**Mitigation:** Per-project `permissions.json`; three global modes (`ask` / `auto-approve` / `yolo`).

**Test:**
1. Set `noobCode.permissionMode` = `ask`.
2. Send a task that runs a shell command. Verify `permission_request` popup appears.
3. Click **Allow Always**. Confirm `permissions.json` is updated to `"ShellExec": "always"`.
4. Send another task with the same shell command. Verify no popup appears.
5. Set mode to `yolo`. Send a file-write task. Verify no diff shown and no permission prompt.

**Status:** ☐ Not yet verified

---

## Risk 9 — Conversation context drift on long sessions

**Mitigation:** Three-layer memory; `WorkingMemory.needs_compression()` triggers warning; long-term notes persist across restarts.

**Test:**
1. Have a 15-turn conversation about a codebase. Confirm that after 10 pairs the `warning` message fires ("Context window nearing limit").
2. Ask the agent a question answered only in the first turn. Verify it can still answer (via long-term notes injected into the system prompt).
3. Restart the backend. Start a new session for the same workspace.
4. **Expected:** `.noob-code/memory.md` is read and injected; agent recalls conventions from the previous session.

**Status:** ☐ Not yet verified

---

## Risk 10 — Extension + backend version mismatch

**Mitigation:** `hello`/`hello_ack` handshake on every connection; version mismatch closes with error.

**Test:**
1. Temporarily change `API_VERSION` in `backend/server.py` to `"2"`.
2. Connect the (unchanged, v1) extension.
3. **Expected:** Extension receives `{"type": "error", "message": "API version mismatch..."}` and shows a VS Code error notification. Connection closes.
4. Revert `API_VERSION` back to `"1"`. Confirm normal handshake succeeds.

**Status:** ☐ Not yet verified

---

## Summary

| Risk | Description | Status |
|------|-------------|--------|
| 1 | Multiple windows — port conflict | ☐ |
| 2 | Model cold-start latency | ☐ |
| 3 | Tool-call format variance | ☐ |
| 4 | Large repo + small context | ☐ |
| 5 | Streaming / tool interleaving | ☐ |
| 6 | Unauthorized local callers | ☐ |
| 7 | Partial edits on crash | ☐ |
| 8 | Permission fatigue | ☐ |
| 9 | Context drift on long sessions | ☐ |
| 10 | Extension/backend version mismatch | ☐ |
