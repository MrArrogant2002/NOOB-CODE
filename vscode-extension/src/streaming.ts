/**
 * NOOB CODE — WebSocket client running in the Node.js extension host.
 *
 * Connects to the Python FastAPI backend at ws://127.0.0.1:<port>/ws?token=<token>,
 * performs the hello/hello_ack version handshake, and exposes typed send/on/off
 * methods. Webview ↔ extension communication happens via postMessage (panel.ts);
 * this module only handles the extension host ↔ backend connection.
 *
 * Reconnect strategy: exponential backoff (1s → 2s → 4s → 8s → 16s → 30s).
 * After 6 failed attempts the user sees a VS Code error notification.
 */

import * as vscode from "vscode";
import WebSocket from "ws";

export type ServerMessageType =
  | "hello"
  | "token"
  | "tool_start"
  | "tool_result"
  | "edit_request"
  | "permission_request"
  | "plan_ready"
  | "done"
  | "warning"
  | "error"
  | "models_list"
  | "session_info"
  | "session_history"
  | "sessions_list"
  | "info";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Handler = (msg: Record<string, any>) => void;

const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];
const API_VERSION = "1";

export interface TaskParams {
  task: string;
  workspace: string;
  model: string;
  session_id?: string;
  plan_mode?: boolean;
  allow_test_edits?: boolean;
  permission_mode?: string;
  file_mentions?: string[];
}

export class NoobCodeClient {
  private ws: WebSocket | undefined;
  private port = 7867;
  private token = "";
  private handlers = new Map<string, Set<Handler>>();
  private reconnectAttempts = 0;
  private reconnectTimer: NodeJS.Timeout | undefined;
  private intentionallyClosed = false;
  private _connected = false;

  // ── Public API ────────────────────────────────────────────────────────────

  connect(port: number, token: string): void {
    this.port = port;
    this.token = token;
    this.intentionallyClosed = false;
    this._open();
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    this.ws?.close();
    this.ws = undefined;
    this._connected = false;
  }

  isConnected(): boolean {
    return this._connected;
  }

  sendTask(params: TaskParams): void {
    this._send({ type: "task", ...params });
  }

  sendApproval(requestId: string, decision: "approve" | "reject" | "approve_all"): void {
    this._send({ type: "approval", request_id: requestId, decision });
  }

  sendPermission(requestId: string, decision: "allow" | "deny" | "always_allow"): void {
    this._send({ type: "permission", request_id: requestId, decision });
  }

  sendPlanExecute(sessionId: string): void {
    this._send({ type: "plan_execute", session_id: sessionId });
  }

  cancel(sessionId: string): void {
    this._send({ type: "cancel", session_id: sessionId });
  }

  listModels(): void {
    this._send({ type: "list_models" });
  }

  reindex(workspace: string): void {
    this._send({ type: "reindex", workspace });
  }

  sendFileChanged(filePath: string, workspace: string): void {
    this._send({ type: "file_changed", path: filePath, workspace });
  }

  on(event: string, callback: Handler): void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(callback);
  }

  off(event: string, callback: Handler): void {
    this.handlers.get(event)?.delete(callback);
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  private _open(): void {
    const url = `ws://127.0.0.1:${this.port}/ws?token=${encodeURIComponent(this.token)}`;
    this.ws = new WebSocket(url);

    this.ws.on("open", () => {
      this.reconnectAttempts = 0;
    });

    this.ws.on("message", (data: WebSocket.RawData) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(data.toString());
      } catch {
        return;
      }
      const type = msg.type as string;

      if (type === "hello") {
        const serverVersion = msg.api_version as string;
        if (serverVersion !== API_VERSION) {
          vscode.window.showErrorMessage(
            `NOOB CODE: API version mismatch (extension v${API_VERSION}, backend v${serverVersion}). ` +
              "Run: python setup.py --update"
          );
        }
        this._send({ type: "hello_ack", api_version: API_VERSION });
        this._connected = true;
      }

      const set = this.handlers.get(type);
      if (set) {
        for (const h of set) {
          h(msg);
        }
      }
    });

    this.ws.on("error", () => {
      // "close" fires next; let it handle reconnect
    });

    this.ws.on("close", (code: number) => {
      this._connected = false;
      this._emit("disconnected", { type: "disconnected" });
      if (this.intentionallyClosed) {
        return;
      }
      if (code === 4001) {
        vscode.window.showErrorMessage(
          "NOOB CODE: Authentication failed — session token mismatch. Run: python setup.py --update"
        );
        return;
      }
      this._scheduleReconnect();
    });
  }

  private _emit(type: string, data: Record<string, unknown>): void {
    const set = this.handlers.get(type);
    if (set) {
      for (const h of set) {
        h(data);
      }
    }
  }

  private _send(data: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private _scheduleReconnect(): void {
    if (this.reconnectAttempts >= BACKOFF_MS.length) {
      vscode.window.showErrorMessage(
        "NOOB CODE: Backend disconnected after multiple retries. " +
          "Reload the window to reconnect (Ctrl+Shift+P → Reload Window)."
      );
      return;
    }
    const delay = BACKOFF_MS[this.reconnectAttempts];
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      if (!this.intentionallyClosed) {
        this._open();
      }
    }, delay);
  }
}
