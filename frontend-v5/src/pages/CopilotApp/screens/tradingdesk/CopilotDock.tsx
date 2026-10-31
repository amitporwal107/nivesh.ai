/**
 * The Copilot docked beside the trading desk (design §9: the "Nivesh Copilot ·
 * 06 · Conversational intelligence" card at the right of the desk), and the
 * same Copilot full height on a phone (design §11 M6: More · AI Copilot).
 *
 * It is the same Copilot as the rest of the app — POST /api/chat/stream, asked
 * in the desk's persona (the TRADER / INVESTOR switch in the desk header) and
 * with `surface: "trading_desk"` — with its own thread, so the desk stays on
 * screen while an answer streams. The surface tells the server to ask the model
 * for the desk PRD's answer structure (§9.4: direct answer, evidence, as-of
 * times, bull and bear factors, uncertainties, invalidation, sources, where to
 * look), where it applies (backend persona_framing.py). That is an instruction
 * to the model: answers are the real streamed Markdown, styled like the
 * design's answer (serif headings, mint emphasis, "›" bullets); nothing is
 * restructured or made up here. The thread id is kept for the browser tab (sessionStorage), so
 * moving between tabs or screens keeps the conversation; "Open the full
 * thread" shows it in the app's normal thread view, with the evidence panel
 * and any result card.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type ReactNode } from "react";
import { Markdown } from "@/components/chat/Markdown";
import { WIDGET_TYPES } from "@/components/chat/ChatWidget";
import { TradePlanChatCard, type TradeIdeaData } from "@/components/chat/TradePlanChatCard";
import { VisualAnswer } from "@/components/chat/visual/VisualAnswer";
import { DAILY_TILES } from "../../components/DailyTraderPanel";
import { CompletionList, applyCompletion, useStockCompletion, type StockSuggestion } from "../../lib/stock-completion";
import { useCopilotShell } from "../../lib/shell-context";
import { useThreadEngine } from "../../lib/use-thread-engine";
import { useThreadTurns, type Turn } from "../../lib/use-thread-turns";
import { threadView } from "../../lib/views";
import { useDesk } from "./context";

const STORE_KEY = "nv.copilot.desk.thread";

/** The Copilot surface the server allowlists for the desk's answer structure (routes/chat.py _desk_persona_for). */
const DESK_SURFACE = "trading_desk";

function readStored(): string | undefined {
  try {
    return window.sessionStorage.getItem(STORE_KEY) || undefined;
  } catch {
    return undefined;
  }
}

function writeStored(id: string | undefined) {
  try {
    if (id) window.sessionStorage.setItem(STORE_KEY, id);
    else window.sessionStorage.removeItem(STORE_KEY);
  } catch {
    // Storage blocked (private window): the thread just lasts for this view.
  }
}

/** The design's answer type, applied to the streamed Markdown. Scoped to the dock. */
const DOCK_STYLE = `
.cp-dock-prose { font-size: 13.5px; line-height: 1.6; color: var(--cp-ink-2); }
.cp-dock-prose :is(h1, h2, h3) { font-family: var(--display); font-weight: 400; font-size: 21px; line-height: 1.2; letter-spacing: -0.02em; color: var(--cp-ink); }
.cp-dock-prose h4 { font-family: var(--mono); font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--cp-ink-3); font-weight: 400; }
.cp-dock-prose em { color: var(--mint); }
.cp-dock-prose strong { color: var(--cp-ink); font-weight: 500; }
.cp-dock-prose ul { list-style: none; margin-left: 0; padding-left: 0; }
.cp-dock-prose ul > li { position: relative; padding-left: 16px; }
.cp-dock-prose ul > li::before { content: "›"; position: absolute; left: 2px; top: 0; color: var(--mint); }
.cp-dock-prose a { font-family: var(--mono); font-size: 11px; color: var(--cp-ink-2); text-decoration: none; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--line-2); white-space: nowrap; }
.cp-dock-prose a:hover { border-color: var(--mint-line); color: var(--cp-ink); }
.cp-dock-prose code { font-family: var(--mono); font-size: 12px; }
.cp-dock-page .cp-dock-prose :is(h1, h2, h3) { font-size: 19px; }
.cp-dock-page .cp-dock-prose { font-size: 12.5px; }
@keyframes cp-dock-dot { 0%, 80%, 100% { opacity: 0.25; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-2px); } }
.cp-dock-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--mint); animation: cp-dock-dot 1.2s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) { .cp-dock-dot { animation: none; opacity: 0.7; } }
`;

export interface CopilotDockHandle {
  ask: (question: string) => void;
  /** Put the cursor in the ask box (More · AI Copilot with the dock showing). */
  focus: () => void;
}

function Mark({ size }: { size: number }) {
  return <span className="nv-mark" aria-hidden style={{ flex: "none", width: size, height: size, fontSize: Math.round(size * 0.58) }}>न</span>;
}

/** Design: three pulsing mint dots and "READING THE DESK…" beside the mark. */
function Typing() {
  return (
    <span role="status" data-testid="dock-typing" className="flex items-center" style={{ gap: 10, minHeight: 24 }}>
      <span className="flex items-center" style={{ gap: 4 }} aria-hidden>
        {[0, 1, 2].map((i) => <span key={i} className="cp-dock-dot" style={{ animationDelay: `${i * 0.16}s` }} />)}
      </span>
      <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)", letterSpacing: "0.12em" }}>Reading the desk…</span>
    </span>
  );
}

function DockTurn({ turn, busy, page, onRetry, onAsk, onOpenThread }: { turn: Turn; busy: boolean; page: boolean; onRetry: (q: string) => void; onAsk: (q: string) => void; onOpenThread: () => void }) {
  const working = turn.state === "streaming";
  const card = !!turn.widget?.widget_type && WIDGET_TYPES.has(turn.widget.widget_type);
  // A stock's trade idea is the desk's own plan card: shown here, beside the desk, not only in the full thread.
  const tradePlan = turn.widget?.widget_type === "trade_plan" && turn.widget.data && typeof turn.widget.data === "object"
    ? (turn.widget.data as TradeIdeaData) : null;
  // The visual answer (charts, tables, the plan) is shown here too, compact, beside the desk.
  const visual = turn.widget?.widget_type === "visual_answer" && turn.widget.data != null;
  return (
    <div data-testid="dock-turn" data-state={turn.state} className="flex flex-col" style={{ gap: 14, flex: "none" }}>
      {turn.question && (
        <div data-testid="dock-question" className="self-end" style={{ maxWidth: "86%", padding: "10px 14px", borderRadius: "14px 14px 4px 14px", background: "var(--bg-3)", border: "1px solid var(--line-2)", fontSize: page ? 13 : 13.5, lineHeight: 1.45, overflowWrap: "anywhere" }}>
          {turn.question}
        </div>
      )}
      {turn.state !== "unanswered" && (
        <div className="flex items-start" style={{ gap: 10 }}>
          <span style={{ marginTop: 2 }}><Mark size={24} /></span>
          <div className="flex min-w-0 flex-1 flex-col" style={{ gap: 10 }}>
            {turn.text && (
              <div data-testid="dock-answer" className="cp-prose cp-dock-prose min-w-0">
                <Markdown caret={working}>{turn.text}</Markdown>
              </div>
            )}
            {working && !turn.text && <Typing />}
            {tradePlan !== null && <TradePlanChatCard data={tradePlan} onAction={(a) => { if (a.query && !busy) onAsk(a.query); }} />}
            {visual && <VisualAnswer data={turn.widget?.data} compact onAction={(a) => { if (a.query && !busy) onAsk(a.query); }} />}
            {card && !tradePlan && !visual && (
              <button type="button" onClick={onOpenThread} style={{ alignSelf: "flex-start", padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--mint)", cursor: "pointer" }}>
                This answer has a result card — open the full thread ›
              </button>
            )}
            {(turn.state === "error" || turn.state === "stopped") && (
              <div data-testid="dock-problem" role="alert" className="flex flex-wrap items-center" style={{ gap: "6px 10px", padding: "8px 10px", borderRadius: 10, border: `1px solid ${turn.state === "error" ? "var(--danger-line)" : "var(--amber-line)"}`, background: turn.state === "error" ? "var(--cp-danger-soft)" : "transparent", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
                <span style={{ flex: "1 1 160px" }}>{turn.state === "error" ? (turn.errorText || "The Copilot could not finish this answer.") : "You stopped this answer."}</span>
                {!busy && <button type="button" onClick={() => onRetry(turn.question)} style={{ padding: 0, border: 0, background: "none", fontSize: 12.5, color: "var(--cp-ink)", cursor: "pointer" }}>Retry ›</button>}
              </div>
            )}
            {turn.state === "saved" && <span className="cp-mono-note">Educational research, not investment advice</span>}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * The Copilot panel. `chips` are questions about what the desk is showing now.
 * variant "dock" = the card beside the desk; "page" = full height in the page on a phone.
 */
export const CopilotDock = forwardRef<CopilotDockHandle, {
  chips: string[]; height: string; variant?: "dock" | "page";
  /** The docked Copilot as a window (copilot-window.tsx): locked in the right column, or floating over the desk. */
  windowMode?: "locked" | "floating";
  onToggleWindow?: () => void;
  /** Floating: a pointer-down on the header starts moving the window. */
  onHeaderPointerDown?: (e: React.PointerEvent) => void;
}>(function CopilotDock({ chips, height, variant = "dock", windowMode, onToggleWindow, onHeaderPointerDown }, ref) {
  const { go } = useCopilotShell();
  const { persona } = useDesk();
  const engine = useThreadEngine();
  const [sid, setSid] = useState<string | undefined>(readStored);
  const [draft, setDraft] = useState("");
  const { turns, session } = useThreadTurns(sid, engine);
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Stock autocomplete at the cursor (lib/stock-completion.tsx): the same completions as the app's ask box.
  const [caret, setCaret] = useState(0);
  const [focused, setFocused] = useState(false);
  const [hi, setHi] = useState(-1);
  const completion = useStockCompletion(draft.slice(0, caret), focused && !engine.busy);
  const completions = completion.data;
  const complete = (st: StockSuggestion) => {
    if (!completions) return;
    const next = applyCompletion(draft, inputRef.current?.selectionStart ?? caret, completions, st);
    setDraft(next.text);
    setCaret(next.caret);
    setHi(-1);
    requestAnimationFrame(() => { const el = inputRef.current; if (el) { el.focus(); el.setSelectionRange(next.caret, next.caret); } });
  };
  const onInputKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const n = completions?.stocks.length ?? 0;
    if (e.key === "Escape") { setHi(-1); setFocused(false); return; }
    if (!n) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => (h + 1) % n); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => (h <= 0 ? n - 1 : h - 1)); return; }
    if (e.key === "Tab") { e.preventDefault(); complete(completions!.stocks[hi >= 0 ? hi : 0]); return; }
    // Enter on a highlighted stock completes it; Enter with nothing highlighted asks, as before.
    if (e.key === "Enter" && hi >= 0 && !e.nativeEvent.isComposing) { e.preventDefault(); complete(completions!.stocks[hi]); }
  };
  const page = variant === "page";

  const ask = (question: string) => {
    const q = question.trim();
    if (!q || engine.busy) return;
    setDraft("");
    void engine.send(q, sid, (id) => {
      setSid(id);
      writeStored(id);
    }, { persona, surface: DESK_SURFACE });
  };
  useImperativeHandle(ref, () => ({ ask, focus: () => inputRef.current?.focus() }));

  const reset = () => {
    engine.clearLocal();
    setSid(undefined);
    writeStored(undefined);
  };

  // Follow the newest text while it streams: the dock scrolls itself; on a phone the page scrolls.
  const lastText = turns[turns.length - 1]?.text.length ?? 0;
  useEffect(() => {
    if (page) {
      if (turns.length) endRef.current?.scrollIntoView({ block: "nearest" });
      return;
    }
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [page, turns.length, lastText, engine.busy]);

  // A thread created before the stream failed has no saved copy yet; the failed
  // answer still shows from the engine's local copy.
  const loadingHistory = !!sid && session.isPending && turns.length === 0;
  const openThread = () => { if (sid) go(threadView(sid)); };

  const thread: ReactNode = (
    <>
      {sid && (
        <div className="flex items-center justify-end" style={{ marginBottom: -8 }}>
          <button type="button" data-testid="dock-open-thread" onClick={openThread} className="cp-mono-note" style={{ padding: 0, border: 0, background: "none", cursor: "pointer", color: "var(--cp-ink-3)" }}>Open the full thread ›</button>
        </div>
      )}
      {loadingHistory && <span role="status" className="cp-mono-note cp-running">Loading the conversation…</span>}
      {!sid && turns.length === 0 && (
        <div data-testid="dock-empty" className="flex items-start" style={{ gap: 10 }}>
          <span style={{ marginTop: 2 }}><Mark size={24} /></span>
          <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
            <span style={{ fontFamily: "var(--display)", fontSize: page ? 19 : 21, lineHeight: 1.2, letterSpacing: "-0.02em" }}>Ask about anything on the desk.</span>
            <span style={{ fontSize: page ? 12.5 : 13.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              Answers come from the same data the desk shows, with sources. The Copilot explains evidence and risk; it does not tell you to buy or sell, and it cannot place orders.
            </span>
            {/* The Daily Trader Copilot's six entry points (owner, 30 Oct): a pick puts its lead question in the box. */}
            <div data-testid="dock-daily" role="group" aria-label="What to ask about" className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 6, marginTop: 4 }}>
              {DAILY_TILES.map((t) => {
                const Icon = t.icon;
                return (
                  <button key={t.key} type="button" data-testid={`dock-daily-${t.key}`} title={t.questions[0]}
                    onClick={() => { const q = t.questions[0]; setDraft(q); setCaret(q.length); setHi(-1); inputRef.current?.focus(); }}
                    className="flex min-w-0 items-center"
                    style={{ gap: 8, padding: "9px 10px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-2)", color: "var(--cp-ink)", cursor: "pointer", fontFamily: "var(--sans)", fontSize: 12.5, textAlign: "left" }}>
                    <Icon aria-hidden size={15} strokeWidth={1.8} style={{ flex: "none", color: "var(--cp-ink-2)" }} />
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
      {turns.map((t) => (
        <DockTurn key={t.key} turn={t} busy={engine.busy} page={page} onRetry={(q) => { engine.clearLocal(); ask(q); }} onAsk={ask} onOpenThread={openThread} />
      ))}
      <div ref={endRef} aria-hidden style={{ scrollMarginBottom: page ? 140 : 0 }} />
    </>
  );

  const sendButton = (size: number, radius: number) => (engine.busy ? (
    <button type="button" data-testid="dock-stop" onClick={engine.stop} aria-label="Stop the answer" className="cp-btn grid place-items-center" style={{ flex: "none", width: size, height: size, padding: 0, borderRadius: radius, fontSize: 12 }}>■</button>
  ) : (
    <button type="submit" data-testid="dock-send" disabled={!draft.trim()} aria-label="Send" className="cp-btn grid place-items-center" data-variant="primary" style={{ flex: "none", width: size, height: size, padding: 0, borderRadius: radius, fontSize: 15 }}>↗</button>
  ));

  const input = (placeholder: string) => (
    <div style={{ position: "relative", flex: 1, minWidth: 0, display: "flex", alignSelf: "stretch", alignItems: "center" }}>
      {focused && completions && <CompletionList completion={completions} hi={hi} onPick={complete} testId="dock-complete" />}
      <input
        ref={inputRef}
        data-testid="dock-input"
        value={draft}
        onChange={(e) => { setDraft(e.target.value); setCaret(e.target.selectionStart ?? e.target.value.length); setHi(-1); setFocused(true); }}
        onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? draft.length)}
        onKeyDown={onInputKey}
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); setHi(-1); }}
        placeholder={placeholder}
        aria-label="Ask the Copilot"
        autoComplete="off"
        style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: "none", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13.5 }}
      />
    </div>
  );

  if (page) {
    return (
      <section data-testid="desk-dock" data-variant="page" aria-label="Nivesh Copilot" className="cp-dock-page flex flex-col" style={{ minHeight: height, gap: 18 }}>
        <style>{DOCK_STYLE}</style>
        <div data-testid="dock-thread" className="flex flex-col" style={{ flex: 1, gap: 20 }}>{thread}</div>
        {chips.length > 0 && (
          <div data-testid="dock-chips" className="flex flex-col" style={{ gap: 8 }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Suggested questions</span>
            {chips.slice(0, 4).map((c) => (
              <button key={c} type="button" className="cp-chip" disabled={engine.busy} onClick={() => ask(c)} style={{ padding: "9px 13px", fontSize: 12.5, borderRadius: 12, width: "100%" }}>{c}</button>
            ))}
          </div>
        )}
        {/* Above the phone's bottom navigation bar (TradingDesk sets --desk-bottom-bar); 0 elsewhere. */}
        <div style={{ position: "sticky", bottom: "var(--desk-bottom-bar, 0px)", paddingTop: 8, paddingBottom: 10, background: "var(--bg-0)", display: "flex", flexDirection: "column", gap: 8 }}>
          <form onSubmit={(e) => { e.preventDefault(); ask(draft); }} className="flex items-center" style={{ gap: 8 }}>
            {sid && (
              <button type="button" data-testid="dock-new" onClick={reset} disabled={engine.busy} aria-label="Start a new conversation" className="grid place-items-center" style={{ flex: "none", width: 36, height: 36, borderRadius: 999, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", fontSize: 16, cursor: "pointer" }}>＋</button>
            )}
            <div className="flex items-center" style={{ flex: 1, minWidth: 0, height: 44, padding: "0 4px 0 16px", gap: 8, borderRadius: 999, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
              {input("Ask Nivesh AI anything…")}
              {sendButton(36, 999)}
            </div>
          </form>
          <span data-testid="dock-note" style={{ fontSize: 10, lineHeight: 1.4, color: "var(--cp-ink-3)", textAlign: "center" }}>For education and research only. Not a buy or sell recommendation.</span>
        </div>
      </section>
    );
  }

  return (
    <aside data-testid="desk-dock" data-variant="dock" data-window={windowMode ?? "locked"} aria-label="Nivesh Copilot" className="cp-card flex flex-col" style={{ height, minHeight: 420, overflow: "hidden", boxShadow: "var(--shadow-card)" }}>
      <style>{DOCK_STYLE}</style>
      <div data-testid="dock-header" className="flex items-center" onPointerDown={windowMode === "floating" ? onHeaderPointerDown : undefined}
        title={windowMode === "floating" ? "Drag to move the Copilot" : undefined}
        style={{ gap: 10, padding: "14px 18px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)", cursor: windowMode === "floating" ? "move" : undefined, touchAction: windowMode === "floating" ? "none" : undefined, userSelect: windowMode === "floating" ? "none" : undefined }}>
        <Mark size={28} />
        <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 19, lineHeight: 1 }}>Nivesh Copilot</span>
          <span className="cp-eyebrow" style={{ fontSize: 9.5, whiteSpace: "nowrap" }}>Conversational intelligence</span>
        </div>
        <span style={{ flex: 1 }} />
        <span className="cp-pill" data-tone="mint" title="Answers read the Nivesh data platform (NIDP), the same data the desk shows" style={{ background: "var(--mint-soft)" }}>
          <span className="nv-dot" style={{ background: "var(--mint)" }} />NIDP
        </span>
        {onToggleWindow && (
          <button type="button" data-testid="dock-window-toggle" onClick={onToggleWindow} className="cp-pill"
            aria-label={windowMode === "floating" ? "Lock the Copilot to the right of the desk" : "Float the Copilot as a window you can move and resize"}
            title={windowMode === "floating" ? "Lock to the right of the desk" : "Float: move and resize it over the desk"}
            style={{ flex: "none", cursor: "pointer", background: "transparent" }}>
            {windowMode === "floating" ? "Lock" : "Float"}
          </button>
        )}
      </div>

      <div ref={scrollRef} data-testid="dock-thread" className="cp-scroll flex flex-col" style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 18, gap: 20 }}>
        {thread}
      </div>

      {chips.length > 0 && (
        <div data-testid="dock-chips" className="flex flex-wrap" style={{ gap: 6, padding: "12px 18px 0", borderTop: "1px solid var(--cp-line)" }}>
          {chips.slice(0, 4).map((c) => (
            <button key={c} type="button" className="cp-chip" disabled={engine.busy} onClick={() => ask(c)} style={{ padding: "6px 11px", fontSize: 12 }}>{c}</button>
          ))}
        </div>
      )}
      <form onSubmit={(e) => { e.preventDefault(); ask(draft); }} style={{ padding: "12px 18px 18px" }}>
        <div className="flex items-center" style={{ gap: 8, padding: "6px 6px 6px 8px", borderRadius: 14, border: "1px solid var(--line-2)", background: "var(--bg-glass)", WebkitBackdropFilter: "blur(14px)", backdropFilter: "blur(14px)" }}>
          <button
            type="button"
            data-testid="dock-new"
            onClick={reset}
            disabled={!sid || engine.busy}
            aria-label="Start a new conversation"
            title="Start a new conversation"
            className="grid place-items-center"
            style={{ flex: "none", width: 28, height: 28, borderRadius: 8, border: 0, background: "transparent", color: "var(--cp-ink-3)", fontSize: 16, cursor: sid && !engine.busy ? "pointer" : "default" }}
          >
            ＋
          </button>
          {input("Ask about a stock, sector or your portfolio")}
          {sendButton(34, 10)}
        </div>
      </form>
    </aside>
  );
});
