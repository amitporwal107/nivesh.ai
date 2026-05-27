/**
 * Chat adapter — AI Copilot.
 *
 *   POST  /api/chat                       { message, session_id? } → reply
 *   GET   /api/chat/sessions              → list
 *   POST  /api/chat/sessions              { title? } → created
 *   GET   /api/chat/sessions/{id}         → messages
 *   DELETE /api/chat/sessions/{id}
 *   GET   /api/copilot/suggested-prompts  → 5 prompts
 *
 * Streaming is supported by the backend per the spec; this v1 wraps the
 * non-streaming JSON response only. Streaming wire-up is a follow-on.
 */
import { http } from "@/services/api/http";
import { z } from "zod";

export const ChatMessageC = z.object({
  id: z.string().optional(),
  role: z.enum(["user", "assistant", "system"]).or(z.string()),
  content: z.string(),
  created_at: z.string().optional(),
}).passthrough();
export type ChatMessageC = z.infer<typeof ChatMessageC>;

export const ChatSendRes = z.object({
  reply: z.string().optional(),
  message: ChatMessageC.optional(),
  session_id: z.string().optional(),
}).passthrough();

export interface ChatAdapter {
  send(message: string, sessionId?: string): Promise<{ reply: string; sessionId?: string }>;
  listSessions(): Promise<unknown[]>;
  createSession(title?: string): Promise<{ id: string }>;
  getSession(id: string): Promise<{ messages: ChatMessageC[] }>;
  suggestedPrompts(): Promise<string[]>;
}

export const realChatAdapter: ChatAdapter = {
  async send(message, sessionId) {
    const res = await http({ method: "POST", path: "/api/chat", body: { message, session_id: sessionId } });
    const parsed = ChatSendRes.safeParse(res.data);
    if (parsed.success) {
      return {
        reply: parsed.data.reply ?? parsed.data.message?.content ?? "",
        sessionId: parsed.data.session_id,
      };
    }
    return { reply: typeof res.data === "string" ? res.data : "" };
  },
  async listSessions() {
    const res = await http({ path: "/api/chat/sessions" });
    return Array.isArray(res.data) ? res.data : [];
  },
  async createSession(title) {
    const res = await http({ method: "POST", path: "/api/chat/sessions", body: { title } });
    const obj = res.data as { id?: string; session_id?: string };
    return { id: obj.id ?? obj.session_id ?? "" };
  },
  async getSession(id) {
    const res = await http({ path: `/api/chat/sessions/${encodeURIComponent(id)}` });
    const obj = res.data as { messages?: unknown[] };
    const messages = Array.isArray(obj.messages) ? obj.messages : [];
    return { messages: messages.map((m) => ChatMessageC.parse(m)) };
  },
  async suggestedPrompts() {
    const res = await http({ path: "/api/copilot/suggested-prompts" });
    const obj = res.data as { prompts?: Array<{ text?: string } | string> };
    if (!Array.isArray(obj.prompts)) return [];
    return obj.prompts.map((p) => typeof p === "string" ? p : p.text ?? "").filter(Boolean);
  },
};
