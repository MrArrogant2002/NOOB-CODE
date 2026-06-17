/**
 * NOOB CODE — Ollama model list helper.
 *
 * Fetches the available models from the backend's REST endpoint and returns
 * a typed list. The result is sent to the webview to populate the model
 * dropdown. Called on panel open and on model-list refresh.
 */

import * as http from "http";

export interface ModelInfo {
  name: string;
  context_length?: number;
  size?: string;
}

/**
 * GET /models from the NOOB CODE backend.
 * Resolves with the model list; rejects on network error or non-200 status.
 */
export function fetchModels(port: number): Promise<ModelInfo[]> {
  return new Promise((resolve, reject) => {
    const req = http.get(`http://127.0.0.1:${port}/models`, (res) => {
      let body = "";
      res.on("data", (chunk: Buffer) => (body += chunk.toString()));
      res.on("end", () => {
        if (res.statusCode !== 200) {
          reject(new Error(`/models returned ${res.statusCode}`));
          return;
        }
        try {
          const data = JSON.parse(body) as { models: ModelInfo[] };
          resolve(data.models ?? []);
        } catch (e) {
          reject(e);
        }
      });
    });
    req.on("error", reject);
    req.setTimeout(5000, () => {
      req.destroy();
      reject(new Error("Timeout fetching models"));
    });
  });
}

/** Format a model entry for display in the dropdown. */
export function formatModelLabel(m: ModelInfo): string {
  const parts = [m.name];
  if (m.context_length) {
    parts.push(`${Math.round(m.context_length / 1024)}k ctx`);
  }
  if (m.size) {
    parts.push(m.size);
  }
  return parts.join(" — ");
}
