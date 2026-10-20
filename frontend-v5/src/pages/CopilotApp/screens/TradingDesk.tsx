/**
 * Smart trading desk — a Trader tool. Design: "Smart Trading Desk" (the
 * user's attached design, 2026-10-14); navigation: the desk PRD §3.1
 * (docs/smart_trader), which orders the desktop tabs like the design's phone
 * chips and puts the Options & futures lab under More.
 *
 *   01 Overview               indices, breadth, regime, flows, sector strength    tradingdesk/OverviewTab
 *   02 AI Scanner             setups ranked from the end-of-day scanner            tradingdesk/ScannerTab
 *   03 Market Intelligence    classified filings and institutional flows           tradingdesk/IntelTab
 *   04 Chart Analysis         candles, indicators, levels and the risk desk        tradingdesk/ChartTab
 *   05 Portfolio & Risk       broker-read holdings, concentration, risk figures    tradingdesk/PortfolioTab
 *   06 More                   AI Copilot · Options & futures lab (tradingdesk/FnoTab) · Watchlists ·
 *                             Saved analyses · Paper trading · Settings & integrations
 *
 * The frame itself reads:
 *   GET /api/markets/home                   `market_state` and `is_live` for the market-status pill (useMarketOverview)
 *   GET /api/positional/watchlist + picks   the scanner list the header search matches a stock against (useDeskScanner)
 *
 * Every block reads an existing endpoint (named in each tab's header comment).
 * A block with no data source says so ("Not connected yet") instead of showing
 * the design's sample figures. Nivesh reads data; nothing here places an order.
 *
 * Desktop (design §2): a header row with the search (a scanner stock is
 * selected, any other NSE symbol opens on the Chart tab — the chart
 * workspace's instrument search, PRD §7.2 — and a question goes to the
 * Copilot), the TRADER / INVESTOR switch and the market status; the module tab row; the tab beside the docked
 * Copilot (from 1400px; the shell's own ask box is hidden there, index.tsx);
 * the disclaimer footer. There is no page headline: the headline is the
 * Overview's.
 *
 * Phone (under 700px): the title block with search and the persona pill (design
 * §11), and a persistent bottom navigation bar (PRD §3.1, §3.3; the user's
 * decision of 2026-10-14): Overview · Scanner · Intel · Chart · Portfolio · More
 * (tradingdesk/BottomBar). The top chip row is gone on phones. On desk pages the
 * app's ask box is hidden on a phone (index.tsx): the desk's Copilot is More ·
 * AI Copilot, so there is one ask box, never two.
 *
 * More (?tab=more) lists real destinations only. Its AI Copilot is the desk's
 * Copilot full height wherever it is not docked (a phone, or a desktop under
 * 1400px; the shell's ask box is hidden on that view, index.tsx); with the
 * dock showing, More lists the destinations and "AI Copilot" moves focus to
 * the dock. `?tab=fno` opens the lab under More, so old links keep working.
 * PRD "Learning and methodology" has no view in the app yet: More says so in
 * a line of text, not with a button that goes nowhere.
 *
 * The tab, the selected stock and the wording live in the URL (?tab=&sym=&persona=).
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type LazyExoticComponent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { LoadingBlock } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { useMarketOverview } from "./markets/hooks";
import { BOTTOM_BAR_SPACE, DeskBottomBar, type BottomKey } from "./tradingdesk/BottomBar";
import { CopilotDock, type CopilotDockHandle } from "./tradingdesk/CopilotDock";
import { DESK_TAB_LABEL, DeskProvider, isDeskTab, type DeskPersona, type DeskState, type DeskTab } from "./tradingdesk/context";
import { useDeskScanner, type DeskSetup } from "./tradingdesk/desk-data";
import { istParts, marketStatus, useNow } from "./tradingdesk/overview-data";

const TAB_SCREENS: Record<DeskTab, LazyExoticComponent<ComponentType>> = {
  overview: lazy(() => import("./tradingdesk/OverviewTab")),
  scanner: lazy(() => import("./tradingdesk/ScannerTab")),
  chart: lazy(() => import("./tradingdesk/ChartTab")),
  intel: lazy(() => import("./tradingdesk/IntelTab")),
  portfolio: lazy(() => import("./tradingdesk/PortfolioTab")),
  fno: lazy(() => import("./tradingdesk/FnoTab")),
};

/** Test-only: ?tab=more&view=strategy-graphs mounts the strategy graphs from a spec's fixture. Present only in a build with VITE_STRATEGY_HARNESS=1. */
const StrategyBuilder = lazy(() => import("./tradingdesk/strategy/StrategyBuilder"));

/** Params only the Strategy Builder uses; they are dropped when the desk leaves it. */
const BUILDER_PARAMS = ["view", "direction", "instrument", "horizon", "build", "plan", "src_kind", "src_bucket", "src_date", "cand", "mode", "focus", "capital", "risk_inr", "risk_pct", "max_alloc", "min_rr", "horizon_days", "avoid_events", "multi_leg", "expiry"];

const StrategyGraphsHarness = import.meta.env.VITE_STRATEGY_HARNESS === "1" ? lazy(() => import("./tradingdesk/strategy/StrategyGraphsHarness")) : null;

/** Symbols the URL may carry: the F&O routes' own rule (letters, digits, & and -). */
const SYM_RE = /^[A-Z0-9&-]{1,20}$/;

/** The primary tabs before More, in the PRD's order (§3.1). Phones use the bottom bar's own short names (BottomBar.tsx). */
const NAV: Array<{ key: Exclude<DeskTab, "fno"> }> = [
  { key: "overview" },
  { key: "scanner" },
  { key: "intel" },
  { key: "chart" },
  { key: "portfolio" },
];

/** The shell's side padding (index.tsx): the header, tab row and footer run edge to edge across it. */
const padFor = (mobile: boolean) => (mobile ? 16 : 28);

/** The portfolio tab's paper-trade card (PortfolioTab.tsx), which "Paper trading" scrolls to. */
const PAPER_CARD = '[data-testid="desk-portfolio-record"]';

/** One word that can be an NSE symbol (letters, digits, & and -), as the URL's ?sym= allows. */
const SYMBOL_TOKEN = /^[A-Za-z0-9&-]{1,20}$/;

/**
 * A scanner stock the search text names: the exact symbol, else the
 * best-ranked symbol it starts (two letters or more). A sentence is never a symbol.
 */
function matchSetup(setups: DeskSetup[], text: string): string | null {
  const t = text.trim().toUpperCase();
  if (!t || /\s/.test(t) || t.length > 20) return null;
  const exact = setups.find((s) => s.symbol.toUpperCase() === t);
  if (exact) return exact.symbol;
  if (t.length < 2) return null;
  return setups.find((s) => s.symbol.toUpperCase().startsWith(t))?.symbol ?? null;
}

// ── header pieces ────────────────────────────────────────────────────────

function SearchBox({ onSubmit, autoFocus }: { onSubmit: (text: string) => void; autoFocus?: boolean }) {
  const [text, setText] = useState("");
  return (
    <form
      role="search"
      onSubmit={(e) => { e.preventDefault(); const t = text.trim(); if (!t) return; setText(""); onSubmit(t); }}
      className="flex items-center"
      style={{ flex: "1 1 220px", maxWidth: 380, minWidth: 0, height: 38, gap: 8, padding: "0 6px 0 14px", borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}
    >
      <span aria-hidden style={{ color: "var(--cp-ink-3)", fontSize: 15 }}>⌕</span>
      <input
        data-testid="desk-search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search a stock or ask Nivesh…"
        aria-label="Search any NSE stock by symbol, or ask Nivesh"
        autoFocus={autoFocus}
        style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: "none", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13 }}
      />
      <span aria-hidden className="cp-num" style={{ flex: "none", fontSize: 9, letterSpacing: "0.1em", padding: "3px 7px", borderRadius: 999, border: "1px solid var(--line-2)", color: "var(--cp-ink-3)" }}>ENTER</span>
    </form>
  );
}

function PersonaSwitch({ persona, onPick }: { persona: DeskPersona; onPick: (p: DeskPersona) => void }) {
  return (
    <div role="group" aria-label="Desk wording" className="inline-flex" style={{ flex: "none", gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
      {(["trader", "investor"] as const).map((p) => {
        const on = p === persona;
        return (
          <button
            key={p}
            type="button"
            aria-pressed={on}
            data-testid={`desk-persona-${p}`}
            onClick={() => onPick(p)}
            title={p === "trader" ? "Technical wording" : "Plain wording"}
            style={{
              padding: "6px 12px", borderRadius: 999, border: 0, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.12em",
              textTransform: "uppercase", background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            }}
          >
            {p}
          </button>
        );
      })}
    </div>
  );
}

/** "NSE hours · 11:32 IST" / "Market closed · 16:05 IST" — from GET /api/markets/home, else the IST clock. */
function StatusPill() {
  const home = useMarketOverview();
  const now = istParts(useNow());
  const s = marketStatus(home.data, now);
  const tone = s.feed === "live" ? "mint" : s.feed === "delayed" ? "amber" : "ink";
  const dot = tone === "mint" ? "var(--mint)" : tone === "amber" ? "var(--amber)" : "var(--cp-ink-4)";
  return (
    <span
      data-testid="desk-market-status"
      data-feed={s.feed}
      data-open={s.open ? "true" : "false"}
      className="cp-pill"
      data-tone={tone}
      title={s.why}
      style={{ flex: "none", background: tone === "mint" ? "var(--mint-soft)" : undefined }}
    >
      <span className="nv-dot" style={{ background: dot }} />
      {s.label}{s.holiday ? ` · ${s.holiday}` : ""} · {now.time} IST
    </span>
  );
}

/** After the search selects a stock: say so, with the way to its chart. */
function Picked({ symbol, onChart }: { symbol: string; onChart: () => void }) {
  return (
    <span role="status" data-testid="desk-search-picked" className="flex items-center" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-3)" }}>
      <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{symbol}</span> selected
      <button type="button" onClick={onChart} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12, color: "var(--mint)" }}>Chart ›</button>
    </span>
  );
}

function TabChip({ id, label, num, on, onClick, small }: { id: string; label: string; num?: string; on: boolean; onClick: () => void; small?: boolean }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      data-testid={`desk-tab-${id}`}
      onClick={onClick}
      className="flex items-center"
      style={{
        flex: "none", gap: 8, padding: small ? "7px 12px" : "8px 14px", borderRadius: 999, fontSize: small ? 12 : 13, fontWeight: 500, whiteSpace: "nowrap", cursor: "pointer",
        fontFamily: "var(--sans)", border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
        background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-2)",
      }}
    >
      {num && <span className="cp-num" style={{ fontSize: 9.5, color: on ? "var(--mint)" : "var(--cp-ink-4)" }}>{num}</span>}
      {label}
    </button>
  );
}

// ── More ─────────────────────────────────────────────────────────────────

type MoreKey = "copilot" | "fno" | "strategy" | "watchlist" | "saved" | "paper" | "settings";

/**
 * More's destinations (PRD §3.1), each a real view. PRD "Learning and
 * methodology" has no view in the app yet, so it is not listed.
 */
const MORE: Array<{ key: MoreKey; label: string; note: string }> = [
  { key: "copilot", label: "AI Copilot", note: "Ask about anything on the desk, with sources" },
  { key: "fno", label: "Options & futures lab", note: "NSE F&O: open interest, build-up and option chains (end of day)" },
  { key: "strategy", label: "Strategy Builder", note: "Cash, futures and options plans for one stock, with the evidence and the payoff" },
  { key: "watchlist", label: "Watchlists", note: "Your watchlists and price alerts" },
  { key: "saved", label: "Saved analyses", note: "Copilot threads, screens and questions you kept" },
  { key: "paper", label: "Paper trading", note: "Your paper trades: predicted against actual" },
  { key: "settings", label: "Settings & integrations", note: "Broker connections (read-only) and statement imports" },
];

/** Small filter-style chip (design §1) for More's destinations. */
function SubChip({ id, on, onClick, children }: { id: MoreKey; on?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      data-testid={`desk-more-${id}`}
      aria-pressed={on === undefined ? undefined : on}
      onClick={onClick}
      style={{
        flex: "none", padding: "5px 11px", borderRadius: 999, fontSize: 12, whiteSpace: "nowrap", cursor: "pointer", fontFamily: "var(--sans)",
        border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--mint)" : "var(--cp-ink-2)",
      }}
    >
      {children}
    </button>
  );
}

/** PRD §3.1 lists "Learning and methodology" under More; the app has no such view yet, so it is a line of text, not a button. */
function LearningGap({ phone }: { phone?: boolean }) {
  return (
    <p data-testid="desk-more-learning-gap" className="m-0" style={{ paddingBottom: phone ? 12 : 0, fontSize: phone ? 11.5 : 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
      Learning and methodology: not in the app yet.
    </p>
  );
}

/** With the Copilot docked: More as a list of its destinations. */
function MoreList({ onPick }: { onPick: (k: MoreKey) => void }) {
  return (
    <section data-testid="desk-more-list" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden", boxShadow: "var(--shadow-card)" }}>
      <div style={{ padding: "13px 18px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
        <span className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>06</span> · More</span>
      </div>
      <ul className="m-0 grid p-0" style={{ listStyle: "none", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))" }}>
        {MORE.map((m) => (
          <li key={m.key} style={{ borderTop: "1px solid var(--cp-line)" }}>
            <button
              type="button"
              data-testid={`desk-more-item-${m.key}`}
              onClick={() => onPick(m.key)}
              className="cp-row-link flex w-full flex-col"
              style={{ gap: 4, padding: "14px 18px", border: 0, background: "transparent", color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}
            >
              <span style={{ fontSize: 14, fontWeight: 500 }}>{m.label} ›</span>
              <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
                {m.key === "copilot" ? "Docked at the right of the desk. Ask about anything on it, with sources." : m.note}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Questions for the desk's Copilot about what the desk is showing. */
function useDockChips(tab: DeskTab, symbol: string | null): string[] {
  const q = useDeskScanner();
  const top = q.data?.setups[0]?.symbol;
  const sym = symbol ?? top ?? null;
  return useMemo(() => {
    const out: string[] = [];
    if (tab === "chart" && sym) {
      out.push(`Explain the ${sym} setup and what would invalidate it`);
      out.push(`Size a trade in ${sym} with 1% risk`);
    } else if (tab === "fno") {
      out.push("What does NIFTY option OI say about this expiry?");
      out.push("Which F&O stocks show long build-up today?");
    } else if (tab === "portfolio") {
      out.push("What are the key risks in my portfolio this week?");
    } else if (tab === "intel") {
      out.push("Summarise today’s most important filings");
    } else {
      if (top) out.push(`Why does ${top} rank first on the scanner?`);
      out.push("Which sectors are leading today and why?");
    }
    out.push("What are the key market risks this week?");
    return [...new Set(out)];
  }, [tab, sym, top]);
}

export default function TradingDeskScreen() {
  const { mobile, wide, go } = useCopilotShell();
  const [params, setParams] = useSearchParams();
  const rawTab = params.get("tab");
  const more = rawTab === "more";
  const tab: DeskTab = isDeskTab(rawTab) ? rawTab : "overview";
  const rawSym = (params.get("sym") || "").toUpperCase();
  const symbol = SYM_RE.test(rawSym) ? rawSym : null;
  const persona: DeskPersona = params.get("persona") === "investor" ? "investor" : "trader";
  const docked = wide;
  // The desk's Copilot full height in the page: More's AI Copilot wherever it is not docked.
  const strategyView = more && params.get("view") === "strategy";
  const pageCopilot = more && !docked && !strategyView;
  const moreOn = more || tab === "fno";
  const dockRef = useRef<CopilotDockHandle>(null);
  const pendingAsk = useRef<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const scan = useDeskScanner();
  const padX = padFor(mobile);

  const update = useCallback((next: { tab?: DeskTab | "more"; sym?: string; persona?: DeskPersona; view?: string; extra?: Record<string, string> }) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next.tab) {
        p.set("tab", next.tab);
        for (const k of BUILDER_PARAMS) p.delete(k);
        if (next.view) p.set("view", next.view);
        for (const [k, v] of Object.entries(next.extra ?? {})) p.set(k, v);
      }
      if (next.sym) p.set("sym", next.sym.toUpperCase());
      if (next.persona === "investor") p.set("persona", "investor");
      else if (next.persona === "trader") p.delete("persona");
      return p;
    }, { replace: true });
  }, [setParams]);

  // Questions go to the desk's own Copilot: the dock when it shows, else More · AI Copilot.
  const askDesk = useCallback((question: string) => {
    if (dockRef.current) {
      dockRef.current.ask(question);
      return;
    }
    pendingAsk.current = question;
    update({ tab: "more" });
  }, [update]);

  // A question asked from another view is sent once More · AI Copilot is up.
  useEffect(() => {
    if (!pageCopilot || !pendingAsk.current || !dockRef.current) return;
    const q = pendingAsk.current;
    pendingAsk.current = null;
    dockRef.current.ask(q);
  }, [pageCopilot]);

  const desk = useMemo<DeskState>(() => ({
    tab,
    openTab: (t) => update({ tab: t }),
    symbol,
    openChart: (s) => update({ tab: "chart", sym: s }),
    setSymbol: (s) => update({ sym: s }),
    openStrategy: (s, src) => update({
      tab: "more", view: "strategy", sym: s,
      extra: src ? { src_kind: src.kind, ...(src.bucket ? { src_bucket: src.bucket } : {}), ...(src.date ? { src_date: src.date } : {}) } : undefined,
    }),
    openStrategyIdeas: (focus) => update({ tab: "more", view: "strategy", extra: { mode: "ideas", ...(focus ? { focus: focus.toUpperCase() } : {}) } }),
    askDesk,
    docked,
    persona,
    setPersona: (p) => update({ persona: p }),
  }), [tab, symbol, update, askDesk, docked, persona]);

  // "Paper trading": the Portfolio & Risk tab, scrolled to its paper-trade card once it has rendered.
  const scrollTimer = useRef<number | null>(null);
  useEffect(() => () => { if (scrollTimer.current) window.clearInterval(scrollTimer.current); }, []);
  const openPaper = () => {
    update({ tab: "portfolio" });
    if (scrollTimer.current) window.clearInterval(scrollTimer.current);
    let tries = 0;
    scrollTimer.current = window.setInterval(() => {
      const el = document.querySelector(PAPER_CARD);
      tries += 1;
      if (el || tries > 40) {
        if (scrollTimer.current) window.clearInterval(scrollTimer.current);
        scrollTimer.current = null;
        el?.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    }, 150);
  };

  const pickMore = (k: MoreKey) => {
    if (k === "copilot") {
      if (dockRef.current && docked) dockRef.current.focus();
      else update({ tab: "more" });
    } else if (k === "fno") update({ tab: "fno" });
    else if (k === "strategy") update({ tab: "more", view: "strategy" });
    else if (k === "watchlist") go("page/watchlist");
    else if (k === "saved") go("page/saved");
    else if (k === "paper") openPaper();
    else go("page/brokers");
  };

  // Search (also the chart workspace's instrument search, PRD §7.2):
  //   a scanner stock (symbol prefix)  → selected; the tab stays
  //   any other one-word symbol        → opened on the Chart tab (?sym=), which loads any NSE symbol
  //   anything else (words, questions) → asked to the desk's Copilot
  const onSearch = (text: string) => {
    const t = text.trim();
    const sym = matchSetup(scan.data?.setups ?? [], t);
    if (sym) {
      desk.setSymbol(sym);
      setPicked(sym);
    } else if (SYMBOL_TOKEN.test(t)) {
      setPicked(null);
      if (!more && tab === "chart") desk.setSymbol(t);
      else desk.openChart(t);
    } else {
      setPicked(null);
      askDesk(t);
    }
  };

  const chips = useDockChips(more ? "overview" : tab, symbol);
  const TabScreen = TAB_SCREENS[tab];
  const bleed = { margin: `0 -${padX}px`, padding: `0 ${padX}px` };

  const moreChips = moreOn && (
    <div data-testid="desk-more-chips" role="group" aria-label="More" className="cp-scroll flex overflow-x-auto" style={{ gap: 6, ...(mobile ? { ...bleed, paddingBottom: 12 } : {}) }}>
      {MORE.map((m) => (
        <SubChip key={m.key} id={m.key} on={m.key === "copilot" ? more && !docked && !strategyView : m.key === "fno" ? !more && tab === "fno" : m.key === "strategy" ? strategyView : undefined} onClick={() => pickMore(m.key)}>
          {m.label}
        </SubChip>
      ))}
    </div>
  );

  let content: ReactNode;
  if (StrategyGraphsHarness && more && params.get("view") === "strategy-graphs") {
    content = (
      <div data-testid="desk-panel-strategy-graphs" className="flex min-w-0 flex-col">
        <Suspense fallback={<LoadingBlock label="Loading" rows={4} />}><StrategyGraphsHarness /></Suspense>
      </div>
    );
  } else if (strategyView) {
    content = (
      <div data-testid="desk-panel-strategy" role="tabpanel" aria-label="Strategy Builder" className="flex min-w-0 flex-col">
        <SafeWidget key="strategy" name="Trading desk · strategy builder">
          <Suspense fallback={<LoadingBlock label="Loading the Strategy Builder" rows={4} />}><StrategyBuilder /></Suspense>
        </SafeWidget>
      </div>
    );
  } else if (pageCopilot) {
    content = (
      <div data-testid="desk-panel-more" role="tabpanel" aria-label="AI Copilot" className="flex min-w-0 flex-col">
        <CopilotDock ref={dockRef} chips={chips} height="calc(100dvh - 250px)" variant="page" />
      </div>
    );
  } else if (more) {
    content = (
      <div data-testid="desk-panel-more" role="tabpanel" aria-label="More" className="flex min-w-0 flex-col">
        <MoreList onPick={pickMore} />
      </div>
    );
  } else {
    content = (
      <div data-testid={`desk-panel-${tab}`} role="tabpanel" aria-label={DESK_TAB_LABEL[tab]} className="flex min-w-0 flex-col" style={{ gap: mobile ? 12 : 16 }}>
        <SafeWidget key={tab} name={`Trading desk · ${tab}`}>
          <Suspense fallback={<LoadingBlock label={`Loading ${DESK_TAB_LABEL[tab]}`} rows={4} />}>
            <TabScreen />
          </Suspense>
        </SafeWidget>
      </div>
    );
  }

  const footer = (
    <footer
      data-testid="desk-disclaimer"
      className={mobile ? "flex flex-col" : "flex items-baseline"}
      style={{ gap: mobile ? 6 : 12, ...bleed, paddingTop: 14, paddingBottom: 14, borderTop: "1px solid var(--cp-line)" }}
    >
      <span className="cp-num" style={{ flex: "none", fontSize: 9.5, letterSpacing: "0.14em", color: "var(--cp-ink-4)" }}>DISCLAIMER</span>
      <span style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        Scanner setups are end-of-day and rules-based. Probabilities are model outputs for the next session, not buy or sell recommendations. Broker connections are read-only; Nivesh does not place orders. 9 out of 10 individual traders in equity F&amp;O incurred net losses (SEBI study).
      </span>
    </footer>
  );

  const dataTab = more ? "more" : tab;

  if (mobile) {
    const bottomKey: BottomKey = moreOn ? "more" : tab;
    // Room under the content for the fixed bottom bar; the phone Copilot's ask box sits above it (CopilotDock).
    const phoneStyle = { paddingTop: 4, paddingBottom: BOTTOM_BAR_SPACE, ["--desk-bottom-bar" as string]: BOTTOM_BAR_SPACE } as CSSProperties;
    return (
      <DeskProvider value={desk}>
        <div data-testid="screen-trading-desk" data-tab={dataTab} data-symbol={symbol ?? ""} data-persona={persona} className="flex min-w-0 flex-col" style={phoneStyle}>
          <header data-testid="desk-mobile-header" className="flex flex-col" style={{ gap: 10, paddingBottom: 12 }}>
            <div className="flex items-center" style={{ gap: 10 }}>
              <span className="nv-mark" aria-hidden style={{ flex: "none", width: 32, height: 32, fontSize: 19 }}>न</span>
              <span className="flex min-w-0 flex-col" style={{ gap: 3 }}>
                <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1 }}>Nivesh Copilot</span>
                <span className="cp-num" style={{ fontSize: 8.5, letterSpacing: "0.14em", color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>AI SMART TRADING DESK</span>
              </span>
              <span style={{ flex: 1 }} />
              <button
                type="button"
                data-testid="desk-search-toggle"
                aria-label="Search a stock or ask Nivesh"
                aria-expanded={searchOpen}
                onClick={() => setSearchOpen((o) => !o)}
                className="grid place-items-center"
                style={{ flex: "none", width: 32, height: 32, borderRadius: 999, border: "1px solid var(--line-2)", background: searchOpen ? "var(--bg-3)" : "transparent", color: "var(--cp-ink-2)", fontSize: 15, cursor: "pointer" }}
              >
                ⌕
              </button>
              <button
                type="button"
                data-testid="desk-persona-pill"
                aria-label={`Wording: ${persona}. Switch to ${persona === "trader" ? "investor" : "trader"}`}
                onClick={() => desk.setPersona(persona === "trader" ? "investor" : "trader")}
                className="cp-pill"
                data-tone="mint"
                style={{ flex: "none", cursor: "pointer", background: "var(--mint-soft)" }}
              >
                {persona === "trader" ? "Trader" : "Investor"}
              </button>
            </div>
            {searchOpen && <SearchBox onSubmit={onSearch} autoFocus />}
            {picked && <Picked symbol={picked} onChart={() => desk.openChart(picked)} />}
          </header>

          {moreChips}
          {moreOn && <LearningGap phone />}

          <div style={{ paddingBottom: 18 }}>{content}</div>
          {!pageCopilot && footer}
          <DeskBottomBar active={bottomKey} onPick={(k) => update({ tab: k })} />
        </div>
      </DeskProvider>
    );
  }

  return (
    <DeskProvider value={desk}>
      <div
        data-testid="screen-trading-desk"
        data-tab={dataTab}
        data-symbol={symbol ?? ""}
        data-persona={persona}
        className="mx-auto flex min-w-0 flex-col"
        style={{ maxWidth: docked ? 1480 : 1180 }}
      >
        <div data-testid="desk-topbar" className="flex flex-wrap items-center" style={{ minHeight: 64, gap: "10px 14px", ...bleed, paddingTop: 12, paddingBottom: 12, borderBottom: "1px solid var(--cp-line)" }}>
          <span className="cp-eyebrow" style={{ whiteSpace: "nowrap" }}>AI Smart Trading Desk</span>
          {picked && <Picked symbol={picked} onChart={() => desk.openChart(picked)} />}
          <span style={{ flex: "1 1 0", minWidth: 0 }} />
          <SearchBox onSubmit={onSearch} />
          <PersonaSwitch persona={persona} onPick={desk.setPersona} />
          <StatusPill />
        </div>

        <div className="flex items-center" style={{ gap: 12, ...bleed, paddingTop: 12, paddingBottom: 12, borderBottom: "1px solid var(--cp-line)" }}>
          <div role="tablist" aria-label="Desk modules" className="cp-scroll flex min-w-0 overflow-x-auto" style={{ flex: 1, gap: 6 }}>
            {NAV.map((t, i) => (
              <TabChip key={t.key} id={t.key} num={String(i + 1).padStart(2, "0")} label={DESK_TAB_LABEL[t.key]} on={!moreOn && t.key === tab} onClick={() => update({ tab: t.key })} />
            ))}
            <TabChip id="more" num="06" label="More" on={moreOn} onClick={() => update({ tab: "more" })} />
          </div>
          {docked && <span data-testid="desk-docked-note" className="cp-eyebrow" style={{ flex: "none", whiteSpace: "nowrap" }}>Copilot docked right</span>}
        </div>

        <div
          className="grid"
          style={{
            gridTemplateColumns: docked ? "minmax(0,1fr) 384px" : "minmax(0,1fr)",
            gap: 20,
            alignItems: "start",
            padding: "24px 0 28px",
            minHeight: docked ? 900 : undefined,
          }}
        >
          <div className="flex min-w-0 flex-col" style={{ gap: 20 }}>
            {moreChips}
            {moreOn && <LearningGap />}
            {content}
          </div>
          {docked && (
            <div style={{ position: "sticky", top: 20 }}>
              <CopilotDock ref={dockRef} chips={chips} height="min(820px, calc(100dvh - 40px))" />
            </div>
          )}
        </div>
        {!pageCopilot && footer}
      </div>
    </DeskProvider>
  );
}
