import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Plus, Send, History as HistoryIcon, Trash2, X, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import {
  useSuggestedPrompts,
  useChatSession,
  useChatSessions,
  useCreateChatSession,
  useDeleteChatSession,
} from "@/hooks/use-chat";
import { chatService } from "@/services";
import { Skeleton } from "@/components/ui/skeleton";
import { ChatWidget } from "@/components/chat/ChatWidget";
import { Markdown } from "@/components/chat/Markdown";

type StreamState = { content: string; thinking?: string; widget?: { widget_type: string; data: unknown }; error?: string };

const WIDGET_TYPES = new Set(["fund_consolidation", "fund_overlap", "overlap_severity", "risk_overview", "cap_education", "concentration", "allocation_review", "instrument_detail", "risk_assessment", "goal_simulation"]);

const FALLBACK_PROMPTS = [
  "Why is my score 74?",
  "Which funds overlap most?",
  "How risky is my portfolio?",
  "What should I reduce first?",
];

/** Compact relative time for the history list ("2m ago", "3d ago"). */
function relTime(iso?: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function ChatPage() {
  const [composer, setComposer] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [historyOpen, setHistoryOpen] = useState(false); // mobile drawer
  // Icon-only collapse of the history rail (desktop), persisted across sessions.
  const [historyCollapsed, setHistoryCollapsed] = useState<boolean>(
    () => localStorage.getItem("nv-chat-history-collapsed") === "1",
  );
  useEffect(() => {
    localStorage.setItem("nv-chat-history-collapsed", historyCollapsed ? "1" : "0");
  }, [historyCollapsed]);

  const prompts = useSuggestedPrompts();
  const qc = useQueryClient();
  const createSession = useCreateChatSession();
  const deleteSession = useDeleteChatSession();
  const sessions = useChatSessions();
  const session = useChatSession(sessionId ?? "");

  // Live streaming state for the in-flight answer + the optimistic user bubble.
  const [streaming, setStreaming] = useState<StreamState | null>(null);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const isBusy = streaming !== null;

  const messages = session.data?.messages ?? [];
  const sessionList = sessions.data ?? [];

  // Stream the answer token-by-token via SSE. The server persists both the user
  // and AI messages, so when the stream ends we just refetch history and drop
  // the local streaming/optimistic state.
  const submitMessage = async (text: string) => {
    const t = text.trim();
    if (!t || isBusy) return;
    let sid = sessionId;
    if (!sid) {
      const created = await createSession.mutateAsync(undefined);
      sid = created.id;
      setSessionId(sid);
    }
    setPendingUser(t);
    setStreaming({ content: "" });
    try {
      await chatService.streamSend(t, sid, (ev) => {
        setStreaming((s) => {
          if (!s) return s;
          switch (ev.type) {
            case "thinking": return { ...s, thinking: ev.status === "start" ? ev.tool : undefined };
            case "token":    return { ...s, content: s.content + (ev.content ?? ""), thinking: undefined };
            case "widget":   return { ...s, widget: { widget_type: ev.widget_type, data: ev.data } };
            case "error":    return { ...s, error: ev.content };
            default:         return s;
          }
        });
      });
    } catch {
      setStreaming((s) => (s ? { ...s, error: "Connection interrupted — please try again." } : s));
    }
    setStreaming(null);
    setPendingUser(null);
    qc.invalidateQueries({ queryKey: ["chat", "sessions", sid] });
    qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
  };

  const handleSend = async () => {
    const text = composer.trim();
    if (!text || isBusy) return;
    setComposer("");
    await submitMessage(text);
  };

  // Widget action chips → drive a follow-up. Some send immediately; "recalc"
  // prefills the composer so the user can type their real SIP amount.
  const handleWidgetAction = (a: { intent?: string; query?: string; label?: string }) => {
    if (a.intent === "review_overlap") void submitMessage("Which of my funds overlap the most?");
    else if (a.intent === "recalc_sip") setComposer("Recalculate my retirement plan with a monthly SIP of ₹");
    else if (a.query) void submitMessage(a.query);
    else if (a.label) void submitMessage(a.label);
  };

  // Start a fresh thread — old conversations stay in history.
  const handleNewChat = () => {
    setSessionId(undefined);
    setComposer("");
    setHistoryOpen(false);
  };

  const handleOpen = (id: string) => {
    setSessionId(id);
    setHistoryOpen(false);
  };

  // Delete a conversation (and its messages) from history.
  const handleDelete = async (id: string) => {
    await deleteSession.mutateAsync(id);
    if (id === sessionId) setSessionId(undefined);
  };

  // "Clear chat" — delete the conversation currently open, then reset.
  const handleClearCurrent = async () => {
    if (!sessionId || deleteSession.isPending) return;
    if (!window.confirm("Delete this conversation? This can't be undone.")) return;
    await deleteSession.mutateAsync(sessionId);
    setSessionId(undefined);
    setComposer("");
  };

  const promptList = prompts.data && prompts.data.length > 0 ? prompts.data : FALLBACK_PROMPTS;

  return (
    <div className="flex min-h-[calc(100vh-4rem)]">
      {/* ── History sidebar (static on md+, slide-over drawer on mobile) ── */}
      <aside
        className={cn(
          "shrink-0 w-64 border-r border-hairline bg-surface-1/40 flex-col transition-[width] duration-200",
          historyCollapsed && "md:w-14",
          historyOpen
            ? "flex fixed inset-y-0 left-0 z-30 bg-bg shadow-xl md:static md:shadow-none md:bg-surface-1/40"
            : "hidden md:flex",
        )}
      >
        {/* Collapsed rail — desktop only, icons only */}
        <div className={cn("hidden flex-col items-center gap-2 p-2", historyCollapsed && "md:flex")}>
          <button
            onClick={handleNewChat}
            className="p-2 rounded-md border border-hairline-2 text-ink hover:bg-surface-2 transition-colors"
            aria-label="New chat"
            title="New chat"
          >
            <Plus className="h-4 w-4" />
          </button>
          <button
            onClick={() => setHistoryCollapsed(false)}
            className="p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors"
            aria-label="Expand history"
            title="Expand history"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </div>

        {/* Full panel — mobile drawer + expanded desktop */}
        <div className={cn("flex flex-col flex-1 min-h-0", historyCollapsed && "md:hidden")}>
          <div className="p-3 flex items-center gap-2">
            <button
              onClick={handleNewChat}
              className="flex-1 flex items-center gap-2 px-3 py-2 rounded-md border border-hairline-2 text-[13px] text-ink hover:bg-surface-2 transition-colors"
            >
              <Plus className="h-4 w-4" /> New chat
            </button>
            <button
              onClick={() => setHistoryCollapsed(true)}
              className="hidden md:inline-flex p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors"
              aria-label="Collapse history"
              title="Collapse history"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
            <button onClick={() => setHistoryOpen(false)} className="md:hidden p-2 text-ink-3" aria-label="Close history">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="px-4 pb-1.5 font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">History</div>
          <div className="flex-1 overflow-y-auto px-2 pb-3">
            {sessions.isPending && Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full rounded-md mb-1.5" />
            ))}
            {!sessions.isPending && sessionList.length === 0 && (
              <p className="px-3 py-2 text-[12.5px] text-ink-3 leading-relaxed">No conversations yet. Start one on the right.</p>
            )}
            {sessionList.map((s) => (
              <div
                key={s.id}
                onClick={() => handleOpen(s.id)}
                className={cn(
                  "group flex items-center justify-between gap-2 px-3 py-2 rounded-md cursor-pointer transition-colors",
                  s.id === sessionId ? "bg-surface-2" : "hover:bg-surface-2/60",
                )}
              >
                <div className="min-w-0">
                  <div className="truncate text-[13px] text-ink">{s.title}</div>
                  {s.updatedAt && <div className="text-[11px] text-ink-3 mt-0.5">{relTime(s.updatedAt)}</div>}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); void handleDelete(s.id); }}
                  className="opacity-0 group-hover:opacity-100 focus:opacity-100 p-1 rounded text-ink-3 hover:text-neg transition"
                  aria-label="Delete conversation"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* mobile backdrop */}
      {historyOpen && <div className="fixed inset-0 bg-black/30 z-20 md:hidden" onClick={() => setHistoryOpen(false)} />}

      {/* ── Conversation column ── */}
      <div className="flex-1 min-w-0 flex flex-col px-6 py-8 lg:px-10 lg:py-10 max-w-[880px] mx-auto w-full">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Chat</div>
            <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
              Ask anything about your portfolio.
            </h1>
          </div>
          <div className="flex items-center gap-2 shrink-0 mt-1">
            <button
              onClick={() => setHistoryOpen(true)}
              className="md:hidden flex items-center gap-1.5 px-3 py-2 rounded-md border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-2 transition-colors"
            >
              <HistoryIcon className="h-3.5 w-3.5" /> History
            </button>
            {messages.length > 0 && (
              <button
                onClick={handleClearCurrent}
                disabled={deleteSession.isPending}
                className="flex items-center gap-1.5 px-3 py-2 rounded-md border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-2 disabled:opacity-50 transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" /> Clear chat
              </button>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2 mt-6">
          {prompts.isPending && Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-40 rounded-full" />
          ))}
          {!prompts.isPending && promptList.map((q) => (
            <button
              key={q}
              onClick={() => setComposer(q)}
              className="px-3.5 py-2 rounded-full bg-surface-2 border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-3 transition-colors"
            >
              {q}
            </button>
          ))}
        </div>

        <div className="mt-7 flex-1 flex flex-col gap-5">
          {messages.length === 0 && !isBusy && !pendingUser && (
            <div className="flex flex-col items-center text-center mt-6">
              <Badge tone="accent" className="mb-3">Ready</Badge>
              <p className="text-ink-2 text-[14px] max-w-md leading-relaxed">
                Pick a question above or type your own. I'll read your portfolio first, then answer in plain English.
              </p>
            </div>
          )}

          {messages.map((m, i) => {
            const isUser = m.role === "user";
            const widget = !isUser ? (m as { widget?: { widget_type?: string; data?: unknown } }).widget : undefined;
            const hasWidget = !!widget?.widget_type && WIDGET_TYPES.has(widget.widget_type);
            return (
              <div key={m.id ?? i} className={cn(isUser ? "self-end max-w-[520px] px-4 py-3 rounded-2xl rounded-br-md bg-surface-2 border border-hairline" : "flex gap-3.5")}>
                {!isUser && (
                  <span className="grid place-items-center h-9 w-9 rounded-md bg-ink text-on-accent font-display text-base leading-none shrink-0">न</span>
                )}
                <div className={isUser ? "" : "flex-1 min-w-0"}>
                  {isUser ? (
                    <p className="text-[14px]">{m.content}</p>
                  ) : (
                    <>
                      {hasWidget && <ChatWidget widget={widget} onAction={handleWidgetAction} />}
                      {m.content?.trim() && (
                        <Markdown className={cn("text-[15.5px] leading-relaxed text-ink-2", hasWidget && "mt-3")}>
                          {m.content}
                        </Markdown>
                      )}
                    </>
                  )}
                </div>
              </div>
            );
          })}

          {/* optimistic user bubble (its persisted copy replaces it on refetch) */}
          {pendingUser && (
            <div className="self-end max-w-[520px] px-4 py-3 rounded-2xl rounded-br-md bg-surface-2 border border-hairline">
              <p className="text-[14px]">{pendingUser}</p>
            </div>
          )}

          {/* live streaming answer */}
          {streaming && (
            <div className="flex gap-3.5">
              <span className="grid place-items-center h-9 w-9 rounded-md bg-ink text-on-accent font-display text-base leading-none shrink-0">न</span>
              <div className="flex-1 min-w-0">
                {streaming.error ? (
                  <p className="text-[14px] text-neg">{streaming.error}</p>
                ) : (
                  <>
                    {/* Widget renders the moment its data arrives (before the
                        narrative), with a soft fade-rise so the chart "draws in." */}
                    {streaming.widget && WIDGET_TYPES.has(streaming.widget.widget_type) && (
                      <div className="animate-widget-in">
                        <ChatWidget widget={streaming.widget} onAction={handleWidgetAction} />
                      </div>
                    )}
                    {streaming.content ? (
                      <Markdown caret className={cn("text-[15.5px] leading-relaxed text-ink-2", streaming.widget && "mt-3")}>
                        {streaming.content}
                      </Markdown>
                    ) : (
                      <div className={cn("flex items-center gap-2 text-ink-3", streaming.widget && "mt-3")}>
                        {streaming.thinking ? (
                          <span className="text-[13px]">Reading your portfolio…</span>
                        ) : (
                          <><Dot delay={0} /><Dot delay={150} /><Dot delay={300} /></>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* composer */}
        <div className="mt-7 sticky bottom-0 bg-bg/95 backdrop-blur">
          <div
            className={cn(
              "flex items-center gap-3 px-4 py-3 rounded-md bg-surface-1 border border-hairline-2",
              "focus-within:border-accent",
            )}
          >
            <Plus className="h-4 w-4 text-ink-3" />
            <input
              type="text"
              placeholder="Ask anything…"
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
              className="flex-1 bg-transparent outline-none text-[14.5px]"
              disabled={isBusy}
            />
            <Button variant="accent" size="sm" disabled={!composer.trim() || isBusy} onClick={handleSend}>
              <Send className="h-3.5 w-3.5" /> Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="h-1.5 w-1.5 rounded-full bg-ink-3"
      style={{ animation: `pulse 1.2s ${delay}ms infinite ease-in-out` }}
    />
  );
}
