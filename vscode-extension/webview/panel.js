/**
 * NOOB CODE — Webview runtime (panel.js).
 *
 * Runs inside the VS Code WebviewView sandbox. Communicates with the
 * extension host (panel.ts) via acquireVsCodeApi().postMessage() and
 * window.addEventListener('message', …). Never touches the network directly.
 *
 * Message flow:
 *   Extension → Webview : window.addEventListener('message', handler)
 *   Webview → Extension : vscode.postMessage({type, ...})
 */

// eslint-disable-next-line no-undef
const vscode = acquireVsCodeApi();

// ── State ─────────────────────────────────────────────────────────────────────

let isRunning       = false;
let planMode        = false;
let currentModel    = "";
let agentBubble     = null;   // current streaming agent <div>
const spinners      = new Map(); // request_id → <details> element
const editPending   = new Map(); // request_id → {el, path, new_content}
const permPending   = new Map(); // request_id → el

// ── DOM refs ──────────────────────────────────────────────────────────────────

const chat          = document.getElementById("chat");
const taskInput     = document.getElementById("task-input");
const sendBtn       = document.getElementById("send-btn");
const cancelBtn     = document.getElementById("cancel-btn");
const newSessionBtn = document.getElementById("new-session-btn");
const planToggle    = document.getElementById("plan-toggle");
const modelSelect   = document.getElementById("model-select");
const statusBar     = document.getElementById("status-bar");
const sessionLabel  = document.getElementById("session-label");

// ── Incoming messages from extension host ─────────────────────────────────────

window.addEventListener("message", (event) => {
  const msg = event.data;
  if (!msg || !msg.type) { return; }

  switch (msg.type) {
    // Connection lifecycle
    case "connected":
      setStatus("connected", "Connected");
      enableInput();
      break;

    // Streaming token
    case "token":
      appendToken(msg.content);
      break;

    // Tool execution
    case "tool_start":
      addToolStart(msg.request_id, msg.name, msg.args);
      break;
    case "tool_result":
      fillToolResult(msg.request_id, msg.result);
      break;

    // Edit approval
    case "edit_request":
      finaliseAgentBubble();
      addEditRequest(msg.request_id, msg.path, msg.diff, msg.new_content);
      break;

    // Permission gate
    case "permission_request":
      finaliseAgentBubble();
      addPermissionRequest(msg.request_id, msg.action, msg.command);
      break;

    // Plan mode
    case "plan_ready":
      finaliseAgentBubble();
      addPlanBlock(msg.steps);
      break;

    // Task done
    case "done":
      finaliseAgentBubble();
      addNotice("done", "✓ " + (msg.final_answer ?? "Done"));
      setRunning(false);
      break;

    // Notices
    case "warning":
      addNotice("warning", "⚠ " + msg.message);
      break;
    case "error":
      finaliseAgentBubble();
      addNotice("error", "✗ " + msg.message);
      setRunning(false);
      break;
    case "info":
      addNotice("info", msg.message);
      break;

    // Model list
    case "models_list":
      populateModels(msg.models ?? []);
      break;

    // Session info
    case "session_info":
      sessionLabel.textContent = "Session " + (msg.session_id ?? "").slice(0, 8);
      break;

    // New session cleared
    case "cleared":
      clearChat();
      break;

    // Prefill from debugFix command
    case "prefill_task":
      taskInput.value = msg.task ?? "";
      taskInput.focus();
      break;
  }
});

// ── Rendering helpers ─────────────────────────────────────────────────────────

function appendToken(text) {
  if (!agentBubble) {
    agentBubble = document.createElement("div");
    agentBubble.className = "msg msg-agent";
    chat.appendChild(agentBubble);
  }
  agentBubble.textContent += text;
  scrollToBottom();
}

function finaliseAgentBubble() {
  agentBubble = null;
}

function addToolStart(requestId, name, args) {
  const el = document.createElement("details");
  el.className = "tool-block";

  const summary = document.createElement("summary");
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  const nameEl = document.createElement("span");
  nameEl.className = "tool-name";
  nameEl.textContent = name;
  const argsEl = document.createElement("span");
  argsEl.textContent = formatArgs(args);
  summary.appendChild(spinner);
  summary.appendChild(nameEl);
  summary.appendChild(argsEl);
  el.appendChild(summary);

  chat.appendChild(el);
  spinners.set(requestId, el);
  scrollToBottom();
}

function fillToolResult(requestId, result) {
  const el = spinners.get(requestId);
  if (!el) { return; }
  spinners.delete(requestId);

  // Remove spinner from summary
  const spin = el.querySelector(".spinner");
  if (spin) { spin.remove(); }

  const resultEl = document.createElement("div");
  resultEl.className = "tool-result";
  resultEl.textContent = result ?? "";
  el.appendChild(resultEl);
  // Leave collapsed by default
  scrollToBottom();
}

function addEditRequest(requestId, filePath, diff, newContent) {
  const el = document.createElement("div");
  el.className = "edit-block";

  const header = document.createElement("div");
  header.className = "edit-header";
  header.textContent = `✏ Edit requested: ${filePath}`;
  el.appendChild(header);

  if (diff) {
    const diffEl = document.createElement("div");
    diffEl.className = "edit-diff";
    diffEl.innerHTML = colourDiff(escapeHtml(diff));
    el.appendChild(diffEl);
  }

  const actions = document.createElement("div");
  actions.className = "edit-actions";

  const approveBtn = makeBtn("Approve", "primary-btn", () => {
    resolve(requestId, "approve");
    disableActions(el);
    el.querySelector(".edit-header").textContent = `✓ Approved: ${filePath}`;
  });
  const allBtn = makeBtn("Approve All", "secondary-btn", () => {
    resolve(requestId, "approve_all");
    disableActions(el);
    el.querySelector(".edit-header").textContent = `✓ Approved all: ${filePath}`;
  });
  const rejectBtn = makeBtn("Reject", "danger-btn", () => {
    resolve(requestId, "reject");
    disableActions(el);
    el.querySelector(".edit-header").textContent = `✗ Rejected: ${filePath}`;
  });

  if (newContent !== undefined) {
    const diffEditorBtn = makeBtn("Open Diff ↗", "link-btn", () => {
      vscode.postMessage({ type: "open_diff", request_id: requestId, path: filePath, new_content: newContent });
    });
    actions.appendChild(diffEditorBtn);
  }

  actions.appendChild(approveBtn);
  actions.appendChild(allBtn);
  actions.appendChild(rejectBtn);
  el.appendChild(actions);

  editPending.set(requestId, { el, filePath, newContent });
  chat.appendChild(el);
  scrollToBottom();

  function resolve(id, decision) {
    vscode.postMessage({ type: "approval", request_id: id, decision });
    editPending.delete(id);
  }
}

function addPermissionRequest(requestId, action, command) {
  const el = document.createElement("div");
  el.className = "perm-block";

  const header = document.createElement("div");
  header.className = "perm-header";
  header.textContent = `🔐 Permission required: ${action}`;
  el.appendChild(header);

  const cmd = document.createElement("div");
  cmd.className = "perm-cmd";
  cmd.textContent = command ?? action;
  el.appendChild(cmd);

  const actions = document.createElement("div");
  actions.className = "perm-actions";

  const allow = makeBtn("Allow", "primary-btn", () => {
    resolve(requestId, "allow");
    header.textContent = `✓ Allowed: ${action}`;
    disableActions(el);
  });
  const always = makeBtn("Allow Always", "secondary-btn", () => {
    resolve(requestId, "always_allow");
    header.textContent = `✓ Always allowed: ${action}`;
    disableActions(el);
  });
  const deny = makeBtn("Deny", "danger-btn", () => {
    resolve(requestId, "deny");
    header.textContent = `✗ Denied: ${action}`;
    disableActions(el);
  });

  actions.appendChild(allow);
  actions.appendChild(always);
  actions.appendChild(deny);
  el.appendChild(actions);

  permPending.set(requestId, el);
  chat.appendChild(el);
  scrollToBottom();

  function resolve(id, decision) {
    vscode.postMessage({ type: "permission", request_id: id, decision });
    permPending.delete(id);
  }
}

function addPlanBlock(steps) {
  const el = document.createElement("div");
  el.className = "plan-block";

  const header = document.createElement("div");
  header.className = "plan-header";
  header.textContent = "📋 Plan — review before executing";
  el.appendChild(header);

  const ol = document.createElement("ol");
  for (const step of steps) {
    const li = document.createElement("li");
    li.textContent = step;
    ol.appendChild(li);
  }
  el.appendChild(ol);

  const actions = document.createElement("div");
  actions.className = "plan-actions";

  const execBtn = makeBtn("Execute Plan ▶", "primary-btn", () => {
    vscode.postMessage({ type: "plan_execute" });
    header.textContent = "▶ Executing plan…";
    disableActions(el);
  });
  const cancelPlanBtn = makeBtn("Cancel", "danger-btn", () => {
    vscode.postMessage({ type: "plan_cancel" });
    header.textContent = "✗ Plan cancelled";
    disableActions(el);
    setRunning(false);
  });

  actions.appendChild(execBtn);
  actions.appendChild(cancelPlanBtn);
  el.appendChild(actions);

  chat.appendChild(el);
  scrollToBottom();
}

function addNotice(type, text) {
  const el = document.createElement("div");
  el.className = `notice ${type}`;
  el.textContent = text;
  chat.appendChild(el);
  scrollToBottom();
}

function populateModels(models) {
  const prev = modelSelect.value;
  modelSelect.innerHTML = "";
  if (!models.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(no models found)";
    modelSelect.appendChild(opt);
    return;
  }
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.name;
    modelSelect.appendChild(opt);
  }
  // Restore previous selection if still available
  if (prev && modelSelect.querySelector(`option[value="${CSS.escape(prev)}"]`)) {
    modelSelect.value = prev;
  }
  currentModel = modelSelect.value;
}

// ── Status & running state ────────────────────────────────────────────────────

function setStatus(cls, text) {
  statusBar.className = "status-bar " + cls;
  statusBar.textContent = text;
  if (cls === "connected") {
    setTimeout(() => { statusBar.className = "status-bar hidden"; }, 3000);
  }
}

function setRunning(running) {
  isRunning = running;
  sendBtn.disabled  = running;
  cancelBtn.disabled = !running;
  taskInput.disabled = running;
}

function enableInput() {
  sendBtn.disabled  = false;
  cancelBtn.disabled = true;
  taskInput.disabled = false;
}

// ── UI utilities ──────────────────────────────────────────────────────────────

function makeBtn(label, cls, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = cls;
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

function disableActions(el) {
  for (const btn of el.querySelectorAll("button")) {
    btn.disabled = true;
  }
}

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
}

function clearChat() {
  chat.innerHTML = "";
  agentBubble = null;
  spinners.clear();
  editPending.clear();
  permPending.clear();
  sessionLabel.textContent = "";
  setRunning(false);
}

function formatArgs(args) {
  if (!args || typeof args !== "object") { return ""; }
  const keys = Object.keys(args);
  if (!keys.length) { return ""; }
  const parts = keys.slice(0, 3).map((k) => {
    const v = args[k];
    const s = typeof v === "string" ? v : JSON.stringify(v);
    return `${k}: ${s.slice(0, 40)}${s.length > 40 ? "…" : ""}`;
  });
  return " (" + parts.join(", ") + ")";
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function colourDiff(html) {
  // Apply colour classes line by line without innerHTML injection risks
  // (input is already HTML-escaped, we just wrap lines in spans)
  return html
    .split("\n")
    .map((line) => {
      if (line.startsWith("+")) {
        return `<span class="diff-add">${line}</span>`;
      } else if (line.startsWith("-")) {
        return `<span class="diff-del">${line}</span>`;
      } else if (line.startsWith("@@")) {
        return `<span class="diff-hunk">${line}</span>`;
      }
      return line;
    })
    .join("\n");
}

// ── Event listeners ───────────────────────────────────────────────────────────

sendBtn.addEventListener("click", sendTask);

taskInput.addEventListener("keydown", (e) => {
  // Ctrl+Enter or Cmd+Enter sends the task
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    sendTask();
  }
});

cancelBtn.addEventListener("click", () => {
  vscode.postMessage({ type: "cancel" });
});

newSessionBtn.addEventListener("click", () => {
  vscode.postMessage({ type: "new_session" });
});

planToggle.addEventListener("click", () => {
  planMode = !planMode;
  planToggle.classList.toggle("active", planMode);
  planToggle.title = planMode ? "Plan mode ON — click to disable" : "Toggle plan mode";
});

modelSelect.addEventListener("change", () => {
  currentModel = modelSelect.value;
  vscode.postMessage({ type: "change_model", model: currentModel });
});

// Request model list on load
vscode.postMessage({ type: "get_models" });

function sendTask() {
  const task = taskInput.value.trim();
  if (!task || isRunning) { return; }

  // Extract @file mentions
  const fileMentions = [];
  const mentionRe = /@([\w./\\-]+)/g;
  let match;
  while ((match = mentionRe.exec(task)) !== null) {
    fileMentions.push(match[1]);
  }

  // Show user bubble
  const userBubble = document.createElement("div");
  userBubble.className = "msg msg-user";
  userBubble.textContent = task;
  chat.appendChild(userBubble);
  scrollToBottom();

  taskInput.value = "";
  setRunning(true);
  agentBubble = null;

  vscode.postMessage({
    type: "send_task",
    task,
    model: currentModel || undefined,
    plan_mode: planMode,
    file_mentions: fileMentions.length ? fileMentions : undefined,
  });
}
