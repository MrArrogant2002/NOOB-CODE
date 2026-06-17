/**
 * NOOB CODE — Permission gate helpers.
 *
 * The primary UI for permission requests lives inline in the webview chat
 * (panel.js renders the permission_request block). This module provides an
 * optional VS Code information-message popup that mirrors the webview buttons,
 * useful when the panel is hidden or the user misses the inline prompt.
 *
 * Called from panel.ts when a permission_request message arrives.
 */

import * as vscode from "vscode";
import { NoobCodeClient } from "./streaming";

/**
 * Show a VS Code information message popup for a shell/git permission request.
 * The user's response is forwarded to the backend via the WebSocket client.
 * The webview handles the same event independently for its inline UI.
 */
export async function showPermissionPopup(
  requestId: string,
  action: string,
  command: string,
  client: NoobCodeClient
): Promise<void> {
  const label = command.length > 60 ? command.slice(0, 57) + "..." : command;
  const pick = await vscode.window.showInformationMessage(
    `NOOB CODE wants to run: ${label}`,
    { modal: false },
    "Allow",
    "Allow Always",
    "Deny"
  );

  if (pick === "Allow") {
    client.sendPermission(requestId, "allow");
  } else if (pick === "Allow Always") {
    client.sendPermission(requestId, "always_allow");
  } else if (pick === "Deny") {
    client.sendPermission(requestId, "deny");
  }
  // If the user dismisses (pick === undefined), do nothing — the webview
  // inline buttons remain active for the user to click there.
  void action; // suppress unused-variable warning
}
