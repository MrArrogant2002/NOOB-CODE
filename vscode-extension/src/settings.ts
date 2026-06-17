/**
 * NOOB CODE — VS Code settings bridge.
 *
 * Reads the VS Code configuration for noobCode.* and returns a plain object
 * that can be attached to outgoing task messages so the backend knows the
 * current permission mode, model, and other user preferences.
 */

import * as vscode from "vscode";

export interface NoobCodeSettings {
  ollamaUrl: string;
  defaultModel: string;
  backendPort: number;
  planModeDefault: boolean;
  permissionMode: "ask" | "auto-approve" | "yolo";
  gpuLayers: number;
  maxContextTokens: number;
  dockerEnabled: boolean;
}

export function readSettings(): NoobCodeSettings {
  const cfg = vscode.workspace.getConfiguration("noobCode");
  return {
    ollamaUrl: cfg.get<string>("ollamaUrl", "http://localhost:11434/v1"),
    defaultModel: cfg.get<string>("defaultModel", "qwen2.5-coder:7b"),
    backendPort: cfg.get<number>("backendPort", 7867),
    planModeDefault: cfg.get<boolean>("planModeDefault", false),
    permissionMode: cfg.get<"ask" | "auto-approve" | "yolo">("permissionMode", "ask"),
    gpuLayers: cfg.get<number>("gpuLayers", -1),
    maxContextTokens: cfg.get<number>("maxContextTokens", 0),
    dockerEnabled: cfg.get<boolean>("dockerEnabled", true),
  };
}

/** Returns a plain object with only the fields the backend task message cares about. */
export function taskSettingsFor(workspace: string): {
  model: string;
  plan_mode: boolean;
  permission_mode: string;
} {
  const s = readSettings();
  return {
    model: s.defaultModel,
    plan_mode: s.planModeDefault,
    permission_mode: s.permissionMode,
  };
  void workspace;
}
