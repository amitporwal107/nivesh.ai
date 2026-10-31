/**
 * Ask box — the input, the suggestion list above it, the attach shortcut, the
 * market-data freshness note and send / stop. Design: Nivesh Copilot.dc.html,
 * the composer block and its `ssOpen` popover.
 *
 * Suggestions are real:
 *   empty box   GET /api/copilot/suggested-prompts   (ranked for this user)
 *   typing      GET /api/chat/suggest-queries        (question bank)
 *               GET /api/chat/instrument-search      (stocks and funds)
 *   the cursor  GET /api/chat/instrument-search?tail=1 (the stock being typed at the cursor: ticker, full or partial
 *               name, a short form, an F&O index — lib/stock-completion.tsx). Its rows come first; Tab, Enter on a
 *               highlighted row or a click replaces the fragment with the ticker and keeps the sentence (nothing is sent).
 */
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { useDebounce } from "@/hooks/use-debounce";
import { useInstrumentSearch } from "@/hooks/use-instrument-search";
import { useMarketsHome } from "@/hooks/use-markets";
import { useQuerySuggestions } from "@/hooks/use-query-suggestions";
import { fmtNum, fmtPct, humaniseTag, type Tone } from "../components/ui";
import { useCopilotPrompts } from "../lib/use-copilot-prompts";
import { applyCompletion, stockWhy, useStockCompletion, type StockSuggestion } from "../lib/stock-completion";
import { toolsNav, type Mode } from "../lib/views";

export interface ComposerHandle {
  focus: () => void;
}

interface Item {
  key: string;
  text: string;
  why?: string;
  tag: string;
  tone: Tone;
  /** What gets sent (or filled in, for a template with a placeholder). */
  query: string;
  template?: boolean;
  /** A stock completion: picking it replaces the fragment at the cursor with this ticker. */
  stock?: StockSuggestion;
}

function Freshness() {
  const m = useMarketsHome();
  if (m.isPending) return null;
  let text: string;
  let color: string;
  if (m.isError || !m.data) {
    text = "Market data unavailable";
    color = "var(--cp-danger)";
  } else {
    const d = m.data;
    const state = d.is_live ? "NSE live" : d.market_state === "open" ? "NSE delayed" : "NSE closed";
    const t = d.as_of ? new Date(d.as_of) : null;
    const when = t && Number.isFinite(t.getTime())
      ? t.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })
      : d.as_of ?? "";
    text = when ? `${state} · ${when}` : state;
    color = d.is_live ? "var(--mint)" : "var(--amber)";
  }
  return (
    <span data-testid="composer-freshness" className="flex items-center" style={{ gap: 6, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", color: "var(--cp-ink-3)", whiteSpace: "nowrap", textTransform: "uppercase" }}>
      <span className="nv-dot" style={{ background: color }} />{text}
    </span>
  );
}

export const Composer = forwardRef<ComposerHandle, {
  busy: boolean;
  mode: Mode;
  mobile: boolean;
  /** Suggestions open on focus (home and thread only). */
  suggest: boolean;
  onSend: (q: string) => void;
  onStop: () => void;
  onAttach: () => void;
  onGo: (view: string) => void;
}>(function Composer({ busy, mode, mobile, suggest, onSend, onStop, onAttach, onGo }, ref) {
  const [draft, setDraft] = useState("");
  // Whether the suggestion list may show: set by focus, click and typing;
  // cleared by blur, Escape and sending.
  const [focused, setFocused] = useState(false);
  const [hi, setHi] = useState(-1);
  /** Where the cursor is: the stock completion looks at the text before it. */
  const [caret, setCaret] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => inputRef.current?.focus() }), []);

  const q = draft.trim();
  const term = useDebounce(q.length >= 2 ? q : "", 220);
  const prompts = useCopilotPrompts(mode);
  const bank = useQuerySuggestions(term);
  const instruments = useInstrumentSearch(term);
  const completion = useStockCompletion(draft.slice(0, caret), suggest && focused && !busy);

  const items = useMemo<Item[]>(() => {
    if (!q) {
      return (prompts.data?.prompts ?? []).slice(0, 5).map((p) => ({
        key: p.id, text: p.label, why: p.outcome ?? p.badge, tag: humaniseTag(p.category) || "For you", tone: "mint" as Tone, query: p.query,
      }));
    }
    const out: Item[] = [];
    // The stock being typed at the cursor comes first: picking it completes the sentence.
    for (const s of (completion.data?.stocks ?? []).slice(0, 4)) {
      out.push({ key: `c:${s.symbol}`, text: s.symbol, why: stockWhy(s), tag: s.kind === "index" ? "Index" : "Stock", tone: "indigo", query: s.symbol, stock: s });
    }
    if (q.length < 2 || term !== q) return out;
    for (const s of (instruments.data?.stocks ?? []).slice(0, 2)) {
      out.push({ key: `s:${s.symbol}`, text: `Research ${s.name}`, why: [s.symbol, s.sector].filter(Boolean).join(" · "), tag: "Stock", tone: "indigo", query: `Tell me about ${s.name}` });
    }
    for (const f of (instruments.data?.funds ?? []).slice(0, 2)) {
      out.push({ key: `f:${f.scheme_code ?? f.name}`, text: `Research ${f.name}`, why: [f.amc, f.category].filter(Boolean).join(" · "), tag: "Fund", tone: "indigo", query: `Tell me about the mutual fund ${f.name}` });
    }
    for (const s of (bank.data?.suggestions ?? []).slice(0, 5)) {
      out.push({ key: `q:${s.query}`, text: s.query, why: [s.section, s.category].filter(Boolean).join(" · "), tag: "Question", tone: "ink", query: s.query, template: s.has_placeholder });
    }
    return out;
  }, [q, term, prompts.data, bank.data, instruments.data, completion.data]);

  // The highlighted row must always exist.
  useEffect(() => { setHi(-1); }, [q]);

  const open = suggest && focused && !busy;
  const tools = toolsNav(mode).slice(0, 3);
  const persona = !q ? prompts.data?.persona : undefined;
  const ctx = prompts.data?.context;
  const signals: string[] = [];
  if (persona && ctx) {
    if (ctx.equity_pct != null) signals.push(`Equity ${fmtPct(ctx.equity_pct, { digits: 0 })}`);
    if (ctx.debt_pct != null) signals.push(`Debt ${fmtPct(ctx.debt_pct, { digits: 0 })}`);
    if (ctx.gold_pct != null) signals.push(`Gold ${fmtPct(ctx.gold_pct, { digits: 0 })}`);
    if (ctx.max_overlap_pct != null && ctx.max_overlap_pct > 0) signals.push(`Max fund overlap ${fmtPct(ctx.max_overlap_pct, { digits: 0 })}`);
    if (ctx.action_count != null && ctx.action_count > 0) signals.push(`${fmtNum(ctx.action_count)} open actions`);
  }

  const send = (text: string) => {
    const t = text.replace(/\s+/g, " ").trim();
    if (!t || busy) return;
    setDraft("");
    setHi(-1);
    // The box keeps focus for the next question, but the list must not reopen
    // over the answer — it comes back on the next click or keystroke.
    setFocused(false);
    onSend(t);
  };

  const fill = (text: string) => {
    setDraft(text);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      const m = text.match(/\{[^}]+\}/);
      if (m && m.index != null) el.setSelectionRange(m.index, m.index + m[0].length);
      else el.setSelectionRange(text.length, text.length);
    });
  };

  const complete = (st: StockSuggestion) => {
    if (!completion.data) return;
    const el = inputRef.current;
    const at = el?.selectionStart ?? caret;
    const next = applyCompletion(draft, at, completion.data, st);
    setDraft(next.text);
    setCaret(next.caret);
    setHi(-1);
    requestAnimationFrame(() => {
      const box = inputRef.current;
      if (!box) return;
      box.focus();
      box.setSelectionRange(next.caret, next.caret);
    });
  };

  const pick = (it: Item) => {
    // A stock completion fills in the ticker and keeps the sentence; nothing is sent.
    if (it.stock) { complete(it.stock); return; }
    // A template still has a slot to fill ("How is {stock} doing?") — put it in
    // the box with the slot selected instead of sending it as is.
    if (it.template) fill(it.query);
    else send(it.query);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") { setFocused(false); setHi(-1); return; }
    if (open && items.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => (h + 1) % items.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => (h <= 0 ? items.length - 1 : h - 1)); return; }
      if (e.key === "Tab" && hi >= 0) { e.preventDefault(); if (items[hi].stock) complete(items[hi].stock as StockSuggestion); else fill(items[hi].query); return; }
      // Tab with nothing highlighted completes the first stock, when there is one.
      if (e.key === "Tab" && hi < 0 && items[0]?.stock) { e.preventDefault(); complete(items[0].stock); return; }
    }
    if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (open && hi >= 0 && items[hi]) pick(items[hi]);
      else send(draft.replace(/\{[^}]*\}/g, " "));
    }
  };

  const loadingSuggest = (!!q && q.length >= 2 && (term !== q || bank.isFetching || instruments.isFetching)) || completion.pending;
  const showList = open && (items.length > 0 || !!persona || !q || loadingSuggest);

  return (
    <div className="cp-composer" style={{ padding: `12px ${mobile ? 16 : 28}px calc(${mobile ? 14 : 20}px + env(safe-area-inset-bottom))` }}>
      <div className="nv-glass mx-auto flex flex-col" style={{ position: "relative", maxWidth: 880, gap: 10, padding: "14px 14px 12px 18px", borderRadius: 20, boxShadow: "var(--shadow-pop)" }}>
        {showList && (
          <div
            data-testid="composer-suggest"
            className="cp-scroll flex flex-col"
            style={{ position: "absolute", left: 0, right: 0, bottom: "calc(100% + 10px)", zIndex: 20, maxHeight: mobile ? "62vh" : 460, overflow: "auto", borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "var(--shadow-pop)" }}
            // Keep focus in the input while a row is being clicked.
            onMouseDown={(e) => e.preventDefault()}
          >
            {persona && (
              <div data-testid="composer-persona" className="flex flex-col" style={{ gap: 10, padding: "16px 18px", borderBottom: "1px solid var(--cp-line)" }}>
                <span className="cp-eyebrow" style={{ color: "var(--mint)" }}>Your persona · set by Nivesh from your portfolio</span>
                <span style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2 }}>{humaniseTag(persona)}</span>
                {signals.length > 0 && (
                  <div className="flex flex-wrap" style={{ gap: 6 }}>
                    {signals.map((g) => (
                      <span key={g} style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", padding: "4px 8px", borderRadius: 6, background: "var(--bg-2)", border: "1px solid var(--cp-line)", color: "var(--cp-ink-2)", textTransform: "uppercase" }}>{g}</span>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="flex flex-col" style={{ padding: 6 }} role="listbox" aria-label={q ? "Completions" : "Suggested for you"}>
              {(items.length > 0 || loadingSuggest) && <span className="cp-eyebrow" style={{ padding: "10px 12px 6px" }}>{q ? "Completions" : "Suggested for you"}</span>}
              {items.map((it, i) => (
                <button
                  key={it.key}
                  type="button"
                  role="option"
                  aria-selected={i === hi}
                  data-testid="composer-suggest-item"
                  data-kind={it.stock ? "stock-completion" : it.template ? "template" : "query"}
                  onClick={() => pick(it)}
                  onMouseEnter={() => setHi(i)}
                  className="flex items-center"
                  style={{ gap: 12, padding: "10px 12px", borderRadius: 10, cursor: "pointer", background: i === hi ? "var(--bg-2)" : "transparent", border: 0, color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}
                >
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink-3)", width: 14, flex: "none" }} aria-hidden>{it.stock ? "⇥" : it.template ? "…" : "↗"}</span>
                  <span className="flex min-w-0 flex-1 flex-col" style={{ gap: 2 }}>
                    <span style={{ fontSize: 14, color: "var(--cp-ink)", ...(mobile ? { lineHeight: 1.35 } : { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }) }}>{it.text}</span>
                    {it.why && <span style={{ fontSize: 12, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{it.why}</span>}
                  </span>
                  {/* On a phone the tag would squeeze the question to a few words. */}
                  {!mobile && <span className="cp-pill" data-tone={it.tone} style={{ flex: "none" }}>{it.tag}</span>}
                </button>
              ))}
              {loadingSuggest && items.length === 0 && <span style={{ padding: "8px 12px", fontSize: 13, color: "var(--cp-ink-3)" }}>Looking for matches…</span>}
            </div>
            {!q && (
              <div className="flex flex-wrap items-center" style={{ gap: 6, padding: "4px 18px 14px" }}>
                <span className="cp-eyebrow" style={{ marginRight: 4 }}>Tools for you</span>
                {tools.map((tl) => (
                  <button key={tl.view} type="button" className="cp-chip" style={{ padding: "6px 12px", borderRadius: 10, fontSize: 12 }} onClick={() => { setFocused(false); inputRef.current?.blur(); onGo(tl.view); }}>{tl.label} ›</button>
                ))}
              </div>
            )}
            {!mobile && (
              <div className="flex flex-wrap justify-between" style={{ gap: 10, padding: "10px 18px", borderTop: "1px solid var(--cp-line)", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", color: "var(--cp-ink-4)" }}>
                <span>↑↓ MOVE · TAB COMPLETE · ENTER ASK · ESC CLOSE</span>
                {!q && items.length > 0 && <span>{prompts.data?.audience === "advisor" ? "RANKED FOR YOUR CLIENT BOOK" : prompts.data?.audience === "trader" ? "YOUR DAILY TRADING QUESTIONS" : "RANKED FOR YOUR HOLDINGS"}</span>}
              </div>
            )}
          </div>
        )}

        <input
          ref={inputRef}
          data-testid="composer-input"
          aria-label="Ask Nivesh"
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setCaret(e.target.selectionStart ?? e.target.value.length); setFocused(true); }}
          onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? draft.length)}
          onKeyDown={onKeyDown}
          onFocus={() => setFocused(true)}
          onClick={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={mobile ? "Ask about your portfolio or a stock…" : "Ask about your portfolio, a stock, a sector, a filing or a strategy…"}
          autoComplete="off"
          enterKeyHint="send"
          style={{ border: 0, outline: 0, background: "transparent", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 16, padding: "6px 0", width: "100%" }}
        />
        <div className="flex flex-wrap items-center justify-between" style={{ gap: "10px 12px" }}>
          <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
            <button type="button" data-testid="composer-attach" onClick={onAttach} title="Import a statement" aria-label="Import a statement" className="grid place-items-center" style={{ width: 30, height: 30, borderRadius: "50%", border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", cursor: "pointer" }}>＋</button>
          </div>
          <div className="flex items-center" style={{ gap: 12 }}>
            <Freshness />
            {busy ? (
              <button type="button" data-testid="composer-stop" onClick={onStop} aria-label="Stop the answer" className="grid place-items-center" style={{ width: 36, height: 36, borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-3)", color: "var(--cp-ink)", fontSize: 12, cursor: "pointer" }}>■</button>
            ) : (
              <button type="button" data-testid="composer-send" onClick={() => send(draft.replace(/\{[^}]*\}/g, " "))} disabled={!q} aria-label="Ask" className="grid place-items-center" style={{ width: 36, height: 36, borderRadius: 12, border: 0, background: "var(--mint)", color: "#06120B", fontSize: 16, cursor: q ? "pointer" : "default", opacity: q ? 1 : 0.45 }}>↑</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});
