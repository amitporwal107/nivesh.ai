// Copilot chat adapter — calls POST /api/copilot/ask (the same endpoint V2's
// ChatView uses) and returns { response, model, mode, chart_count }. The
// caller owns history; we send the last 6 turns inline per the backend
// contract.

import { apiPost } from "./apiClient";

const MODEL_KEY_MAP = {
  "gpt-4o": "gpt-4o",
  "gpt-4o-mini": "gpt-4o-mini",
  "sonnet-4.6": "claude-sonnet-4-6",
  "opus-4.7": "claude-opus-4-7",
  "haiku-4.5": "claude-haiku-4-5",
  o3: "o3",
};

/**
 * Send a question to the copilot with optional rolling history.
 * @returns {Promise<{ ok: boolean, text: string, chartCount?: number, mode?: string, error?: any }>}
 */
export async function askCopilot({ question, history = [], model = "gpt-4o" }) {
  const mapped = MODEL_KEY_MAP[model] || model || "gemini";
  const payload = {
    model: mapped,
    question: (question || "").slice(0, 800),
    history: history.slice(-6).map((m) => ({
      role: m.role || (m.kind === "q" ? "user" : "assistant"),
      content: m.content || m.text || "",
    })),
  };
  const { data, error } = await apiPost("/copilot/ask", payload);
  if (error || !data) {
    return { ok: false, text: "", error };
  }
  return {
    ok: true,
    text: data.response || "",
    chartCount: data.chart_count || 0,
    mode: data.mode || null,
  };
}
