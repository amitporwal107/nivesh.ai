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
import { apiConfig } from "@/services/api/config";
import { getAuthToken } from "@/services/api/auth-token";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { z } from "zod";

/** Server-Sent-Event frames emitted by POST /api/chat/stream. */
export type StreamEvent =
  | { type: "meta"; session_id?: string; ai_msg_id?: string; user_msg_id?: string }
  | { type: "route"; agent?: string; confidence?: number }
  | { type: "thinking"; tool?: string; status?: "start" | "end" }
  | { type: "token"; content: string }
  | { type: "widget"; widget_type: string; data: unknown; [k: string]: unknown }
  | { type: "done"; content?: string; follow_ups?: string[] }
  | { type: "error"; content?: string };

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
  /** Stream the answer token-by-token via SSE. `onEvent` fires for every frame
   *  (meta/thinking/token/widget/done/error). Resolves when the stream ends. */
  streamSend(
    message: string,
    sessionId: string | undefined,
    onEvent: (ev: StreamEvent) => void,
    opts?: { page?: string; signal?: AbortSignal },
  ): Promise<void>;
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
  async streamSend(message, sessionId, onEvent, opts) {
    // SSE via fetch (EventSource can't POST). Cookie auth on web; the native app
    // adds Authorization: Bearer (the WebView drops the cross-site cookie, so
    // this raw fetch must carry the token like the http() client does).
    const token = getAuthToken();
    const activeProfileId = useImpersonationStore.getState().profileId;
    const res = await fetch(`${apiConfig.baseUrl}/api/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(activeProfileId ? { "X-Active-Profile": activeProfileId } : {}),
      },
      credentials: "include",
      body: JSON.stringify({ message, session_id: sessionId, page: opts?.page }),
      signal: opts?.signal,
    });
    if (!res.ok || !res.body) {
      onEvent({ type: "error", content: "Couldn't start the response stream." });
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE frames are separated by a blank line ("\n\n").
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 2);
        if (!raw.startsWith("data:")) continue;
        const payload = raw.slice(5).trim();
        if (!payload) continue;
        try {
          onEvent(JSON.parse(payload) as StreamEvent);
        } catch {
          /* ignore a malformed/partial frame */
        }
      }
    }
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
