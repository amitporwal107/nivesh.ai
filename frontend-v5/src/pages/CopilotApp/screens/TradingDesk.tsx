/**
 * Smart trading desk — a Trader tool. Layout: the owner's redesign of 2026-10-27 (docs/desk_redesign_20261027/PLAN.md,
 * step 1 "Shell"), in the V5 look of the owner's "Nivesh Trader Workspace" design: a PAPER MODE banner, the header,
 * four numbered tabs, "My portfolio", and at most two levels (tab → view). The places and every old URL's redirect
 * are in tradingdesk/desk-nav.ts.
 *
 *   01 Market Overview   one page: the market part of OverviewTab · ScannerPulse · ScannerTop10 (with the decision
 *                        cards) · "All scanner candidates" (ScannerTab's list, collapsed) · "N open paper trades"
 *   02 Trade Desk        open · closed · new: tabs/trade-desk/TradeDeskTab.tsx (step 3) — the header strip, Open & pending,
 *                        Closed & journal (the journal drawer) and New trade (the risk-service ticket, the F&O builder,
 *                        the Strategy Builder, the backtest)
 *   03 Market Desk       intel · smartmoney · sectors · research · screener · watchlists (IntelTab + EventsTab;
 *                        SmartMoneyTab + the F&O lab's build-up, candidates, indices and chain; SectorHeatmap;
 *                        ChartTab; Screener + Chartink sources; the Watchlist page)
 *   04 Risk Desk         limits · controls · log (tradingdesk/tabs/risk-desk: paper risk only, built from RiskControls,
 *                        the risk profile, the F&O lab's live readiness and its decision lineage and replay)
 *   My portfolio         ?tab=portfolio: PortfolioTab without the paper cards (they are Trade Desk's), inside the frame
 *   AI Copilot           docked beside the desk from 1400px; below that ?tab=copilot shows it full height
 *
 * The content of each view is today's screen, re-hosted as it is (steps 2–5 of the plan redesign it). Nothing here
 * places an order: the desk's trades are paper trades, and broker connections are read-only.
 *
 * The frame itself reads:
 *   GET /api/markets/home                   `market_state` and `is_live` for the market-status pill (useMarketOverview)
 *   GET /api/risk/status                    the "Kill switch on" / "Trading halted" pill, shown only for a known "on" (useRiskStatus)
 *   GET /api/positional/watchlist + picks   the scanner list the header search matches a stock against (useDeskScanner)
 *   GET /api/desk/paper-trades              Market Overview's "N open paper trades" line (usePaperTrades)
 *
 * The place lives in the URL (?tab=&view=, plus the stock ?sym=, the wording ?persona= and the hosted screens' own
 * params); a tab or view change drops the previous view's params (desk-nav.ts VIEW_PARAMS). The breadcrumb is the
 * location ("Trading desk › Market Desk › Smart Money"), not the click path.
 *
 * Phone (under 700px): the banner, the title block with search, the wording pill and My portfolio, and a persistent
 * bottom bar (BottomBar.tsx): 01 Overview · 02 Trade · 03 Market · 04 Risk · Copilot. The app's own ask box is hidden
 * on desk pages on a phone (index.tsx); the desk's Copilot is the bar's Copilot, so there is one ask box, never two.
 */
import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { LoadingBlock } from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { useMarketOverview } from "./markets/hooks";
import { BOTTOM_BAR_SPACE, DeskBottomBar, type BottomKey } from "./tradingdesk/BottomBar";
import { CopilotDock, type CopilotDockHandle } from "./tradingdesk/CopilotDock";
import { DeskProvider, type DeskPersona, type DeskState, type DeskTab, type LabView } from "./tradingdesk/context";
import { useDeskScanner, type DeskSetup } from "./tradingdesk/desk-data";
import {
  DESK_SECTIONS, SECTION_LABEL, SECTION_VIEWS, VIEW_PARAMS, canonical, crumbsOf, defaultSub, defaultView, isSection, legacyRedirect, locationOf, placeOfOldTab,
  subViewsOf,
  type DeskLocation, type DeskPlace, type DeskSection,
} from "./tradingdesk/desk-nav";
import { usePaperTrades } from "./tradingdesk/desk-trading";
import { DeskTrail } from "./tradingdesk/DeskTrail";
import { SymbolSearch } from "./tradingdesk/SymbolSearch";
import { istParts, marketStatus, useNow } from "./tradingdesk/overview-data";
import { useRiskStatus } from "./tradingdesk/risk-controls";

// ── the hosted screens, each in its own chunk ────────────────────────────

const OverviewTab = lazy(() => import("./tradingdesk/OverviewTab"));
const ScannerTab = lazy(() => import("./tradingdesk/ScannerTab"));
const ScannerPulse = lazy(() => import("./tradingdesk/ScannerPulse").then((m) => ({ default: m.ScannerPulse })));
const ScannerTop10 = lazy(() => import("./tradingdesk/ScannerTop10").then((m) => ({ default: m.ScannerTop10 })));
const IntelTab = lazy(() => import("./tradingdesk/IntelTab"));
const EventsTab = lazy(() => import("./tradingdesk/EventsTab"));
const ChartTab = lazy(() => import("./tradingdesk/ChartTab"));
const SmartMoneyTab = lazy(() => import("./tradingdesk/SmartMoneyTab"));
const FnoTab = lazy(() => import("./tradingdesk/FnoTab"));
const PortfolioTab = lazy(() => import("./tradingdesk/PortfolioTab"));
const TradeDeskTab = lazy(() => import("./tradingdesk/tabs/trade-desk/TradeDeskTab"));
const ChartinkSettings = lazy(() => import("./tradingdesk/chartink/ChartinkSettings"));
const ForwardTestPanel = lazy(() => import("./tradingdesk/FnoForwardTest").then((m) => ({ default: m.ForwardTestPanel })));
const RiskDeskTab = lazy(() => import("./tradingdesk/tabs/risk-desk/RiskDeskTab"));
const SectorHeatmap = lazy(() => import("./SectorHeatmap"));
const Screener = lazy(() => import("./Screener"));
const Watchlist = lazy(() => import("./Watchlist"));

/** Test-only: ?tab=more&view=strategy-graphs mounts the strategy graphs from a spec's fixture. Present only in a build with VITE_STRATEGY_HARNESS=1. */
const StrategyGraphsHarness = import.meta.env.VITE_STRATEGY_HARNESS === "1" ? lazy(() => import("./tradingdesk/strategy/StrategyGraphsHarness")) : null;

/** The F&O lab's views on Market Desk › Smart Money (Trade Desk › New trade hosts its "strategies" view itself). */
const SMART_MONEY_LAB: readonly LabView[] = ["buildup", "candidates", "indices", "chain"];

/** Symbols the URL may carry: the F&O routes' own rule (letters, digits, & and -). */
const SYM_RE = /^[A-Z0-9&-]{1,20}$/;

/** The shell's side padding (index.tsx): the banner, header, tab row and footer run edge to edge across it. */
const padFor = (mobile: boolean) => (mobile ? 16 : 28);

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

/** The old tab name a place stands for (DeskState.tab; the hosted screens were written against these names). */
function oldTabOf(loc: DeskLocation): DeskTab {
  if (loc.tab === "portfolio") return "portfolio";
  if (loc.tab !== "market") return "overview";
  return loc.view === "research" ? "chart" : loc.view === "smartmoney" ? "smartmoney" : loc.view === "intel" ? "intel" : "overview";
}

// ── header pieces ────────────────────────────────────────────────────────

/** V5 FR-20: always on screen. Amber, mono, as the owner's design draws it. */
function PaperBanner({ padX, mobile }: { padX: number; mobile: boolean }) {
  return (
    <div
      data-testid="desk-paper-banner"
      role="note"
      className="flex items-center"
      style={{
        gap: 10, margin: `0 -${padX}px`, padding: `${mobile ? 7 : 8}px ${padX}px`, background: "var(--amber-soft)", borderBottom: "1px solid var(--amber-line)",
        fontFamily: "var(--mono)", fontSize: mobile ? 9.5 : 10.5, lineHeight: 1.5, letterSpacing: mobile ? "0.1em" : "0.14em", textTransform: "uppercase", color: "var(--amber)",
      }}
    >
      <span aria-hidden style={{ flex: "none", width: 7, height: 7, borderRadius: "50%", background: "var(--amber)" }} />
      <span style={{ minWidth: 0 }}>Paper mode · simulated execution only · no broker orders</span>
    </div>
  );
}

function SearchBox({ onSubmit, autoFocus, persona, setups, column }: { onSubmit: (text: string) => void; autoFocus?: boolean; persona: DeskPersona; setups: DeskSetup[]; column?: boolean }) {
  const [text, setText] = useState("");
  const top = useMemo(() => setups.slice(0, 6).map((s) => ({ symbol: s.symbol, name: null })), [setups]);
  return (
    <form
      role="search"
      onSubmit={(e) => { e.preventDefault(); const t = text.trim(); if (!t) return; setText(""); onSubmit(t); }}
      className="flex items-center"
      style={{ flex: column ? "none" : "1 1 220px", maxWidth: 380, minWidth: 0, height: 38, gap: 8, padding: "0 6px 0 14px", borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)", position: "relative" }}
    >
      <span aria-hidden style={{ color: "var(--cp-ink-3)", fontSize: 15 }}>⌕</span>
      <SymbolSearch
        value={text}
        onChange={setText}
        onSelect={(symbol) => { setText(""); onSubmit(symbol); }}
        persona={persona}
        topSetups={top}
        anchorToParent
        inputTestId="desk-search"
        testIdPrefix="desk-search"
        placeholder={persona === "investor" ? "Search a company, or ask Nivesh…" : "Search a stock or ask Nivesh…"}
        ariaLabel="Search any NSE stock by symbol, name or ISIN, or ask Nivesh"
        autoFocus={autoFocus}
        maxLength={200}
        inputStyle={{ flex: 1, minWidth: 0, width: "100%", background: "transparent", border: 0, outline: "none", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13 }}
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

/**
 * "Kill switch on" / "Trading halted" from GET /api/risk/status, opening Risk Desk › Controls & profile. Nothing shows
 * while the state is off, loading, failed or unknown (a body without a boolean kill_switch): the view itself says those.
 */
function RiskPill({ onOpen, phone }: { onOpen: () => void; phone?: boolean }) {
  const s = useRiskStatus().data;
  if (!s?.known || (!s.killSwitch && !s.halted)) return null;
  const label = s.killSwitch ? "Kill switch on" : "Trading halted";
  return (
    <button
      type="button"
      data-testid="desk-risk-pill"
      data-control={s.killSwitch ? "kill_switch" : "halted"}
      onClick={onOpen}
      className="cp-pill"
      data-tone="danger"
      title={`${label}: new paper positions are blocked. Open Risk Desk › Policy & runtime.`}
      style={{ flex: "none", cursor: "pointer", alignSelf: phone ? "flex-start" : undefined }}
    >
      <span className="nv-dot" style={{ background: "var(--cp-danger)" }} />
      {label}
    </button>
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

/** A numbered tab, as the design draws it: a pill with the mono number, mint when on. */
function TabChip({ id, label, num, on, onClick }: { id: DeskSection; label: string; num: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      data-testid={`desk-tab-${id}`}
      onClick={onClick}
      className="flex items-center"
      style={{
        flex: "none", gap: 9, padding: "9px 17px", borderRadius: 999, fontSize: 14, fontWeight: 500, whiteSpace: "nowrap", cursor: "pointer",
        fontFamily: "var(--sans)", border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
        background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--mint)" : "var(--cp-ink-2)",
      }}
    >
      <span className="cp-num" style={{ fontSize: 10.5, color: on ? "var(--mint)" : "var(--cp-ink-4)" }}>{num}</span>
      {label}
    </button>
  );
}

/** "My portfolio": the real, broker-read portfolio inside the frame. A button, not a numbered tab. */
function MyPortfolioButton({ on, onClick, small }: { on: boolean; onClick: () => void; small?: boolean }) {
  return (
    <button
      type="button"
      data-testid="desk-my-portfolio"
      aria-pressed={on}
      onClick={onClick}
      title="Your real holdings and F&O positions, read from your brokers (read-only)"
      style={{
        flex: "none", padding: small ? "6px 12px" : "9px 17px", borderRadius: 999, fontSize: small ? 12 : 14, fontWeight: 500, whiteSpace: "nowrap", cursor: "pointer",
        fontFamily: "var(--sans)", border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
        background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--mint)" : "var(--cp-ink-2)",
      }}
    >
      My portfolio
    </button>
  );
}

/** The view switcher under the breadcrumb: pills, the current one filled mint (the design's sub-chips). */
function ViewSwitcher({ tab, view, onPick, bleed, underline }: { tab: DeskSection; view: string | null; onPick: (v: string) => void; bleed?: CSSProperties; underline?: boolean }) {
  const views = SECTION_VIEWS[tab];
  if (!views.length) return null;
  return (
    <div data-testid="desk-views" data-variant={underline ? "sections" : "views"} role="group" aria-label={`${SECTION_LABEL[tab]} ${underline ? "sections" : "views"}`} className="cp-scroll flex overflow-x-auto"
      style={{ gap: underline ? 22 : 8, ...(underline ? { borderBottom: "1px solid var(--cp-line)" } : {}), ...bleed }}>
      {views.map((v) => {
        const on = v.key === view;
        return (
          <button
            key={v.key}
            type="button"
            data-testid={`desk-view-${v.key}`}
            aria-pressed={on}
            onClick={() => onPick(v.key)}
            style={underline ? {
              flex: "none", padding: "8px 0 10px", border: 0, borderBottom: `2px solid ${on ? "var(--mint)" : "transparent"}`, marginBottom: -1, background: "transparent",
              fontSize: 13.5, fontWeight: on ? 600 : 500, whiteSpace: "nowrap", cursor: "pointer", fontFamily: "var(--sans)", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            } : {
              flex: "none", padding: "7px 15px", borderRadius: 999, fontSize: 12.5, fontWeight: 500, whiteSpace: "nowrap", cursor: "pointer", fontFamily: "var(--sans)",
              border: `1px solid ${on ? "var(--mint)" : "var(--line-2)"}`, background: on ? "var(--mint)" : "transparent", color: on ? "var(--bg-0)" : "var(--cp-ink-2)",
            }}
          >
            {v.label}
          </button>
        );
      })}
    </div>
  );
}

/** A Trade Desk section's sub-views: the design's chips, the current one filled mint. */
function SubViewSwitcher({ subs, sub, onPick, bleed }: { subs: readonly { key: string; label: string }[]; sub: string | null; onPick: (s: string) => void; bleed?: CSSProperties }) {
  return (
    <div data-testid="desk-subviews" role="group" aria-label="Sub-views" className="cp-scroll flex overflow-x-auto" style={{ gap: 8, ...bleed }}>
      {subs.map((v) => {
        const on = v.key === sub;
        return (
          <button key={v.key} type="button" data-testid={`desk-sub-${v.key}`} aria-pressed={on} onClick={() => onPick(v.key)}
            style={{
              flex: "none", padding: "6px 14px", borderRadius: 999, fontSize: 12.5, fontWeight: 500, whiteSpace: "nowrap", cursor: "pointer", fontFamily: "var(--sans)",
              border: `1px solid ${on ? "var(--mint)" : "var(--line-2)"}`, background: on ? "var(--mint)" : "transparent", color: on ? "var(--bg-0)" : "var(--cp-ink-2)",
            }}>
            {v.label}
          </button>
        );
      })}
    </div>
  );
}

const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)" };
const lineStyle: CSSProperties = { fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" };

/** Market Overview's one line to Trade Desk: how many paper trades are open (GET /api/desk/paper-trades). */
function OpenTradesLine({ onOpen }: { onOpen: () => void }) {
  const q = usePaperTrades();
  let text: string;
  if (q.isPending) text = "Reading your paper trades";
  else if (q.isError) text = "Your paper trades didn’t load";
  else {
    const n = q.data.trades.filter((t) => t.status === "open").length + q.data.strategyTrades.filter((t) => t.status === "open").length;
    text = n === 0 ? "No open paper trades" : `${n} open paper ${n === 1 ? "trade" : "trades"}`;
  }
  return (
    <p data-testid="desk-open-trades-line" className="m-0" style={lineStyle}>
      {text} · <button type="button" data-testid="desk-open-trades-link" onClick={onOpen} style={linkBtn}>Trade Desk ›</button>
    </p>
  );
}

/** Trade Desk's one line where paper and real are easiest to confuse. */
function PaperRealLine({ onOpen }: { onOpen: () => void }) {
  return (
    <p data-testid="desk-paper-real-line" className="m-0" style={lineStyle}>
      These are paper trades. Your real holdings and F&amp;O positions (read-only): <button type="button" data-testid="desk-paper-real-link" onClick={onOpen} style={linkBtn}>My portfolio</button>
    </p>
  );
}

// ── hosting ──────────────────────────────────────────────────────────────

/** One re-hosted screen: its own error boundary and loading state. `desk-panel-<id>`; the old desk's ids where it had one. */
function Hosted({ id, name, children }: { id: string; name: string; children: ReactNode }) {
  return (
    <div data-testid={`desk-panel-${id}`} className="cp-desk-host flex min-w-0 flex-col">
      <SafeWidget key={id} name={`Trading desk · ${name}`}>
        <Suspense fallback={<LoadingBlock label={`Loading ${name}`} rows={4} />}>{children}</Suspense>
      </SafeWidget>
    </div>
  );
}

/** A titled part of a view, below its main screen (Events calendar, F&O, Chartink sources, live-readiness, audit). */
function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-col" style={{ gap: 14, paddingTop: 18, borderTop: "1px solid var(--cp-line)" }}>
      <h2 className="cp-eyebrow m-0" data-testid={`desk-section-${id}-title`}>{title}</h2>
      <Hosted id={id} name={title}>{children}</Hosted>
    </section>
  );
}

/** Market Overview's "All scanner candidates": the full scanner list, collapsed until opened (?section=scanner). */
function ScannerSection({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <section aria-label="All scanner candidates" className="flex min-w-0 flex-col" style={{ gap: 14, paddingTop: 18, borderTop: "1px solid var(--cp-line)" }}>
      <button
        type="button"
        data-testid="desk-scanner-toggle"
        aria-expanded={open}
        aria-controls="desk-scanner-list"
        onClick={onToggle}
        className="flex items-center self-start"
        style={{ gap: 10, padding: "8px 14px", borderRadius: 999, border: "1px solid var(--line-2)", background: open ? "var(--bg-3)" : "transparent", cursor: "pointer", fontFamily: "var(--sans)", fontSize: 13, fontWeight: 500, color: "var(--cp-ink)" }}
      >
        <span aria-hidden style={{ color: "var(--mint)", fontFamily: "var(--mono)" }}>{open ? "−" : "+"}</span>
        All scanner candidates
      </button>
      {open && (
        <div id="desk-scanner-list">
          <Hosted id="scanner" name="the scanner list"><ScannerTab listOnly /></Hosted>
        </div>
      )}
    </section>
  );
}

/** Questions for the desk's Copilot about what the desk is showing. */
function useDockChips(loc: DeskLocation, symbol: string | null): string[] {
  const q = useDeskScanner();
  const top = q.data?.setups[0]?.symbol;
  const sym = symbol ?? top ?? null;
  return useMemo(() => {
    const out: string[] = [];
    if (loc.tab === "market" && loc.view === "research" && sym) {
      out.push(`Explain the ${sym} setup and what would invalidate it`);
      out.push(`Size a trade in ${sym} with 1% risk`);
    } else if (loc.tab === "market" && loc.view === "smartmoney") {
      out.push("What does NIFTY option OI say about this expiry?");
      out.push("Which F&O stocks show long build-up today?");
    } else if (loc.tab === "portfolio") {
      out.push("What are the key risks in my portfolio this week?");
    } else if (loc.tab === "market" && loc.view === "intel") {
      out.push("Summarise today’s most important filings");
    } else {
      if (top) out.push(`Why does ${top} rank first on the scanner?`);
      out.push("Which sectors are leading today and why?");
    }
    out.push("What are the key market risks this week?");
    return [...new Set(out)];
  }, [loc.tab, loc.view, sym, top]);
}

export default function TradingDeskScreen() {
  const { mobile, wide } = useCopilotShell();
  const [params, setParams] = useSearchParams();
  const search = params.toString();
  const docked = wide;
  const harness = !!StrategyGraphsHarness && params.get("tab") === "more" && params.get("view") === "strategy-graphs";
  // An old desk URL (or a stray view): replaced by its new place before anything mounts.
  const redirect = useMemo(() => (harness ? null : legacyRedirect(new URLSearchParams(search), docked)), [search, docked, harness]);
  const loc = useMemo(() => locationOf(new URLSearchParams(search)), [search]);
  const section = params.get("section");
  const rawSym = (params.get("sym") || "").toUpperCase();
  const symbol = SYM_RE.test(rawSym) ? rawSym : null;
  const persona: DeskPersona = params.get("persona") === "investor" ? "investor" : "trader";
  const dockRef = useRef<CopilotDockHandle>(null);
  const pendingAsk = useRef<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const scan = useDeskScanner();
  const padX = padFor(mobile);

  useLayoutEffect(() => {
    if (redirect) setParams(redirect, { replace: true });
  }, [redirect, setParams]);

  /** Go to a place: the tab, its view (default when left out) and extra params; the old view's params are dropped. */
  const goPlace = useCallback((tab: DeskPlace, view?: string | null, extra?: Record<string, string>) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      for (const k of [...VIEW_PARAMS, "view", "section"]) p.delete(k);
      p.set("tab", tab);
      const v = view === undefined ? defaultView(tab) : view;
      if (v) p.set("view", v);
      const sub = defaultSub(tab, v ?? null);
      if (sub) p.set("sub", sub);
      for (const [k, val] of Object.entries(extra ?? {})) p.set(k, val);
      return canonical(p);
    }, { replace: true });
  }, [setParams]);

  const setParam = useCallback((patch: Record<string, string | null>) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch)) {
        if (v === null) p.delete(k);
        else p.set(k, v);
      }
      return canonical(p);
    }, { replace: true });
  }, [setParams]);

  // Questions go to the desk's own Copilot: the dock when it shows, else the page Copilot (?tab=copilot).
  const askDesk = useCallback((question: string) => {
    if (dockRef.current) {
      dockRef.current.ask(question);
      return;
    }
    pendingAsk.current = question;
    goPlace("copilot");
  }, [goPlace]);

  const pageCopilot = !redirect && loc.tab === "copilot" && !docked;
  // A question asked from another view is sent once the page Copilot is up.
  useEffect(() => {
    if (!pageCopilot || !pendingAsk.current || !dockRef.current) return;
    const q = pendingAsk.current;
    pendingAsk.current = null;
    dockRef.current.ask(q);
  }, [pageCopilot]);

  // Scroll to a part of a view once it has rendered (a lazy screen can take a moment).
  const scrollTimer = useRef<number | null>(null);
  useEffect(() => () => { if (scrollTimer.current) window.clearInterval(scrollTimer.current); }, []);
  const scrollWhenReady = useCallback((selector: string) => {
    if (scrollTimer.current) window.clearInterval(scrollTimer.current);
    let tries = 0;
    scrollTimer.current = window.setInterval(() => {
      const el = document.querySelector(selector);
      tries += 1;
      if (el || tries > 40) {
        if (scrollTimer.current) window.clearInterval(scrollTimer.current);
        scrollTimer.current = null;
        el?.scrollIntoView({ block: "start" });
      }
    }, 150);
  }, []);
  // ?section= opens a part of a view (Market Overview's scanner list, the Events calendar, an F&O section, Chartink).
  useEffect(() => {
    if (redirect || !section) return;
    scrollWhenReady(section === "scanner" ? '[data-testid="desk-scanner-toggle"]' : `[data-testid="desk-panel-${section}"]`);
  }, [redirect, section, loc.tab, loc.view, scrollWhenReady]);

  const goSection = useCallback((tab: DeskPlace, view: string | null, sec: string, extra?: Record<string, string>) => {
    goPlace(tab, view, { section: sec, ...(extra ?? {}) });
  }, [goPlace]);

  const desk = useMemo<DeskState>(() => ({
    tab: oldTabOf(loc),
    openTab: (t) => {
      const pl = placeOfOldTab(t);
      if (pl.section) goSection(pl.tab, pl.view, pl.section);
      else goPlace(pl.tab, pl.view);
    },
    symbol,
    openChart: (s) => goPlace("market", "research", { sym: s.toUpperCase() }),
    setSymbol: (s) => setParam({ sym: s.toUpperCase() }),
    openStrategy: (s, src) => goPlace("trade", "lab", {
      sym: s.toUpperCase(),
      ...(src ? { src_kind: src.kind, ...(src.bucket ? { src_bucket: src.bucket } : {}), ...(src.date ? { src_date: src.date } : {}) } : {}),
    }),
    openStrategyIdeas: (focus) => goPlace("trade", "lab", { mode: "ideas", ...(focus ? { focus: focus.toUpperCase() } : {}) }),
    openStrategyPlan: (p) => goPlace("trade", "lab", { ...p, mode: "stock", build: "1" }),
    openChartink: () => goSection("market", "screener", "chartink"),
    openLab: (view, opts) => {
      const extra = {
        ...(opts?.symbol ? { lab_sym: opts.symbol.toUpperCase() } : {}),
        ...(opts?.focus ? { lab_focus: opts.focus.toUpperCase() } : {}),
      };
      if (view === "strategies") goSection("trade", "lab", "fno", extra);
      else goSection("market", "smartmoney", "fno", { ...(view && view !== "buildup" ? { lab: view } : {}), ...extra });
    },
    openIntel: (opts) => goPlace("market", "intel", {
      ...(opts?.chip && opts.chip !== "all" ? { in_chip: opts.chip } : {}), ...(opts?.event ? { in_ev: opts.event } : {}),
    }),
    openPaperTrades: () => goPlace("trade", "paper"),
    // The breadcrumb is the location now; where a link left from no longer names a crumb.
    noteFrom: () => undefined,
    askDesk,
    docked,
    persona,
    setPersona: (p) => setParam({ persona: p === "investor" ? "investor" : null }),
  }), [loc, symbol, goPlace, goSection, setParam, askDesk, docked, persona]);

  // Search (also the chart workspace's instrument search, PRD §7.2):
  //   a scanner stock (symbol prefix)  → selected; the place stays
  //   any other one-word symbol        → opened in Market Desk › Stock Research (?sym=), which loads any NSE symbol
  //   anything else (words, questions) → asked to the desk's Copilot
  const onSearch = (text: string) => {
    const t = text.trim();
    const sym = matchSetup(scan.data?.setups ?? [], t);
    if (sym) {
      desk.setSymbol(sym);
      setPicked(sym);
    } else if (SYMBOL_TOKEN.test(t)) {
      setPicked(null);
      if (loc.tab === "market" && loc.view === "research") desk.setSymbol(t);
      else desk.openChart(t);
    } else {
      setPicked(null);
      askDesk(t);
    }
  };

  const chips = useDockChips(loc, symbol);
  const bleed = { margin: `0 -${padX}px`, padding: `0 ${padX}px` };
  const openPortfolio = () => goPlace("portfolio");
  const openRisk = () => goPlace("risk", "controls");
  const pickTab = (t: DeskSection) => goPlace(t);
  const crumbs = crumbsOf(loc);
  const trailBar = (
    <DeskTrail
      tab={crumbs.tab}
      view={crumbs.view}
      sub={crumbs.sub}
      onRoot={() => goPlace("overview")}
      onTab={() => goPlace(loc.tab)}
      onView={() => goPlace(loc.tab, loc.view)}
    />
  );

  // ── the place's content ──
  let content: ReactNode;
  if (redirect) {
    content = <LoadingBlock label="Opening the desk" rows={2} />;
  } else if (harness && StrategyGraphsHarness) {
    content = (
      <div data-testid="desk-panel-strategy-graphs" className="flex min-w-0 flex-col">
        <Suspense fallback={<LoadingBlock label="Loading" rows={4} />}><StrategyGraphsHarness /></Suspense>
      </div>
    );
  } else if (loc.tab === "overview") {
    const scannerOpen = section === "scanner";
    content = (
      <>
        <OpenTradesLine onOpen={() => goPlace("trade", "paper")} />
        <Hosted id="overview-market" name="Market Overview"><OverviewTab marketOnly /></Hosted>
        <Hosted id="pulse" name="the market pulse"><ScannerPulse /></Hosted>
        <Hosted id="top10" name="the Top 10 ideas"><ScannerTop10 /></Hosted>
        <ScannerSection open={scannerOpen} onToggle={() => setParam({ section: scannerOpen ? null : "scanner" })} />
      </>
    );
  } else if (loc.tab === "trade") {
    // The owner's workbench (PLAN.md "1-REVISED"): five sections with sub-views. Paper Trading and Strategy Lab are
    // tabs/trade-desk; Watchlists the Watchlist page; AI Scanner and Chart Analysis host today's scanner list, Chartink
    // sources and chart until step 3 PR B builds them.
    switch (loc.view) {
      case "scanner":
        content = loc.sub === "library"
          ? <Hosted id="chartink" name="Chartink sources"><ChartinkSettings asSection /></Hosted>
          : loc.sub === "scorecard"
            ? (
              <>
                <p data-testid="desk-trade-scorecard-pending" className="m-0" style={lineStyle}>The ideas' scorecard (GET /api/desk/idea-scorecard) is built in the next step of the redesign; the AI ideas are ranked, not predicted.</p>
                <Hosted id="forward-test" name="the F&O forward test"><ForwardTestPanel /></Hosted>
              </>
            )
            : <Hosted id="scanner" name="the scanner list"><ScannerTab listOnly /></Hosted>;
        break;
      case "chart":
        content = loc.sub === "record"
          ? <p data-testid="desk-trade-record-pending" className="m-0" style={lineStyle}>Signal record: not available yet. It needs a route that serves a signal's revisions (positional_signals_history); it is built in the next step.</p>
          : <Hosted id="chart" name="Chart Analysis"><ChartTab /></Hosted>;
        break;
      case "watchlists":
        content = <Hosted id="watchlists" name="Watchlists"><Watchlist /></Hosted>;
        break;
      default:
        content = (
          <>
            <PaperRealLine onOpen={openPortfolio} />
            <Hosted id="trade-desk" name="Trade Desk">
              <TradeDeskTab section={loc.view === "lab" ? "lab" : "paper"} sub={loc.sub ?? null} onSub={(sb, extra) => goPlace("trade", loc.view, { sub: sb, ...(extra ?? {}) })} />
            </Hosted>
          </>
        );
    }
  } else if (loc.tab === "market") {
    switch (loc.view) {
      case "smartmoney":
        content = (
          <>
            <Hosted id="smartmoney" name="Smart Money"><SmartMoneyTab /></Hosted>
            <Section id="fno" title="F&O · build-up, candidates, indices and option chain"><FnoTab views={SMART_MONEY_LAB} asSection /></Section>
          </>
        );
        break;
      case "sectors":
        content = <Hosted id="sectors" name="Sector Rotation"><SectorHeatmap /></Hosted>;
        break;
      case "research":
        content = <Hosted id="chart" name="Stock Research"><ChartTab /></Hosted>;
        break;
      case "screener":
        content = (
          <>
            <Hosted id="screener" name="the Screener"><Screener /></Hosted>
            <Section id="chartink" title="Chartink sources"><ChartinkSettings asSection /></Section>
          </>
        );
        break;
      default:
        content = (
          <>
            <Hosted id="intel" name="Market Intelligence"><IntelTab /></Hosted>
            <Section id="events" title="Events calendar"><EventsTab /></Section>
          </>
        );
    }
  } else if (loc.tab === "risk") {
    content = <Hosted id="riskdesk" name="the Risk Desk"><RiskDeskTab view={loc.view} /></Hosted>;
  } else if (loc.tab === "portfolio") {
    content = (
      <SafeWidget key="portfolio" name="Trading desk · My portfolio">
        <Suspense fallback={<LoadingBlock label="Loading your portfolio" rows={4} />}><PortfolioTab withPaper={false} /></Suspense>
      </SafeWidget>
    );
  } else {
    content = <CopilotDock ref={dockRef} chips={chips} height="calc(100dvh - 250px)" variant="page" />;
  }

  const panelTab = harness ? "more" : loc.tab;
  const panel = (
    <div
      data-testid={`desk-panel-${panelTab}`}
      data-view={loc.view ?? ""}
      role="tabpanel"
      aria-label={[crumbs.tab, crumbs.view, crumbs.sub].filter(Boolean).join(" · ")}
      className="flex min-w-0 flex-col"
      style={{ gap: mobile ? 14 : 20 }}
    >
      {content}
    </div>
  );

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

  const tab4 = isSection(loc.tab) ? loc.tab : null;
  const subs = tab4 && !redirect ? subViewsOf(tab4, loc.view) : [];
  const views = tab4 && !redirect ? (
    <>
      <ViewSwitcher tab={tab4} view={loc.view} onPick={(v) => goPlace(tab4, v)} bleed={mobile ? { ...bleed, paddingBottom: 2 } : undefined} underline={tab4 === "trade"} />
      {subs.length > 0 && <SubViewSwitcher subs={subs} sub={loc.sub ?? null} onPick={(sb) => goPlace(tab4, loc.view, { sub: sb })} bleed={mobile ? { ...bleed, paddingBottom: 2 } : undefined} />}
    </>
  ) : null;
  const rootAttrs = {
    "data-testid": "screen-trading-desk",
    "data-tab": panelTab,
    "data-view": loc.view ?? "",
    "data-sub": loc.sub ?? "",
    "data-symbol": symbol ?? "",
    "data-persona": persona,
  };

  if (mobile) {
    const bottomKey: BottomKey = tab4 ?? (loc.tab === "copilot" ? "copilot" : "overview");
    // Room under the content for the fixed bottom bar; the phone Copilot's ask box sits above it (CopilotDock).
    const phoneStyle = { paddingBottom: BOTTOM_BAR_SPACE, ["--desk-bottom-bar" as string]: BOTTOM_BAR_SPACE } as CSSProperties;
    return (
      <DeskProvider value={desk}>
        <div {...rootAttrs} className="flex min-w-0 flex-col" style={phoneStyle}>
          <PaperBanner padX={padX} mobile />
          <header data-testid="desk-mobile-header" className="flex flex-col" style={{ gap: 10, paddingTop: 12, paddingBottom: 12 }}>
            <div className="flex items-center" style={{ gap: 8 }}>
              <span className="nv-mark" aria-hidden style={{ flex: "none", width: 30, height: 30, fontSize: 18 }}>न</span>
              <span className="flex min-w-0 flex-col" style={{ gap: 3, overflow: "hidden" }}>
                <span style={{ fontFamily: "var(--display)", fontSize: 19, lineHeight: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Nivesh Copilot</span>
                <span className="cp-num" style={{ fontSize: 8.5, letterSpacing: "0.14em", color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>AI SMART TRADING DESK</span>
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
              <MyPortfolioButton small on={loc.tab === "portfolio"} onClick={openPortfolio} />
            </div>
            <RiskPill phone onOpen={openRisk} />
            {searchOpen && <SearchBox column onSubmit={onSearch} autoFocus persona={persona} setups={scan.data?.setups ?? []} />}
            {picked && <Picked symbol={picked} onChart={() => desk.openChart(picked)} />}
          </header>

          <div className="flex min-w-0 flex-col" style={{ gap: 10, paddingBottom: 14 }}>
            {trailBar}
            {views}
          </div>
          <div style={{ paddingBottom: 18 }}>{panel}</div>
          {!pageCopilot && footer}
          <DeskBottomBar active={bottomKey} onPick={(k) => (k === "copilot" ? goPlace("copilot") : pickTab(k))} />
        </div>
      </DeskProvider>
    );
  }

  return (
    <DeskProvider value={desk}>
      <div {...rootAttrs} className="mx-auto flex min-w-0 flex-col" style={{ maxWidth: docked ? 1480 : 1180 }}>
        <PaperBanner padX={padX} mobile={false} />
        <div data-testid="desk-topbar" className="flex flex-wrap items-center" style={{ minHeight: 60, gap: "10px 14px", ...bleed, paddingTop: 12, paddingBottom: 4 }}>
          <span className="cp-eyebrow" style={{ whiteSpace: "nowrap" }}>AI Smart Trading Desk · Trader mode</span>
          {picked && <Picked symbol={picked} onChart={() => desk.openChart(picked)} />}
          <span style={{ flex: "1 1 0", minWidth: 0 }} />
          <SearchBox onSubmit={onSearch} persona={persona} setups={scan.data?.setups ?? []} />
          <PersonaSwitch persona={persona} onPick={desk.setPersona} />
          <RiskPill onOpen={openRisk} />
          <StatusPill />
          {docked ? (
            <button type="button" data-testid="desk-docked-note" onClick={() => dockRef.current?.focus()} className="cp-pill" data-tone="mint" style={{ flex: "none", cursor: "pointer", background: "var(--mint-soft)" }}>
              Copilot docked right
            </button>
          ) : (
            <button
              type="button"
              data-testid="desk-copilot-button"
              aria-pressed={loc.tab === "copilot"}
              onClick={() => goPlace("copilot")}
              className="cp-pill"
              data-tone="mint"
              style={{ flex: "none", cursor: "pointer", background: loc.tab === "copilot" ? "var(--mint-soft)" : "transparent" }}
            >
              Copilot
            </button>
          )}
        </div>

        <div className="flex items-center" style={{ gap: 10, ...bleed, paddingTop: 12, paddingBottom: 16, borderBottom: "1px solid var(--cp-line)" }}>
          <div data-testid="desk-tabs" role="tablist" aria-label="Desk tabs" className="cp-scroll flex min-w-0 overflow-x-auto" style={{ flex: "0 1 auto", gap: 10 }}>
            {DESK_SECTIONS.map((t, i) => (
              <TabChip key={t} id={t} num={String(i + 1).padStart(2, "0")} label={SECTION_LABEL[t]} on={!redirect && loc.tab === t} onClick={() => pickTab(t)} />
            ))}
          </div>
          <span style={{ flex: 1 }} />
          <MyPortfolioButton on={loc.tab === "portfolio"} onClick={openPortfolio} />
        </div>

        <div
          className="grid"
          style={{
            gridTemplateColumns: docked ? "minmax(0,1fr) 384px" : "minmax(0,1fr)",
            gap: 20,
            alignItems: "start",
            padding: "20px 0 28px",
            minHeight: docked ? 900 : undefined,
          }}
        >
          <div className="flex min-w-0 flex-col" style={{ gap: 16 }}>
            {trailBar}
            {views}
            {panel}
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
