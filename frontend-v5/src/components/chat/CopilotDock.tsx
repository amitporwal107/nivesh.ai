/**
 * CopilotDock — the global AI copilot, available on every authenticated screen.
 *
 * A floating launcher button (bottom-right) opens a slide-over panel that reuses
 * the exact same chat backend, session model and structured widgets as the full
 * /chat page. The difference: it travels with the user across dashboards and is
 * *page-aware* — the dashboard label in view (derived from the route) is passed
 * to /api/chat/send as `page`, so "explain this" / "why is this high?" resolve
 * to the screen the user is looking at.
 *
 * It is mounted once in AppLayout and hides itself on the full /chat page (where
 * it would be redundant).
 */
import { useEffect, useRef, useState } from "react";
import { useLocation, Link } from "react-router-dom";
import { Sparkles, Send, X, Plus, Maximize2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ChatWidget } from "@/components/chat/ChatWidget";
import { Markdown, prefetchStreamdown } from "@/components/chat/Markdown";
import { useTypewriterReveal, remainingRevealMs } from "@/components/chat/useTypewriter";
import { useQueryClient } from "@tanstack/react-query";
import { useChatSession, useSuggestedPrompts, useCreateChatSession } from "@/hooks/use-chat";
import { chatService } from "@/services";

// `buffer` is everything received; `content` is the paced, typed-out slice.
type DockStream = { buffer: string; content: string; thinking?: string; widget?: { widget_type: string; data: unknown }; error?: string };

const WIDGET_TYPES = new Set([
  "fund_consolidation", "fund_overlap", "overlap_severity", "risk_overview",
  "cap_education", "concentration", "allocation_review", "instrument_detail",
]);

const FALLBACK_PROMPTS = [
  "Explain this screen",
  "How risky is my portfolio?",
  "Which funds overlap most?",
  "What should I fix first?",
];

/** Map the current route to the human dashboard label shown to the user and
 *  sent to the backend as page context. Returns null on routes with no useful
 *  context (so the copilot stays generic there). */
function pageLabelFor(pathname: string): string | null {
  if (pathname.startsWith("/funds/")) return "Fund details";
  const map: Record<string, string> = {
    "/dashboard": "Overview",
    "/portfolio": "Portfolio builder",
    "/ai-insights": "AI Insights",
    "/risk": "Risk",
    "/performance": "Performance",
    "/composition": "Composition",
    "/recommendations": "Recommendations",
    "/goals": "Goals",
    "/tax": "Tax",
    "/plan": "Plan board",
    "/pro-trader": "Pro Trader",
    "/settings": "Settings",
  };
  return map[pathname] ?? null;
}

export function CopilotDock() {
  const location = useLocation();
  const page = pageLabelFor(location.pathname);

  const [open, setOpen] = useState(false);
  const [composer, setComposer] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);

  const qc = useQueryClient();
  const createSession = useCreateChatSession();
  const prompts = useSuggestedPrompts();
  const session = useChatSession(sessionId ?? "");
  const messages = session.data?.messages ?? [];

  const [streaming, setStreaming] = useState<DockStream | null>(null);
  const firstTokenRef = useRef<number | null>(null);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const isBusy = streaming !== null;

  // Pace the visible text toward the received buffer over a ~10s window.
  useTypewriterReveal(streaming, setStreaming, firstTokenRef);

  // Warm the lazy Streamdown chunk when the dock is opened — keeps it out of the
  // initial bundle on pages where the copilot is never used.
  useEffect(() => { if (open) void prefetchStreamdown(); }, [open]);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the latest message in view as the thread grows / while streaming.
  useEffect(() => {
    if (open && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [open, messages.length, streaming?.content, isBusy]);

  // The dock is redundant on the full chat page — let that page own the screen.
  if (location.pathname === "/chat") return null;

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
    firstTokenRef.current = null;
    setStreaming({ buffer: "", content: "" });
    try {
      await chatService.streamSend(t, sid, (ev) => {
        setStreaming((s) => {
          if (!s) return s;
          switch (ev.type) {
            case "thinking": return { ...s, thinking: ev.status === "start" ? ev.tool : undefined };
            // Tokens accumulate into `buffer`; the typewriter reveals `content`.
            case "token":    return { ...s, buffer: s.buffer + (ev.content ?? ""), thinking: undefined };
            case "widget":
              // Start the reveal window at widget arrival so the staggered
              // build (and the bubble hold) span ~10s even with little/no text.
              if (firstTokenRef.current == null) firstTokenRef.current = performance.now();
              return { ...s, widget: { widget_type: ev.widget_type, data: ev.data } };
            case "error":    return { ...s, error: ev.content };
            default:         return s;
          }
        });
      }, { page: page ?? undefined });
    } catch {
      setStreaming((s) => (s ? { ...s, error: "Connection interrupted — please try again." } : s));
    }
    // Hold the bubble open until the paced reveal finishes its ~10s window.
    await new Promise((r) => setTimeout(r, remainingRevealMs(firstTokenRef.current)));
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

  const handleWidgetAction = (a: { intent?: string; query?: string; label?: string }) => {
    if (a.intent === "review_overlap") void submitMessage("Which of my funds overlap the most?");
    else if (a.intent === "recalc_sip") setComposer("Recalculate my retirement plan with a monthly SIP of ₹");
    else if (a.query) void submitMessage(a.query);
    else if (a.label) void submitMessage(a.label);
  };

  const handleNew = () => {
    setSessionId(undefined);
    setComposer("");
  };

  const promptList = prompts.data && prompts.data.length > 0 ? prompts.data : FALLBACK_PROMPTS;
  const showEmpty = messages.length === 0 && !isBusy && !pendingUser;

  return (
    <>
      {/* Launcher — sits above the mobile bottom nav on small screens. */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          aria-label="Open AI copilot"
          className="fixed z-40 bottom-24 right-5 lg:bottom-6 lg:right-6 flex items-center gap-2 rounded-full bg-ink text-on-accent shadow-lg pl-3.5 pr-4 py-3 hover:opacity-90 transition-opacity"
        >
          <Sparkles className="h-4 w-4" />
          <span className="text-[13px] font-medium">Ask copilot</span>
        </button>
      )}

      {/* Backdrop (mobile) */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/30 lg:bg-transparent lg:pointer-events-none"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Slide-over panel */}
      <div
        className={cn(
          "fixed z-50 flex flex-col bg-bg border-hairline shadow-2xl transition-transform duration-200",
          "inset-x-0 bottom-0 top-16 rounded-t-2xl border-t",
          "lg:inset-y-0 lg:left-auto lg:right-0 lg:top-0 lg:w-[440px] lg:rounded-none lg:border-l lg:border-t-0",
          open ? "translate-y-0 lg:translate-x-0" : "translate-y-full lg:translate-y-0 lg:translate-x-full",
        )}
        role="dialog"
        aria-label="AI copilot"
        aria-hidden={!open}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-hairline">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="grid place-items-center h-8 w-8 rounded-md bg-ink text-on-accent font-display text-[15px] leading-none shrink-0">न</span>
            <div className="min-w-0">
              <div className="text-[14px] font-medium text-ink leading-tight">Copilot</div>
              {page && (
                <div className="text-[11.5px] text-ink-3 leading-tight truncate">Asking about · {page}</div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-0.5 shrink-0">
            <button onClick={handleNew} title="New chat" aria-label="New chat" className="p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors">
              <Plus className="h-4 w-4" />
            </button>
            <Link to="/chat" onClick={() => setOpen(false)} title="Open full chat" aria-label="Open full chat" className="p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors">
              <Maximize2 className="h-4 w-4" />
            </Link>
            <button onClick={() => setOpen(false)} title="Close" aria-label="Close copilot" className="p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-4 py-4 flex flex-col gap-4">
          {showEmpty && (
            <div className="mt-2">
              <p className="text-[13.5px] text-ink-2 leading-relaxed">
                Ask anything about your portfolio{page ? <> — I'll read the <span className="text-ink font-medium">{page}</span> view first</> : ""}.
              </p>
              <div className="flex flex-wrap gap-2 mt-4">
                {prompts.isPending && Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-32 rounded-full" />
                ))}
                {!prompts.isPending && promptList.map((q) => (
                  <button
                    key={q}
                    onClick={() => setComposer(q)}
                    className="px-3 py-1.5 rounded-full bg-surface-2 border border-hairline text-[12px] text-ink-2 hover:bg-surface-3 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => {
            const isUser = m.role === "user";
            const widget = !isUser ? (m as { widget?: { widget_type?: string; data?: unknown } }).widget : undefined;
            const hasWidget = !!widget?.widget_type && WIDGET_TYPES.has(widget.widget_type);
            return (
              <div key={m.id ?? i} className={cn(isUser ? "self-end max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-br-md bg-surface-2 border border-hairline" : "flex gap-2.5")}>
                {!isUser && (
                  <span className="grid place-items-center h-7 w-7 rounded-md bg-ink text-on-accent font-display text-[13px] leading-none shrink-0">न</span>
                )}
                <div className={isUser ? "" : "flex-1 min-w-0"}>
                  {isUser ? (
                    <p className="text-[13.5px]">{m.content}</p>
                  ) : hasWidget ? (
                    // Widget is the answer — its narrative would just repeat it.
                    <ChatWidget widget={widget} onAction={handleWidgetAction} />
                  ) : m.content?.trim() ? (
                    <Markdown className="text-[14px] leading-relaxed text-ink-2">{m.content}</Markdown>
                  ) : null}
                </div>
              </div>
            );
          })}

          {pendingUser && (
            <div className="self-end max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-br-md bg-surface-2 border border-hairline">
              <p className="text-[13.5px]">{pendingUser}</p>
            </div>
          )}

          {streaming && (
            <div className="flex gap-2.5">
              <span className="grid place-items-center h-7 w-7 rounded-md bg-ink text-on-accent font-display text-[13px] leading-none shrink-0">न</span>
              <div className="flex-1 min-w-0">
                {streaming.error ? (
                  <p className="text-[14px] text-neg">{streaming.error}</p>
                ) : streaming.widget && WIDGET_TYPES.has(streaming.widget.widget_type) ? (
                  // Widget is the answer — sections fade-rise (sd-stagger) over
                  // ~9s; narrative suppressed since the widget already says it.
                  <div className="sd-stagger">
                    <ChatWidget widget={streaming.widget} onAction={handleWidgetAction} />
                  </div>
                ) : streaming.content ? (
                  <Markdown caret className="text-[14px] leading-relaxed text-ink-2">
                    {streaming.content}
                  </Markdown>
                ) : (
                  <div className="flex items-center gap-1.5 text-ink-3 pt-2">
                    {streaming.thinking ? <span className="text-[12.5px]">Reading your portfolio…</span>
                      : <><Dot delay={0} /><Dot delay={150} /><Dot delay={300} /></>}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="px-4 py-3 border-t border-hairline bg-bg">
          <div className={cn("flex items-center gap-2.5 px-3.5 py-2.5 rounded-md bg-surface-1 border border-hairline-2", "focus-within:border-accent")}>
            <input
              type="text"
              placeholder={page ? `Ask about ${page}…` : "Ask anything…"}
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
              className="flex-1 bg-transparent outline-none text-[14px]"
              disabled={isBusy}
            />
            <Button variant="accent" size="sm" disabled={!composer.trim() || isBusy} onClick={handleSend}>
              <Send className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>
    </>
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
