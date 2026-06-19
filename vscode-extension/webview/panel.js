/**
 * NOOB CODE — Webview runtime.
 * Layout mirrors Claude Code's sidebar: clean chat + minimal input bar.
 *
 * Message flow:
 *   Extension → Webview : window.addEventListener('message', handler)
 *   Webview → Extension : vscode.postMessage({type, ...})
 */

// eslint-disable-next-line no-undef
const vscode = acquireVsCodeApi();

// ── State ─────────────────────────────────────────────────────────────────────

let isRunning    = false;
let planMode     = false;
let currentModel = "";
let agentBubble  = null;
let agentRawText = "";
const spinners   = new Map();
const editPending  = new Map();
const permPending  = new Map();

// ── DOM refs ──────────────────────────────────────────────────────────────────

const chat          = document.getElementById("chat");
const taskInput     = document.getElementById("task-input");
const mainBtn       = document.getElementById("main-btn");
const iconSend      = document.getElementById("icon-send");
const iconStop      = document.getElementById("icon-stop");
const newSessionBtn = document.getElementById("new-session-btn");
const modeBtn       = document.getElementById("mode-btn");
const modeLabel     = document.getElementById("mode-label");
const modelSelect   = document.getElementById("model-select");
const connDot       = document.getElementById("conn-dot");
const sessionLabel  = document.getElementById("session-label");

// ── Incoming messages ─────────────────────────────────────────────────────────

window.addEventListener("message", (event) => {
  const msg = event.data;
  if (!msg || !msg.type) { return; }

  switch (msg.type) {
    case "connected":
      connDot.className = "conn-dot connected";
      mainBtn.disabled = false;
      taskInput.disabled = false;
      taskInput.focus();
      break;

    case "disconnected":
      connDot.className = "conn-dot disconnected";
      break;

    case "token":
      appendToken(msg.content);
      break;

    case "tool_start":
      finaliseAgentBubble();
      addToolStart(msg.request_id, msg.name, msg.args);
      break;

    case "tool_result":
      fillToolResult(msg.request_id, msg.result);
      break;

    case "edit_request":
      finaliseAgentBubble();
      addEditRequest(msg.request_id, msg.path, msg.diff, msg.new_content);
      break;

    case "permission_request":
      finaliseAgentBubble();
      addPermissionRequest(msg.request_id, msg.action, msg.command);
      break;

    case "plan_ready":
      finaliseAgentBubble();
      addPlanBlock(msg.steps);
      break;

    case "done": {
      // Only show final_answer notice when no tokens were streamed (avoids duplication)
      const hadContent = agentRawText.trim().length > 0;
      finaliseAgentBubble();
      if (!hadContent && msg.final_answer) {
        addNotice("done", "✓ " + msg.final_answer);
      }
      setRunning(false);
      break;
    }

    case "warning":
      addNotice("warning", "⚠ " + msg.message);
      break;

    case "error":
      finaliseAgentBubble();
      addNotice("error", "✗ " + msg.message);
      setRunning(false);
      break;

    case "info":
      if (msg.message === "Task cancelled.") {
        finaliseAgentBubble();
        setRunning(false);
      }
      addNotice("info", msg.message);
      break;

    case "models_list":
      populateModels(msg.models ?? []);
      break;

    case "session_info":
      sessionLabel.textContent = "#" + (msg.session_id ?? "").slice(0, 7);
      break;

    case "cleared":
      clearChat();
      break;

    case "prefill_task":
      taskInput.value = msg.task ?? "";
      autoResize(taskInput);
      taskInput.focus();
      break;
  }
});

// ── Markdown renderer ─────────────────────────────────────────────────────────

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMarkdown(text) {
  const parts = [];
  const fenceRe = /```(\w*)\n?([\s\S]*?)```/g;
  let last = 0;
  let m;
  while ((m = fenceRe.exec(text)) !== null) {
    if (m.index > last) { parts.push(renderInline(text.slice(last, m.index))); }
    const lang = escapeHtml(m[1] || "");
    const code = escapeHtml(m[2].replace(/\n$/, ""));
    const hdr  = lang ? `<div class="code-header">${lang}</div>` : "";
    parts.push(`<pre>${hdr}<code>${code}</code></pre>`);
    last = m.index + m[0].length;
  }
  if (last < text.length) { parts.push(renderInline(text.slice(last))); }
  return parts.join("");
}

function renderInline(text) {
  let html = escapeHtml(text);

  // Stash inline code so other patterns don't touch it
  const stash = [];
  html = html.replace(/`([^`\n]+)`/g, (_, c) => { stash.push(c); return `\x00C${stash.length - 1}\x00`; });

  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
  html = html.replace(/^#{5,} (.+)$/gm, "<h4>$1</h4>");  // h5/h6 → h4 (same visual)
  html = html.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^### (.+)$/gm,  "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm,   "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm,    "<h1>$1</h1>");

  html = html.replace(/((?:^[-*] .+$\n?)+)/gm, (b) =>
    "<ul>" + b.trim().split("\n").map((l) => `<li>${l.replace(/^[-*] /, "")}</li>`).join("") + "</ul>"
  );
  html = html.replace(/((?:^\d+\. .+$\n?)+)/gm, (b) =>
    "<ol>" + b.trim().split("\n").map((l) => `<li>${l.replace(/^\d+\. /, "")}</li>`).join("") + "</ol>"
  );

  html = html.replace(/\x00C(\d+)\x00/g, (_, i) => `<code>${stash[+i]}</code>`);

  html = html.split(/\n{2,}/).map((block) => {
    const t = block.trim();
    if (!t) { return ""; }
    if (/^<(h[1-3]|ul|ol|pre)/.test(t)) { return t.replace(/\n/g, "<br>"); }
    return `<p>${t.replace(/\n/g, "<br>")}</p>`;
  }).join("");

  // Merge adjacent list blocks so items separated by blank lines get sequential numbers
  html = html.replace(/<\/ol>\s*<ol>/g, "");
  html = html.replace(/<\/ul>\s*<ul>/g, "");

  return html;
}

// ── Chat rendering ────────────────────────────────────────────────────────────

function addThinkingBubble() {
  agentBubble = document.createElement("div");
  agentBubble.className = "msg-agent streaming thinking";
  agentBubble.innerHTML = '<span class="thinking-dots"><span></span><span></span><span></span></span>';
  chat.appendChild(agentBubble);
  scrollToBottom();
}

function appendToken(text) {
  if (!agentBubble) {
    agentBubble = document.createElement("div");
    agentBubble.className = "msg-agent streaming";
    chat.appendChild(agentBubble);
    agentRawText = "";
  }
  if (agentBubble.classList.contains("thinking")) {
    agentBubble.classList.remove("thinking");
    agentBubble.innerHTML = "";
  }
  agentRawText += text;
  agentBubble.textContent = agentRawText;
  scrollToBottom();
}

function looksLikeToolCall(text) {
  // Strip leading code fence then check if what remains starts with a tool-call JSON.
  // Use \s* between { and "name" because the model sometimes puts them on separate lines.
  const t = text.replace(/^```\w*\s*/, "").trim();
  return /^\{\s*"name"/.test(t) || /^<tool_call>/.test(t);
}

function stripToolCallSuffix(text) {
  // Remove a tool-call block that appears at the tail of a prose response.
  // Patterns match even when the JSON is truncated mid-stream (no closing "):
  //   code-fenced:  \n```json\n{"name   (partial — "name": never arrived)
  //   bare JSON:    \n{"name   (same)
  //   orphan fence: \n```json\n  (code fence opened, no content written yet)
  return text
    .replace(/\n```\w*\s*\{\s*"name[\s\S]*$/, "")   // code-fenced tool call (partial or complete)
    .replace(/\n\{\s*"name[\s\S]*$/, "")              // bare JSON tool call (partial or complete)
    .replace(/\n```\w*\s*$/, "")                      // orphaned opening fence with no content
    .trimEnd();
}

function finaliseAgentBubble() {
  if (!agentBubble) { return; }
  agentBubble.classList.remove("streaming");
  const text = agentRawText.trim();
  if (text) {
    if (looksLikeToolCall(text)) {
      agentBubble.remove();
    } else {
      agentBubble.innerHTML = renderMarkdown(stripToolCallSuffix(text));
    }
  } else {
    agentBubble.remove();
  }
  agentBubble  = null;
  agentRawText = "";
}

function addToolStart(requestId, name, args) {
  const el  = document.createElement("details");
  el.className = "tool-block";

  const sum = document.createElement("summary");
  const sp  = document.createElement("span"); sp.className = "spinner";
  const nm  = document.createElement("span"); nm.className = "tool-name"; nm.textContent = name;
  const ar  = document.createElement("span"); ar.className = "tool-args"; ar.textContent = fmtArgs(args);

  sum.appendChild(sp); sum.appendChild(nm); sum.appendChild(ar);
  el.appendChild(sum);
  chat.appendChild(el);
  spinners.set(requestId, el);
  scrollToBottom();
}

function fillToolResult(requestId, result) {
  const el = spinners.get(requestId);
  if (!el) { return; }
  spinners.delete(requestId);
  const sp = el.querySelector(".spinner");
  if (sp) { sp.remove(); }
  const r = document.createElement("div");
  r.className = "tool-result";
  r.textContent = result ?? "";
  el.appendChild(r);
  scrollToBottom();
}

function addEditRequest(requestId, filePath, diff, newContent) {
  const el  = document.createElement("div"); el.className = "edit-block";
  const hdr = document.createElement("div"); hdr.className = "edit-header";
  hdr.textContent = `✏ Edit: ${filePath}`;
  el.appendChild(hdr);

  if (diff) {
    const d = document.createElement("div"); d.className = "edit-diff";
    d.innerHTML = colourDiff(escapeHtml(diff));
    el.appendChild(d);
  }

  const act = document.createElement("div"); act.className = "gate-actions";
  if (newContent !== undefined) {
    act.appendChild(mkBtn("Open Diff ↗", "link-btn", () =>
      vscode.postMessage({ type: "open_diff", request_id: requestId, path: filePath, new_content: newContent })
    ));
  }
  act.appendChild(mkBtn("Approve", "primary-btn", () => {
    resolve(requestId, "approve"); hdr.textContent = `✓ Approved: ${filePath}`; disableAct(el);
  }));
  act.appendChild(mkBtn("Approve All", "secondary-btn", () => {
    resolve(requestId, "approve_all"); hdr.textContent = `✓ All approved`; disableAct(el);
  }));
  act.appendChild(mkBtn("Reject", "danger-btn", () => {
    resolve(requestId, "reject"); hdr.textContent = `✗ Rejected`; disableAct(el);
  }));

  el.appendChild(act);
  editPending.set(requestId, { el, filePath, newContent });
  chat.appendChild(el);
  requestAnimationFrame(() => scrollToBottom());

  function resolve(id, decision) {
    vscode.postMessage({ type: "approval", request_id: id, decision });
    editPending.delete(id);
  }
}

function addPermissionRequest(requestId, action, command) {
  const el  = document.createElement("div"); el.className = "perm-block";
  const hdr = document.createElement("div"); hdr.className = "perm-header";
  hdr.textContent = `🔐 Permission: ${action}`;
  el.appendChild(hdr);

  const cmd = document.createElement("div"); cmd.className = "perm-cmd";
  cmd.textContent = command ?? action;
  el.appendChild(cmd);

  const act = document.createElement("div"); act.className = "gate-actions";
  act.appendChild(mkBtn("Allow", "primary-btn", () => {
    resolve(requestId, "allow"); hdr.textContent = `✓ Allowed: ${action}`; disableAct(el);
  }));
  act.appendChild(mkBtn("Allow Always", "secondary-btn", () => {
    resolve(requestId, "always_allow"); hdr.textContent = `✓ Always: ${action}`; disableAct(el);
  }));
  act.appendChild(mkBtn("Deny", "danger-btn", () => {
    resolve(requestId, "deny"); hdr.textContent = `✗ Denied`; disableAct(el);
  }));

  el.appendChild(act);
  permPending.set(requestId, el);
  chat.appendChild(el);
  requestAnimationFrame(() => scrollToBottom());

  function resolve(id, decision) {
    vscode.postMessage({ type: "permission", request_id: id, decision });
    permPending.delete(id);
  }
}

function addPlanBlock(steps) {
  const el  = document.createElement("div"); el.className = "plan-block";
  const hdr = document.createElement("div"); hdr.className = "plan-header";
  hdr.textContent = "📋 Plan — review before executing";
  el.appendChild(hdr);

  const ol = document.createElement("ol");
  (steps || []).forEach((s) => { const li = document.createElement("li"); li.textContent = s; ol.appendChild(li); });
  el.appendChild(ol);

  const act = document.createElement("div"); act.className = "gate-actions";
  act.appendChild(mkBtn("Execute Plan ▶", "primary-btn", () => {
    vscode.postMessage({ type: "plan_execute" }); hdr.textContent = "▶ Executing…"; disableAct(el);
  }));
  act.appendChild(mkBtn("Cancel", "danger-btn", () => {
    vscode.postMessage({ type: "plan_cancel" }); hdr.textContent = "✗ Cancelled"; disableAct(el); setRunning(false);
  }));
  el.appendChild(act);
  chat.appendChild(el);
  // rAF ensures the browser paints the full block height before we scroll,
  // so the Execute/Cancel buttons are fully visible, not clipped.
  requestAnimationFrame(() => scrollToBottom());
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
    const o = document.createElement("option"); o.value = ""; o.textContent = "(no models)";
    modelSelect.appendChild(o);
    return;
  }
  models.forEach((m) => {
    const o = document.createElement("option"); o.value = m.name; o.textContent = m.name;
    modelSelect.appendChild(o);
  });
  if (prev && modelSelect.querySelector(`option[value="${CSS.escape(prev)}"]`)) {
    modelSelect.value = prev;
  }
  currentModel = modelSelect.value;
}

// ── State helpers ─────────────────────────────────────────────────────────────

function setRunning(running) {
  isRunning = running;
  taskInput.disabled = running;

  if (running) {
    mainBtn.classList.replace("send", "stop");
    mainBtn.title = "Stop task";
    iconSend.classList.add("hidden");
    iconStop.classList.remove("hidden");
  } else {
    mainBtn.classList.replace("stop", "send");
    mainBtn.title = "Send (Ctrl+Enter)";
    iconStop.classList.add("hidden");
    iconSend.classList.remove("hidden");
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function mkBtn(label, cls, fn) {
  const b = document.createElement("button");
  b.type = "button"; b.className = cls; b.textContent = label;
  b.addEventListener("click", fn);
  return b;
}

function disableAct(el) {
  el.querySelectorAll("button").forEach((b) => { b.disabled = true; });
}

function scrollToBottom() { chat.scrollTop = chat.scrollHeight; }

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 180) + "px";
}

function fmtArgs(args) {
  if (!args || typeof args !== "object") { return ""; }
  const keys = Object.keys(args);
  if (!keys.length) { return ""; }
  const s = keys.slice(0, 2).map((k) => {
    const v = typeof args[k] === "string" ? args[k] : JSON.stringify(args[k]);
    return v.slice(0, 48) + (v.length > 48 ? "…" : "");
  }).join(" · ");
  return "  " + s;
}

function colourDiff(html) {
  return html.split("\n").map((l) => {
    if (l.startsWith("+"))  { return `<span class="diff-add">${l}</span>`; }
    if (l.startsWith("-"))  { return `<span class="diff-del">${l}</span>`; }
    if (l.startsWith("@@")) { return `<span class="diff-hunk">${l}</span>`; }
    return l;
  }).join("\n");
}

function clearChat() {
  chat.innerHTML = "";
  agentBubble = null; agentRawText = "";
  spinners.clear(); editPending.clear(); permPending.clear();
  sessionLabel.textContent = "";
  setRunning(false);
}

// ── Event listeners ───────────────────────────────────────────────────────────

mainBtn.addEventListener("click", () => { isRunning ? cancelTask() : sendTask(); });

taskInput.addEventListener("input", () => autoResize(taskInput));
taskInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (!isRunning) { sendTask(); } }
  if (e.key === "Escape") { vscode.postMessage({ type: "focus_editor" }); }
});

newSessionBtn.addEventListener("click", () => vscode.postMessage({ type: "new_session" }));

// Mode toggle: Agent ↔ Plan
modeBtn.addEventListener("click", () => {
  planMode = !planMode;
  modeLabel.textContent = planMode ? "Plan" : "Agent";
  modeBtn.classList.toggle("plan-active", planMode);
  modeBtn.title = planMode ? "Plan mode — agent drafts a plan first" : "Agent mode — execute immediately";
});

modelSelect.addEventListener("change", () => {
  currentModel = modelSelect.value;
  vscode.postMessage({ type: "change_model", model: currentModel });
});

vscode.postMessage({ type: "get_models" });

// ── Actions ───────────────────────────────────────────────────────────────────

function cancelTask() {
  vscode.postMessage({ type: "cancel" });
}

function sendTask() {
  const task = taskInput.value.trim();
  if (!task || isRunning) { return; }

  const fileMentions = [];
  const re = /@([\w./\\-]+)/g;
  let m;
  while ((m = re.exec(task)) !== null) { fileMentions.push(m[1]); }

  const bubble = document.createElement("div");
  bubble.className = "msg-user";
  bubble.textContent = task;
  chat.appendChild(bubble);
  scrollToBottom();

  taskInput.value = "";
  autoResize(taskInput);
  setRunning(true);
  agentBubble = null; agentRawText = "";
  addThinkingBubble();

  vscode.postMessage({
    type: "send_task",
    task,
    model: currentModel || undefined,
    plan_mode: planMode,
    file_mentions: fileMentions.length ? fileMentions : undefined,
  });
}
