/**
 * NOOB CODE — VS Code diff editor integration.
 *
 * When the backend sends an edit_request, the webview shows inline Approve/Reject
 * buttons. Optionally the user can also open a proper side-by-side VS Code diff
 * editor via the "Open Diff" button (which posts an open_diff message from panel.js).
 *
 * Uses an in-memory TextDocumentContentProvider so we never write temp files.
 */

import * as vscode from "vscode";
import * as path from "path";
import { NoobCodeClient } from "./streaming";

const SCHEME = "noob-code-diff";

class DiffContentProvider implements vscode.TextDocumentContentProvider {
  private readonly contents = new Map<string, string>();

  set(uri: vscode.Uri, content: string): void {
    this.contents.set(uri.toString(), content);
  }

  delete(uri: vscode.Uri): void {
    this.contents.delete(uri.toString());
  }

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.contents.get(uri.toString()) ?? "";
  }
}

let _provider: DiffContentProvider | undefined;

export function registerDiffProvider(context: vscode.ExtensionContext): void {
  _provider = new DiffContentProvider();
  context.subscriptions.push(
    vscode.workspace.registerTextDocumentContentProvider(SCHEME, _provider)
  );
}

/**
 * Open VS Code's built-in diff editor showing the proposed change.
 * Called when the user clicks "Open Diff" in the webview panel.
 *
 * @param workspace  Absolute path to the repo root.
 * @param filePath   Relative or absolute path to the file being edited.
 * @param newContent Full proposed file content after the edit.
 * @param requestId  Matches the edit_request.request_id from the backend.
 * @param client     Used to send the approval response after user action.
 */
export async function openDiffEditor(
  workspace: string,
  filePath: string,
  newContent: string,
  requestId: string,
  client: NoobCodeClient
): Promise<void> {
  if (!_provider) {
    return;
  }

  const absPath = path.isAbsolute(filePath) ? filePath : path.join(workspace, filePath);
  const basename = path.basename(filePath);

  // Read original content from disk (empty string for new files)
  let originalContent = "";
  try {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(absPath));
    originalContent = doc.getText();
  } catch {
    // New file — original is empty
  }

  // Register in-memory content for both sides
  const originalUri = vscode.Uri.parse(
    `${SCHEME}:original-${requestId}/${encodeURIComponent(basename)}`
  );
  const proposedUri = vscode.Uri.parse(
    `${SCHEME}:proposed-${requestId}/${encodeURIComponent(basename)}`
  );

  _provider.set(originalUri, originalContent);
  _provider.set(proposedUri, newContent);

  await vscode.commands.executeCommand(
    "vscode.diff",
    originalUri,
    proposedUri,
    `NOOB CODE: ${basename} (review changes)`,
    { preview: true }
  );

  // Offer quick-pick buttons via notification
  const pick = await vscode.window.showInformationMessage(
    `NOOB CODE: Apply changes to ${basename}?`,
    { modal: false },
    "Approve",
    "Reject"
  );

  client.sendApproval(requestId, pick === "Approve" ? "approve" : "reject");

  // Clean up in-memory content
  _provider.delete(originalUri);
  _provider.delete(proposedUri);
}
