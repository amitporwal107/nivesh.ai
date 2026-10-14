/**
 * The Copilot docked beside the trading desk (design: the "Nivesh Copilot ·
 * Conversational intelligence" panel at the right of the desk).
 *
 * It is the same Copilot as the rest of the app — POST /api/chat/stream, asked
 * in the trader persona — with its own thread, so the desk stays on screen
 * while an answer streams. The thread id is kept for the browser tab
 * (sessionStorage), so moving between tabs or screens keeps the conversation;
 * "Open full thread" shows it in the app's normal thread view, with the
 * evidence panel and any result card.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Markdown } from "@/components/chat/Markdown";
import { WIDGET_TYPES } from "@/components/chat/ChatWidget";
import { useCopilotShell } from "../../lib/shell-context";
import { useThreadEngine } from "../../lib/use-thread-engine";
import { useThreadTurns, type Turn } from "../../lib/use-thread-turns";
import { threadView } from "../../lib/views";

const STORE_KEY = "nv.copilot.desk.thread";

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

export interface CopilotDockHandle {
  ask: (question: string) => void;
}

function DockTurn({ turn, busy, onRetry, onOpenThread }: { turn: Turn; busy: boolean; onRetry: (q: string) => void; onOpenThread: () => void }) {
  const working = turn.state === "streaming";
  const card = !!turn.widget?.widget_type && WIDGET_TYPES.has(turn.widget.widget_type);
  return (
    <div data-testid="dock-turn" data-state={turn.state} className="flex flex-col" style={{ gap: 12, flex: "none" }}>
      {turn.question && (
        <div data-testid="dock-question" className="self-end" style={{ maxWidth: "88%", padding: "10px 14px", borderRadius: "14px 14px 4px 14px", background: "var(--bg-3)", border: "1px solid var(--line-2)", fontSize: 13.5, lineHeight: 1.45, overflowWrap: "anywhere" }}>
          {turn.question}
        </div>
      )}
      {turn.state !== "unanswered" && (
        <div className="flex items-start" style={{ gap: 10 }}>
          <span className="nv-mark" aria-hidden style={{ flex: "none", width: 24, height: 24, fontSize: 14, marginTop: 2 }}>न</span>
          <div className="flex min-w-0 flex-1 flex-col" style={{ gap: 8 }}>
            {turn.text && (
              <div data-testid="dock-answer" className="cp-prose min-w-0" style={{ fontSize: 13.5 }}>
                <Markdown caret={working}>{turn.text}</Markdown>
              </div>
            )}
            {working && !turn.text && (
              <span role="status" className="cp-running cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>Reading the desk…</span>
            )}
            {card && (
              <button type="button" onClick={onOpenThread} style={{ alignSelf: "flex-start", padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--mint)", cursor: "pointer" }}>
                This answer has a result card — open the full thread ›
              </button>
            )}
            {(turn.state === "error" || turn.state === "stopped") && (
              <div data-testid="dock-problem" role="alert" className="flex flex-wrap items-center" style={{ gap: "6px 10px", padding: "8px 10px", borderRadius: 10, border: `1px solid ${turn.state === "error" ? "var(--danger-line)" : "var(--amber-line)"}`, fontSize: 12.5, color: "var(--cp-ink-2)" }}>
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

/** The docked panel. `chips` are questions about what the desk is showing now. */
export const CopilotDock = forwardRef<CopilotDockHandle, { chips: string[]; height: string }>(function CopilotDock({ chips, height }, ref) {
  const { go } = useCopilotShell();
  const engine = useThreadEngine();
  const [sid, setSid] = useState<string | undefined>(readStored);
  const [draft, setDraft] = useState("");
  const { turns, session } = useThreadTurns(sid, engine);
  const scrollRef = useRef<HTMLDivElement>(null);

  const ask = (question: string) => {
    const q = question.trim();
    if (!q || engine.busy) return;
    setDraft("");
    void engine.send(q, sid, (id) => {
      setSid(id);
      writeStored(id);
    }, { persona: "trader" });
  };
  useImperativeHandle(ref, () => ({ ask }));

  const reset = () => {
    engine.clearLocal();
    setSid(undefined);
    writeStored(undefined);
  };

  // Follow the newest text while it streams.
  const lastText = turns[turns.length - 1]?.text.length ?? 0;
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns.length, lastText, engine.busy]);

  // A thread created before the stream failed has no saved copy yet; the failed
  // answer still shows from the engine's local copy.
  const loadingHistory = !!sid && session.isPending && turns.length === 0;
  const openThread = () => { if (sid) go(threadView(sid)); };

  return (
    <aside data-testid="desk-dock" aria-label="Nivesh Copilot" className="cp-card flex flex-col" style={{ height, minHeight: 420, overflow: "hidden" }}>
      <div className="flex items-center" style={{ gap: 10, padding: "12px 14px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
        <span className="nv-mark" aria-hidden style={{ width: 26, height: 26, fontSize: 15 }}>न</span>
        <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 18, lineHeight: 1 }}>Nivesh Copilot</span>
          <span className="cp-eyebrow" style={{ fontSize: 9 }}>Asked as a trader</span>
        </div>
        <span style={{ flex: 1 }} />
        {sid && (
          <>
            <button type="button" data-testid="dock-open-thread" onClick={openThread} className="cp-btn" data-variant="ghost" style={{ padding: "5px 9px", fontSize: 12 }}>Full thread ›</button>
            <button type="button" data-testid="dock-new" onClick={reset} disabled={engine.busy} className="cp-btn" data-variant="ghost" style={{ padding: "5px 9px", fontSize: 12 }} aria-label="Start a new conversation">New</button>
          </>
        )}
      </div>

      <div ref={scrollRef} data-testid="dock-thread" className="cp-scroll flex flex-col" style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 14, gap: 18 }}>
        {loadingHistory && <span role="status" className="cp-mono-note cp-running">Loading the conversation…</span>}
        {!sid && turns.length === 0 && (
          <div className="flex flex-col" style={{ gap: 8 }}>
            <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.2 }}>Ask about anything on the desk.</span>
            <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              Answers come from the same data the desk shows, with sources. The Copilot explains evidence and risk; it does not tell you to buy or sell, and it cannot place orders.
            </span>
          </div>
        )}
        {turns.map((t) => (
          <DockTurn key={t.key} turn={t} busy={engine.busy} onRetry={(q) => { engine.clearLocal(); ask(q); }} onOpenThread={openThread} />
        ))}
      </div>

      {chips.length > 0 && (
        <div data-testid="dock-chips" className="flex flex-wrap" style={{ gap: 6, padding: "10px 14px 0", borderTop: "1px solid var(--cp-line)" }}>
          {chips.slice(0, 4).map((c) => (
            <button key={c} type="button" className="cp-chip" disabled={engine.busy} onClick={() => ask(c)} style={{ padding: "6px 11px", fontSize: 12 }}>{c}</button>
          ))}
        </div>
      )}
      <form
        onSubmit={(e) => { e.preventDefault(); ask(draft); }}
        className="flex items-center"
        style={{ gap: 8, margin: 12, padding: "6px 6px 6px 12px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}
      >
        <input
          data-testid="dock-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about a stock, setup or your positions"
          aria-label="Ask the Copilot"
          style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: "none", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13.5 }}
        />
        {engine.busy ? (
          <button type="button" data-testid="dock-stop" onClick={engine.stop} className="cp-btn" style={{ padding: "6px 10px", fontSize: 12 }}>Stop</button>
        ) : (
          <button type="submit" data-testid="dock-send" disabled={!draft.trim()} className="cp-btn" data-variant="primary" style={{ padding: "6px 12px", fontSize: 13 }} aria-label="Send">↗</button>
        )}
      </form>
    </aside>
  );
});
