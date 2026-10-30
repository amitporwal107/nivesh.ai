/**
 * The Daily Trader Copilot entry point (owner, 30 Oct: "NIVESH COPILOT · What would you like to know today? · Ask in
 * plain English. Get evidence-backed insights and a clear trade plan.", six entry points, a question box and "Explore
 * this question"). The Trader persona's home.
 *
 * Six entry points follow a trading day: what is happening (Market pulse), where the opportunity is (Find
 * opportunities), the trades I have (My positions), F&O (F&O strategies), protecting capital (Manage risk) and learning
 * from the day (Daily review). Picking one puts its lead question in the box, where it can be edited (a stock name
 * completes as in every ask box); its other questions are listed under the button. "Explore this question" asks the
 * Copilot, which answers with the evidence and the data's date.
 */
import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { BarChart3, BriefcaseBusiness, NotepadText, ScanSearch, ShieldCheck, SquareActivity, ArrowRight, type LucideIcon } from "lucide-react";
import { applyCompletion, CompletionList, useStockCompletion, type StockSuggestion } from "../lib/stock-completion";

export interface DailyTile {
  key: "pulse" | "opportunities" | "positions" | "fno" | "risk" | "review";
  label: string;
  icon: LucideIcon;
  /** The lead question first. "this stock" is selected in the box so a typed name replaces it. */
  questions: string[];
}

export const DAILY_TILES: DailyTile[] = [
  { key: "pulse", label: "Market pulse", icon: SquareActivity, questions: [
    "What is the market view today for Nifty and Bank Nifty?",
    "Where is smart money moving?",
    "What is the expected move in Nifty?",
    "What are the key support and resistance levels for Nifty and Bank Nifty?",
    "Which sectors are leading and lagging?",
  ] },
  { key: "opportunities", label: "Find opportunities", icon: ScanSearch, questions: [
    "Find today's top 5 trading opportunities with entry, stop-loss and targets",
    "Which breakouts are confirmed?",
    "Which stocks have unusual volume?",
    "Is this stock a buy now?",
    "What is the entry, target and stop-loss for this stock?",
  ] },
  { key: "positions", label: "My positions", icon: BriefcaseBusiness, questions: [
    "What are my open trades doing?",
    "Is my existing trade still valid?",
    "Should I book profits or hold?",
  ] },
  { key: "fno", label: "F&O strategies", icon: BarChart3, questions: [
    "Which F&O setups are attractive?",
    "What is the expected move in Nifty?",
    "Is there a long buildup or short covering in Bank Nifty?",
  ] },
  { key: "risk", label: "Manage risk", icon: ShieldCheck, questions: [
    "How much should I risk?",
    "What should I avoid today?",
    "How much of my daily loss limit have I used?",
  ] },
  { key: "review", label: "Daily review", icon: NotepadText, questions: [
    "What did I learn from today's trades?",
    "Did I follow my entry, stop-loss and exit rules?",
  ] },
];

const PLACEHOLDER = "this stock";

export function DailyTraderPanel({ onAsk, eyebrow, mobile }: { onAsk: (question: string) => void; eyebrow?: string; mobile: boolean }) {
  const [tile, setTile] = useState<DailyTile>(DAILY_TILES[0]);
  const [draft, setDraft] = useState(DAILY_TILES[0].questions[0]);
  const [caret, setCaret] = useState(draft.length);
  const [focused, setFocused] = useState(false);
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const completion = useStockCompletion(draft.slice(0, caret), focused);
  const shown = completion.data;
  // The selection to apply once the box shows the new text: in the same commit (a layout effect), so a key typed right
  // after a pick lands in the box, over "this stock".
  const [pendingSel, setPendingSel] = useState<{ start: number; end: number } | null>(null);
  useLayoutEffect(() => {
    const el = box.current;
    if (!pendingSel || !el) return;
    el.focus();
    el.setSelectionRange(pendingSel.start, pendingSel.end);
    setCaret(pendingSel.start);
    setPendingSel(null);
  }, [pendingSel]);

  /** Put a question in the box; a "this stock" in it is selected, so typing a name replaces it. */
  const choose = (q: string) => {
    setDraft(q);
    const at = q.indexOf(PLACEHOLDER);
    setPendingSel(at >= 0 ? { start: at, end: at + PLACEHOLDER.length } : { start: q.length, end: q.length });
  };
  const pickTile = (t: DailyTile) => { setTile(t); choose(t.questions[0]); };
  const pickStock = (s: StockSuggestion) => {
    if (!shown) return;
    const next = applyCompletion(draft, caret, shown, s);
    setDraft(next.text);
    setHi(0);
    requestAnimationFrame(() => { box.current?.setSelectionRange(next.caret, next.caret); setCaret(next.caret); });
  };
  const explore = () => { const q = draft.trim(); if (q) onAsk(q); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (shown) {
      if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => (h + 1) % shown.stocks.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => (h - 1 + shown.stocks.length) % shown.stocks.length); return; }
      if (e.key === "Tab") { e.preventDefault(); pickStock(shown.stocks[hi] ?? shown.stocks[0]); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); explore(); }
  };
  const more = tile.questions.filter((q) => q !== draft);

  return (
    <section data-testid="daily-trader" className="cp-card flex flex-col" style={{ gap: 16, padding: mobile ? 18 : 24 }}>
      <div className="flex flex-col" style={{ gap: 8 }}>
        <span className="cp-eyebrow" data-testid="daily-eyebrow">Nivesh Copilot{eyebrow ? ` · ${eyebrow}` : ""}</span>
        <h1 className="m-0" data-testid="home-headline" style={{ fontFamily: "var(--sans)", fontWeight: 600, fontSize: mobile ? 24 : 30, lineHeight: 1.2, letterSpacing: "-0.01em" }}>
          What would you like to know today?
        </h1>
        <p className="m-0" style={{ fontSize: 15, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>Ask in plain English. Get evidence-backed insights and a clear trade plan.</p>
      </div>

      <div role="radiogroup" aria-label="What to ask about" className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
        {DAILY_TILES.map((t) => {
          const on = t.key === tile.key;
          const Icon = t.icon;
          return (
            <button key={t.key} type="button" role="radio" aria-checked={on} data-testid={`daily-tile-${t.key}`} onClick={() => pickTile(t)}
              className="flex min-w-0 flex-col items-start"
              style={{ gap: mobile ? 10 : 16, padding: mobile ? "14px 14px" : "18px 18px", borderRadius: 14, cursor: "pointer", textAlign: "left",
                border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}`, background: on ? "var(--mint-soft)" : "var(--bg-2)", color: "var(--cp-ink)", fontFamily: "var(--sans)" }}>
              <Icon aria-hidden size={22} strokeWidth={1.8} style={{ color: on ? "var(--mint)" : "var(--cp-ink-2)" }} />
              <span style={{ fontSize: mobile ? 14.5 : 17, fontWeight: 500, lineHeight: 1.25 }}>{t.label}</span>
            </button>
          );
        })}
      </div>

      <div style={{ position: "relative" }}>
        {shown && focused && <CompletionList completion={shown} hi={hi} onPick={pickStock} testId="daily-complete" />}
        <textarea ref={box} data-testid="daily-question" aria-label="Your question" rows={mobile ? 3 : 2} value={draft}
          onChange={(e) => { setDraft(e.target.value); setCaret(e.target.selectionStart ?? e.target.value.length); setHi(0); }}
          onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} onKeyDown={onKey}
          style={{ width: "100%", resize: "vertical", minHeight: 72, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)",
            color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 15.5, lineHeight: 1.5 }} />
      </div>

      <button type="button" data-testid="daily-explore" className="cp-btn" data-variant="primary" disabled={!draft.trim()} onClick={explore}
        style={{ width: "100%", padding: "12px 16px", fontSize: 15 }}>
        Explore this question <ArrowRight aria-hidden size={16} />
      </button>

      {more.length > 0 && (
        <div className="flex flex-col" style={{ gap: 2 }} data-testid="daily-more">
          <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>More in {tile.label}</span>
          {more.map((q) => (
            <button key={q} type="button" data-testid="daily-more-q" onClick={() => choose(q)}
              style={{ padding: "8px 0", border: 0, borderBottom: "1px solid var(--cp-line)", background: "none", cursor: "pointer", textAlign: "left", color: "var(--cp-ink-2)", fontFamily: "var(--sans)", fontSize: 14 }}>
              {q}
            </button>
          ))}
        </div>
      )}

      <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        Answers use the latest market data available and show its date. Ideas to review, not recommendations; nothing is sent to a broker.
      </span>
    </section>
  );
}
