/**
 * Chat adapter — AI Copilot.
 *
 *   POST  /api/chat/send                  { message, session_id? } → {user_message, ai_message}
 *   GET   /api/chat/sessions              → list
 *   POST  /api/chat/sessions              { title? } → created
 *   GET   /api/chat/messages?session_id=  → messages (no GET /sessions/{id} exists)
 *   DELETE /api/chat/sessions/{id}
 *   GET   /api/copilot/suggested-prompts  → 5 prompts
 *
 * NOTE: The send endpoint is /api/chat/send (not /api/chat).
 * Response shape: {user_message: {content, role, ...}, ai_message: {content, role, ...}}
 */
import { http } from "@/services/api/http";
import { z } from "zod";

export const ChatMessageC = z.object({
  id: z.string().optional(),
  role: z.enum(["user", "assistant", "system"]).or(z.string()),
  content: z.string(),
  created_at: z.string().optional(),
  // Structured widget envelope: { widget_type, data, ... }. Rendered below the
  // bubble by ChatWidget. passthrough already preserves it; typed here for use.
  widget: z.object({ widget_type: z.string(), data: z.any() }).passthrough().optional(),
}).passthrough();
export type ChatMessageC = z.infer<typeof ChatMessageC>;

// Backend returns {user_message, ai_message} — each is a full ChatMessage
export const ChatSendRes = z.object({
  user_message: ChatMessageC.optional(),
  ai_message:   ChatMessageC.optional(),
  // Legacy/alternate shapes
  reply:         z.string().optional(),
  message:       ChatMessageC.optional(),
  session_id:    z.string().optional(),
}).passthrough();

export interface ChatAdapter {
  /** `page` is the human-readable dashboard label the user is viewing when
   *  asking from the global Copilot dock (e.g. "Risk"). Omitted on the full
   *  chat page. */
  send(message: string, sessionId?: string, page?: string): Promise<{ reply: string; sessionId?: string }>;
  listSessions(): Promise<ChatSession[]>;
  createSession(title?: string): Promise<{ id: string }>;
  getSession(id: string): Promise<{ messages: ChatMessageC[] }>;
  deleteSession(id: string): Promise<void>;
  suggestedPrompts(): Promise<string[]>;
}

export interface ChatSession {
  id: string;
  title: string;
  updatedAt?: string;
}

export const realChatAdapter: ChatAdapter = {
  async send(message, sessionId, page) {
    // Chat runs a reasoning model + tools and legitimately takes 20-30s — far
    // past the 15s default. Use a generous timeout, and noRetry because
    // /chat/send is non-idempotent (a retry creates duplicate messages).
    const res = await http({
      method: "POST",
      path: "/api/chat/send",
      body: { message, session_id: sessionId, page },
      timeoutMs: 90_000,
      noRetry: true,
    });
    const parsed = ChatSendRes.safeParse(res.data);
    if (parsed.success) {
      const d = parsed.data;
      // Real shape: {ai_message: {content, ...}, user_message: {...}}
      const reply = d.ai_message?.content ?? d.reply ?? d.message?.content ?? "";
      const sid: string | undefined = d.session_id ?? sessionId;
      return { reply, sessionId: sid };
    }
    return { reply: typeof res.data === "string" ? res.data : "" };
  },
  async listSessions() {
    // Backend returns raw session docs sorted by updated_at desc, each with
    // session_id + an auto-title (first 50 chars of the first user message).
    const res = await http({ path: "/api/chat/sessions" });
    const arr = Array.isArray(res.data) ? res.data : [];
    return arr
      .map((s) => {
        const o = s as { session_id?: string; id?: string; title?: string; updated_at?: string; created_at?: string };
        return {
          id: o.session_id ?? o.id ?? "",
          title: (o.title && o.title.trim()) || "New conversation",
          updatedAt: o.updated_at ?? o.created_at,
        };
      })
      .filter((s) => s.id);
  },
  async createSession(title) {
    const res = await http({ method: "POST", path: "/api/chat/sessions", body: { title } });
    const obj = res.data as { id?: string; session_id?: string };
    return { id: obj.id ?? obj.session_id ?? "" };
  },
  async deleteSession(id) {
    await http({ method: "DELETE", path: `/api/chat/sessions/${id}` });
  },
  async getSession(id) {
    // History lives at GET /api/chat/messages?session_id= (returns an array).
    // There is no GET /api/chat/sessions/{id} on the backend.
    const res = await http({ path: "/api/chat/messages", query: { session_id: id } });
    const raw = Array.isArray(res.data)
      ? res.data
      : (res.data as { messages?: unknown[] })?.messages ?? [];
    return { messages: raw.map((m) => ChatMessageC.parse(m)) };
  },
  async suggestedPrompts() {
    const res = await http({ path: "/api/copilot/suggested-prompts" });
    const obj = res.data as { prompts?: Array<{ label?: string; text?: string; query?: string; id?: string; icon?: string } | string> };
    if (!Array.isArray(obj.prompts)) return [];
    return obj.prompts.map((p) => typeof p === "string" ? p : (p.label ?? p.text ?? p.query ?? "")).filter(Boolean);
  },
};
