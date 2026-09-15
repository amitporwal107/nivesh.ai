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
import { Sparkles, Send, Square, X, Plus, Maximize2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ChatWidget, WIDGET_TYPES } from "@/components/chat/ChatWidget";
import { AgentRibbon, FollowUps, ThinkingSteps, stepUpdate, type ThinkingStep } from "@/components/chat/StreamStatus";
import { Markdown, prefetchStreamdown } from "@/components/chat/Markdown";
import { useTypewriterReveal, remainingRevealMs, holdFor } from "@/components/chat/useTypewriter";
import { useQueryClient } from "@tanstack/react-query";
import { useChatSession, useSuggestedPrompts, useCreateChatSession } from "@/hooks/use-chat";
import { chatService } from "@/services";

// `buffer` is everything received; `content` is the paced, typed-out slice.
// `steps` / `agent` / `followUps` mirror the stream's thinking / route / done
// frames. Widget types come from the ONE list ChatWidget exports (the dock used
// to keep its own shorter copy and rendered a blank turn for the rest).
type DockStream = {
  buffer: string;
  content: string;
  thinking?: string;
  steps: ThinkingStep[];
  agent?: string;
  confidence?: number;
  widget?: { widget_type: string; data: unknown };
  error?: string;
  skip?: boolean;
};
type AnswerMeta = { sessionId: string; agent?: string; confidence?: number; followUps: string[] };
type LocalAnswer = { sessionId: string; question: string; content: string; widget?: { widget_type: string; data: unknown }; note: "stopped" | "error" };

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
    "/portfolio": "Portfolio Page",
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
  const streamRef = useRef<DockStream | null>(null);
  useEffect(() => { streamRef.current = streaming; }, [streaming]);
  const abortRef = useRef<AbortController | null>(null);
  const [answerMeta, setAnswerMeta] = useState<AnswerMeta | null>(null);
  const [localAnswer, setLocalAnswer] = useState<LocalAnswer | null>(null);

  // Pace the visible text to token arrival (never slower than a smooth type-out).
  useTypewriterReveal(streaming, setStreaming, firstTokenRef);

  // Esc while an answer streams: show it all now.
  useEffect(() => {
    if (!streaming) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setStreaming((st) => (st && !st.skip ? { ...st, skip: true } : st)); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [streaming]);

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
    setAnswerMeta(null);
    setLocalAnswer(null);
    setPendingUser(t);
    firstTokenRef.current = null;
    const ac = new AbortController();
    abortRef.current = ac;
    setStreaming({ buffer: "", content: "", steps: [] });
    // Facts about the answer captured here, outside React state: the state
    // mirror (streamRef) can lag a commit when the stream completes in one
    // tick, and these must not depend on render timing.
    let followUps: string[] = [];
    let answerText = "";
    let agent: string | undefined;
    let confidence: number | undefined;
    let widget: { widget_type: string; data: unknown } | undefined;
    let errorText: string | undefined;
    try {
      await chatService.streamSend(t, sid, (ev) => {
        if (ev.type === "done" && Array.isArray(ev.follow_ups)) followUps = ev.follow_ups.filter((q) => typeof q === "string");
        if (ev.type === "token") answerText += ev.content ?? "";
        if (ev.type === "route") { agent = ev.agent ?? agent; if (typeof ev.confidence === "number") confidence = ev.confidence; }
        if (ev.type === "widget") widget = { widget_type: ev.widget_type, data: ev.data };
        if (ev.type === "error") errorText = ev.content;
        setStreaming((s) => {
          if (!s) return s;
          switch (ev.type) {
            case "route":    return { ...s, agent: ev.agent ?? s.agent, confidence: typeof ev.confidence === "number" ? ev.confidence : s.confidence };
            case "thinking": return { ...s, thinking: ev.status === "start" ? ev.tool : undefined, steps: stepUpdate(s.steps, ev.tool, ev.status) };
            // Tokens accumulate into `buffer`; the typewriter reveals `content`.
            case "token":    return { ...s, buffer: s.buffer + (ev.content ?? ""), thinking: undefined };
            case "widget":
              if (firstTokenRef.current == null) firstTokenRef.current = performance.now();
              return { ...s, widget: { widget_type: ev.widget_type, data: ev.data } };
            case "error":    return { ...s, error: ev.content };
            default:         return s;
          }
        });
      }, { page: page ?? undefined, signal: ac.signal });
    } catch {
      if (!ac.signal.aborted) {
        setStreaming((s) => (s ? { ...s, error: "Connection interrupted — please try again." } : s));
      }
    }
    abortRef.current = null;
    if (ac.signal.aborted) {
      // Stopped by the user: keep what arrived (the server won't have persisted
      // a partial answer), then refetch the thread.
      if (answerText || widget) setLocalAnswer({ sessionId: sid, question: t, content: answerText, widget, note: "stopped" });
    } else if (errorText || streamRef.current?.error) {
      const err = errorText ?? streamRef.current?.error ?? "";
      setLocalAnswer({ sessionId: sid, question: t, content: answerText || err, widget, note: "error" });
    } else {
      // Finish typing what is still hidden (capped) and let a widget build in —
      // unless the user skipped. Only the VISIBLE length comes from the mirror.
      const shown = streamRef.current?.content.length ?? 0;
      await holdFor(remainingRevealMs(Math.max(0, answerText.length - shown), !!widget), () => !!streamRef.current?.skip);
      setAnswerMeta({ sessionId: sid, agent, confidence, followUps });
    }
    setStreaming(null);
    setPendingUser(null);
    qc.invalidateQueries({ queryKey: ["chat", "sessions", sid] });
    qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
  };

  const handleStop = () => { abortRef.current?.abort(); };
  const handleSkip = () => { setStreaming((s) => (s && !s.skip ? { ...s, skip: true } : s)); };

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
    setAnswerMeta(null);
    setLocalAnswer(null);
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
                    <ChatWidget widget={widget} onAction={handleWidgetAction} />
                  ) : m.content?.trim() ? (
                    <Markdown className="text-[14px] leading-relaxed text-ink-2">{m.content}</Markdown>
                  ) : null}
                </div>
              </div>
            );
          })}

          {/* Optimistic user bubble. Suppress once the persisted copy lands in
              the refetched session (new sessions fetch mid-stream) — else the
              message renders twice for the duration of the answer. */}
          {pendingUser &&
            !(messages.length > 0 &&
              messages[messages.length - 1].role === "user" &&
              messages[messages.length - 1].content === pendingUser) && (
            <div className="self-end max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-br-md bg-surface-2 border border-hairline">
              <p className="text-[13.5px]">{pendingUser}</p>
            </div>
          )}

          {answerMeta && answerMeta.sessionId === sessionId && !streaming && messages.length > 0 && messages[messages.length - 1].role !== "user" && (
            <div className="pl-[38px] -mt-1 flex flex-col gap-2.5" data-testid="dock-answer-meta">
              {answerMeta.agent && <div><AgentRibbon agent={answerMeta.agent} confidence={answerMeta.confidence} /></div>}
              <FollowUps items={answerMeta.followUps} onPick={(q) => void submitMessage(q)} disabled={isBusy} />
            </div>
          )}

          {localAnswer && localAnswer.sessionId === sessionId && !streaming && (
            <div className="flex gap-2.5" data-testid="dock-local-answer">
              <span className="grid place-items-center h-7 w-7 rounded-md bg-ink text-on-accent font-display text-[13px] leading-none shrink-0">न</span>
              <div className="flex-1 min-w-0">
                {localAnswer.widget && WIDGET_TYPES.has(localAnswer.widget.widget_type) ? (
                  <ChatWidget widget={localAnswer.widget} onAction={handleWidgetAction} />
                ) : localAnswer.content ? (
                  <Markdown className="text-[14px] leading-relaxed text-ink-2">{localAnswer.content}</Markdown>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className={cn("font-mono text-[10px] uppercase tracking-[.14em]", localAnswer.note === "error" ? "text-neg" : "text-ink-3")}>
                    {localAnswer.note === "error" ? "Couldn't finish" : "Stopped"}
                  </span>
                  <button type="button" onClick={() => void submitMessage(localAnswer.question)} className="rounded-full border border-hairline bg-surface-1 px-2.5 py-1 text-[11.5px] text-ink-2 hover:bg-surface-2 transition-colors">
                    Try again
                  </button>
                </div>
              </div>
            </div>
          )}

          {streaming && (
            <div className="flex gap-2.5" data-testid="dock-streaming-answer" onClick={handleSkip}>
              <span className="grid place-items-center h-7 w-7 rounded-md bg-ink text-on-accent font-display text-[13px] leading-none shrink-0">न</span>
              <div className="flex-1 min-w-0 flex flex-col gap-2">
                {streaming.agent && <div><AgentRibbon agent={streaming.agent} confidence={streaming.confidence} /></div>}
                {streaming.steps.length > 0 && !streaming.widget && !streaming.content && (
                  <div aria-live="polite"><ThinkingSteps steps={streaming.steps} /></div>
                )}
                {streaming.error ? (
                  <p className="text-[14px] text-neg">{streaming.error}</p>
                ) : streaming.widget && WIDGET_TYPES.has(streaming.widget.widget_type) ? (
                  // Builds in quick steps; the hero line (section 1) types the summary.
                  <div className={streaming.skip ? undefined : "sd-stagger"}>
                    <ChatWidget widget={streaming.widget} onAction={handleWidgetAction} />
                  </div>
                ) : streaming.content ? (
                  <Markdown caret={streaming.content.length < streaming.buffer.length} className="text-[14px] leading-relaxed text-ink-2">
                    {streaming.content}
                  </Markdown>
                ) : streaming.steps.length === 0 ? (
                  <div className="flex items-center gap-1.5 text-ink-3 pt-2" aria-live="polite">
                    {streaming.thinking ? <span className="text-[12.5px]">Reading your portfolio…</span>
                      : <><Dot delay={0} /><Dot delay={150} /><Dot delay={300} /></>}
                  </div>
                ) : null}
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
              aria-label={page ? `Ask the copilot about ${page}` : "Ask the copilot"}
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
              className="flex-1 bg-transparent outline-none text-[14px]"
              disabled={isBusy}
            />
            {isBusy ? (
              <Button variant="outline" size="sm" onClick={handleStop} data-testid="dock-stop" aria-label="Stop generating">
                <Square className="h-3 w-3 fill-current" />
              </Button>
            ) : (
              <Button variant="accent" size="sm" disabled={!composer.trim()} onClick={handleSend} data-testid="dock-send" aria-label="Send">
                <Send className="h-3.5 w-3.5" />
              </Button>
            )}
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
