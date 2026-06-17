/**
 * NOOB CODE — Sidebar webview panel (WebviewViewProvider).
 *
 * Registered with VS Code as the provider for the "noobCodePanel" view.
 * Manages the chat webview lifetime, forwards WebSocket messages from the
 * backend into the webview, and routes webview postMessage events back to
 * the backend through the NoobCodeClient.
 *
 * The webview (panel.html / panel.js) never touches the network directly —
 * all I/O goes through this class.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { NoobCodeClient, TaskParams } from "./streaming";
import { openDiffEditor } from "./diff";
import { showPermissionPopup } from "./permissions";
import { readSettings } from "./settings";

export class NoobCodePanel implements vscode.WebviewViewProvider {
  static readonly viewId = "noobCodePanel";

  private view: vscode.WebviewView | undefined;
  private readonly client: NoobCodeClient;
  private readonly context: vscode.ExtensionContext;
  private currentSessionId: string | undefined;

  constructor(context: vscode.ExtensionContext, client: NoobCodeClient) {
    this.context = context;
    this.client = client;
    this._registerClientHandlers();
  }

  // ── WebviewViewProvider ───────────────────────────────────────────────────

  resolveWebviewView(
    view: vscode.WebviewView,
    _ctx: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this.view = view;

    const webviewUri = vscode.Uri.joinPath(this.context.extensionUri, "webview");
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [webviewUri],
    };
    view.webview.html = this._buildHtml(view.webview);

    view.webview.onDidReceiveMessage((msg: Record<string, unknown>) => {
      this._handleWebviewMessage(msg);
    });

    // Request model list so the dropdown populates immediately
    this.client.listModels();

    // Let the webview know whether we are already connected
    if (this.client.isConnected()) {
      this._post({ type: "connected" });
    }
  }

  // ── Called by extension.ts commands ──────────────────────────────────────

  /** Prefill task from outside (e.g. debugFix command). */
  prefillTask(task: string): void {
    this._post({ type: "prefill_task", task });
  }

  /** Start a task programmatically (called by debugFix). */
  sendTask(overrides: Partial<TaskParams> & { task: string }): void {
    const ws = this._workspace();
    const s = readSettings();
    this.client.sendTask({
      workspace: ws,
      model: s.defaultModel,
      plan_mode: s.planModeDefault,
      permission_mode: s.permissionMode,
      session_id: this.currentSessionId,
      ...overrides,
    });
  }

  // ── Webview → Extension messages ──────────────────────────────────────────

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private _handleWebviewMessage(msg: Record<string, any>): void {
    switch (msg.type as string) {
      case "send_task": {
        const ws = this._workspace();
        const s = readSettings();
        this.client.sendTask({
          task: msg.task as string,
          workspace: ws,
          model: (msg.model as string | undefined) ?? s.defaultModel,
          plan_mode: (msg.plan_mode as boolean | undefined) ?? s.planModeDefault,
          permission_mode: s.permissionMode,
          session_id: this.currentSessionId,
          file_mentions: msg.file_mentions as string[] | undefined,
        });
        break;
      }

      case "cancel":
        if (this.currentSessionId) {
          this.client.cancel(this.currentSessionId);
        }
        break;

      case "new_session":
        this.currentSessionId = undefined;
        this._post({ type: "cleared" });
        break;

      case "approval":
        this.client.sendApproval(
          msg.request_id as string,
          msg.decision as "approve" | "reject" | "approve_all"
        );
        break;

      case "permission":
        this.client.sendPermission(
          msg.request_id as string,
          msg.decision as "allow" | "deny" | "always_allow"
        );
        break;

      case "plan_execute":
        if (this.currentSessionId) {
          this.client.sendPlanExecute(this.currentSessionId);
        }
        break;

      case "plan_cancel":
        if (this.currentSessionId) {
          this.client.cancel(this.currentSessionId);
        }
        break;

      case "get_models":
        this.client.listModels();
        break;

      case "change_model":
        vscode.workspace
          .getConfiguration("noobCode")
          .update("defaultModel", msg.model as string, vscode.ConfigurationTarget.Global);
        break;

      case "open_diff":
        openDiffEditor(
          this._workspace(),
          msg.path as string,
          msg.new_content as string,
          msg.request_id as string,
          this.client
        );
        break;
    }
  }

  // ── Backend → Webview forwarding ──────────────────────────────────────────

  private _registerClientHandlers(): void {
    // Forward most messages directly to the webview
    const forward = (msg: Record<string, unknown>) => this._post(msg);

    for (const t of [
      "token",
      "tool_start",
      "tool_result",
      "edit_request",
      "permission_request",
      "plan_ready",
      "done",
      "warning",
      "error",
      "models_list",
      "session_info",
      "info",
    ]) {
      this.client.on(t, forward);
    }

    // Side-effects on specific messages
    this.client.on("hello", () => {
      this._post({ type: "connected" });
      this.client.listModels();
    });

    this.client.on("session_info", (msg) => {
      this.currentSessionId = msg.session_id as string;
    });

    // Show VS Code popup for permission requests (secondary UI — webview is primary)
    this.client.on("permission_request", (msg) => {
      showPermissionPopup(
        msg.request_id as string,
        msg.action as string,
        msg.command as string,
        this.client
      );
    });

    this.client.on("error", (msg) => {
      const text = msg.message as string;
      if (text.includes("API version mismatch") || text.includes("Unauthorized")) {
        vscode.window.showErrorMessage(`NOOB CODE: ${text}`);
      }
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  private _post(msg: Record<string, unknown>): void {
    this.view?.webview.postMessage(msg);
  }

  private _workspace(): string {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();
  }

  private _buildHtml(webview: vscode.Webview): string {
    const webviewDir = path.join(this.context.extensionPath, "webview");
    let html = fs.readFileSync(path.join(webviewDir, "panel.html"), "utf-8");

    const cssUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "webview", "panel.css")
    );
    const jsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "webview", "panel.js")
    );
    // Nonce prevents code injection via injected content
    const nonce = require("crypto").randomUUID().replace(/-/g, "");
    const csp = webview.cspSource;

    html = html
      .replace(/\{\{CSP_SOURCE\}\}/g, csp)
      .replace(/\{\{NONCE\}\}/g, nonce)
      .replace("{{CSS_URI}}", cssUri.toString())
      .replace("{{JS_URI}}", jsUri.toString());

    return html;
  }
}
