/**
 * NOOB CODE VS Code Extension — activation entry point.
 *
 * Startup sequence:
 *  1. Read (or wait for) the session token written by the Python backend.
 *  2. Check whether the backend is already running on the configured port.
 *     If not, spawn it as a child process.
 *  3. Poll /health until the backend is ready (up to 30 s).
 *  4. Connect the NoobCodeClient WebSocket.
 *  5. Register the NoobCodePanel as a WebviewViewProvider.
 *  6. Register all commands.
 *
 * Risk 1 (multiple VS Code windows → port conflict) is handled by the Python
 * backend's daemon.py lockfile; the extension just checks /health first and
 * skips spawning if a server is already live.
 */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import * as http from "http";
import { ChildProcess, spawn } from "child_process";
import { NoobCodeClient } from "./streaming";
import { NoobCodePanel } from "./panel";
import { registerDiffProvider } from "./diff";

let backendProcess: ChildProcess | undefined;
let outputChannel: vscode.OutputChannel;
let panelProvider: NoobCodePanel | undefined;

// ── Activation ────────────────────────────────────────────────────────────────

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  outputChannel = vscode.window.createOutputChannel("NOOB CODE Backend");
  context.subscriptions.push(outputChannel);

  // Register the in-memory diff content provider (used by diff.ts)
  registerDiffProvider(context);

  const port = vscode.workspace
    .getConfiguration("noobCode")
    .get<number>("backendPort", 7867);

  // Start backend if not already alive (Risk 1: check health first)
  const alreadyRunning = await checkHealth(port);
  if (!alreadyRunning) {
    backendProcess = startBackend(context, port);
    const ready = await waitForHealth(port, 30_000);
    if (!ready) {
      vscode.window.showErrorMessage(
        "NOOB CODE: Backend did not start within 30 s. " +
          "Check the 'NOOB CODE Backend' output channel for errors."
      );
      return;
    }
  }

  // Read the session token from the file the backend wrote on startup
  const token = await readSessionToken(context, port);

  // Create the WebSocket client and connect
  const client = new NoobCodeClient();
  client.connect(port, token);
  context.subscriptions.push({ dispose: () => client.disconnect() });

  // Create and register the sidebar panel
  panelProvider = new NoobCodePanel(context, client);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(NoobCodePanel.viewId, panelProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );

  // Register all commands
  context.subscriptions.push(
    vscode.commands.registerCommand("noobCode.openPanel", () => {
      vscode.commands.executeCommand("workbench.view.extension.noob-code-container");
    }),

    vscode.commands.registerCommand("noobCode.newTask", () => {
      vscode.commands.executeCommand("workbench.view.extension.noob-code-container");
    }),

    vscode.commands.registerCommand("noobCode.debugFix", () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showWarningMessage("NOOB CODE: Open a file first.");
        return;
      }
      const filePath = editor.document.fileName;
      const relPath = path.basename(filePath);
      // Open the panel and pre-send the debug task
      vscode.commands.executeCommand("workbench.view.extension.noob-code-container");
      panelProvider?.sendTask({
        task: `Run the tests. If they fail, use debug_fix on ${relPath} to repair the issue. Do not edit test files.`,
      });
    }),

    vscode.commands.registerCommand("noobCode.newSession", () => {
      vscode.commands.executeCommand("workbench.view.extension.noob-code-container");
      panelProvider?.prefillTask(""); // triggers cleared + new session in webview
    }),

    vscode.commands.registerCommand("noobCode.exportSession", async () => {
      const uri = await vscode.window.showSaveDialog({
        defaultUri: vscode.Uri.file("noob-code-session.md"),
        filters: { Markdown: ["md"] },
      });
      if (uri && client.isConnected()) {
        client["_send"]?.({ type: "export_session", output_path: uri.fsPath });
        vscode.window.showInformationMessage(`NOOB CODE: Exporting session to ${uri.fsPath}`);
      }
    }),

    vscode.commands.registerCommand("noobCode.reindex", () => {
      if (client.isConnected()) {
        const ws = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        if (ws) {
          client.reindex(ws);
          vscode.window.showInformationMessage("NOOB CODE: Re-indexing workspace...");
        }
      }
    }),

    // Debounced re-index on every file save — the backend enforces the 30 s cooldown
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (!client.isConnected()) {
        return;
      }
      const folder = vscode.workspace.getWorkspaceFolder(doc.uri);
      if (folder) {
        client.sendFileChanged(doc.uri.fsPath, folder.uri.fsPath);
      }
    })
  );
}

// ── Deactivation ──────────────────────────────────────────────────────────────

export function deactivate(): void {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
    backendProcess = undefined;
  }
}

// ── Backend lifecycle ──────────────────────────────────────────────────────────

function startBackend(context: vscode.ExtensionContext, port: number): ChildProcess {
  // Extension lives inside vscode-extension/; the Python project is one level up
  const projectRoot = path.resolve(context.extensionPath, "..");
  const python = process.platform === "win32" ? "python" : "python3";

  outputChannel.appendLine(`[NOOB CODE] Starting backend on port ${port}…`);

  const proc = spawn(
    python,
    ["-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: projectRoot, env: { ...process.env } }
  );

  proc.stdout?.on("data", (d: Buffer) => outputChannel.append(d.toString()));
  proc.stderr?.on("data", (d: Buffer) => outputChannel.append(d.toString()));
  proc.on("exit", (code) =>
    outputChannel.appendLine(`[NOOB CODE] Backend exited (code ${code})`)
  );

  return proc;
}

function checkHealth(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForHealth(port: number, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await sleep(500);
    if (await checkHealth(port)) {
      return true;
    }
  }
  return false;
}

async function readSessionToken(
  context: vscode.ExtensionContext,
  port: number
): Promise<string> {
  // The backend writes the token to data/.session_token relative to the project root
  const projectRoot = path.resolve(context.extensionPath, "..");
  const tokenPath = path.join(projectRoot, "data", ".session_token");

  // Wait up to 5 s for the file to appear (backend writes it on first startup)
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    try {
      const token = fs.readFileSync(tokenPath, "utf-8").trim();
      if (token) {
        return token;
      }
    } catch {
      // File not yet created
    }
    await sleep(200);
  }

  outputChannel.appendLine("[NOOB CODE] Warning: session token file not found — connecting without auth.");
  void port;
  return "";
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
