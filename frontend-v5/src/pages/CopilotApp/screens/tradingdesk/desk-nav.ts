/**
 * Smart trading desk — where things are (the owner's redesign of 2026-10-27, docs/desk_redesign_20261027/PLAN.md).
 * Pure URL logic: TradingDesk.tsx draws it, and the redirects and the breadcrumb come from here.
 *
 *   /app/trader/desk?tab=<tab>&view=<view>[&sub=<sub-view>]
 *
 *   01 Market Overview   tab=overview     one page (no views)
 *   02 Trade Desk        tab=trade        the owner's workbench (PLAN.md "1-REVISED", 27 Oct 19:40): four sections, each with
 *                                         its sub-views (sub=):
 *                                           scanner     AI Scanner      ranked · library · scorecard
 *                                           chart       Chart Analysis  live · record
 *                                           paper       Paper Trading   the owner's six views (5 Nov, "completely replace the current
 *                                                                         paper trading dashboard"; docs/scanner_paper_trading/
 *                                                                         UI_DESIGN_V2.md §1): 01 overview · 02 opportunities ·
 *                                                                         03 allocation · 04 risk · 05 pnl · 06 analytics. The old
 *                                                                         keys redirect: live, journal → pnl; settings → allocation
 *                                           watchlists  Watchlists      (one page)
 *                                         Strategy Lab was removed (owner, 29 Oct: "remove strategy lab completely"); trades
 *                                         are built on the chart's paper basket now, so every lab URL opens Chart Analysis ›
 *                                         Live chart with its sym and tp (LAB_TO_CHART). The old Trade Desk views land in their
 *                                         sections: view=open / paper → paper live, closed → paper journal, new → the chart;
 *                                         Market Desk's watchlists → here.
 *   03 Market Desk       tab=market       intel · smartmoney · sectors · research · screener (sub=: screens · dashboard · builder;
 *                                         the last two flagged: Scan dashboard, Scan builder; docs/scan_builder/DESIGN.md §7) ·
 *                                         recovery (Market Recovery, owner 3 Nov; flagged market_recovery; docs/market_recovery/DESIGN.md)
 *                                         (watchlists and scorecard were Market Desk views until the owner's 19:40 IST
 *                                         correction of 27 Oct; their URLs open Trade Desk, MOVED_TO_TRADE)
 *   04 Risk Desk         tab=risk         limits · controls · log · hedge (flagged: Portfolio hedge, last). The Scanner-to-Paper
 *                                         Trading views that were here for a day (overview · allocation · portfolio) moved into
 *                                         Paper Trading v2 (owner, 5 Nov): their URLs open Trade Desk › Paper Trading ›
 *                                         overview · allocation · risk (RISK_TO_PAPER)
 *   My portfolio         tab=portfolio    the header button, not a numbered tab (the real, broker-read portfolio)
 *   AI Copilot           tab=copilot      the Copilot full height, where it is not docked (under 1400px)
 *
 * Trade Desk goes three deep (tab → section → sub-view), and Market Desk › Screener (its scan sub-views); every other view two. `section=` names a part of a view to open and scroll to (Market Overview's collapsed
 * "All scanner candidates", the Events calendar under Market Intelligence, the F&O sections, Chartink sources).
 *
 * Every URL of the old desk (Overview · AI Scanner · Market Intelligence · Chart Analysis · Portfolio & Risk · Smart
 * Money · More) maps to its new place (legacyRedirect), keeping the params the hosted screens read (sym, lab, in_chip,
 * the Strategy Builder's inputs, the scanner's sc_*).
 */

export const DESK_SECTIONS = ["overview", "trade", "market", "risk"] as const;
export type DeskSection = (typeof DESK_SECTIONS)[number];
/** Every `tab=` the desk shows: the four numbered tabs, My portfolio and the page Copilot. */
export type DeskPlace = DeskSection | "portfolio" | "copilot";

export const SECTION_LABEL: Record<DeskSection, string> = {
  overview: "Market Overview",
  trade: "Trade Desk",
  market: "Market Desk",
  risk: "Risk Desk",
};
export const PLACE_LABEL: Record<DeskPlace, string> = { ...SECTION_LABEL, portfolio: "My portfolio", copilot: "AI Copilot" };

/** Short names for the phone's bottom bar. */
export const SECTION_SHORT: Record<DeskSection, string> = { overview: "Overview", trade: "Trade", market: "Market", risk: "Risk" };

export interface DeskViewDef {
  key: string;
  label: string;
  /** The design's small mono number before the label ("01"…"06"), where the design numbers its menu (Paper Trading v2). */
  num?: string;
  /** A shorter chip label for a phone, where the chip row overflows at 390 px (UI_DESIGN_V2.md §1: 06 → "Analytics"). */
  short?: string;
}

/** Each tab's views, the default first. A tab with none is one page. */
export const SECTION_VIEWS: Record<DeskSection, readonly DeskViewDef[]> = {
  overview: [],
  trade: [
    { key: "scanner", label: "AI Scanner" },
    { key: "chart", label: "Chart Analysis" },
    { key: "paper", label: "Paper Trading" },
    { key: "watchlists", label: "Watchlists" },
  ],
  market: [
    { key: "intel", label: "Market Intelligence" },
    { key: "smartmoney", label: "Smart Money" },
    { key: "sectors", label: "Sector Rotation" },
    { key: "research", label: "Stock Research" },
    { key: "screener", label: "Screener" },
    // Market Recovery (owner, 3 Nov: the recovery radar under Market Desk; docs/market_recovery/DESIGN.md). Listed last so the
    // other views keep their places; the switcher shows it only with the `market_recovery` flag (FLAGGED_VIEWS).
    { key: "recovery", label: "Market Recovery" },
  ],
  risk: [
    { key: "limits", label: "Exposure & limits" },
    { key: "controls", label: "Policy & runtime" },
    { key: "log", label: "Decision log" },
    // The Scanner-to-Paper Trading views (Trading overview, Capital allocation, Portfolio risk) moved to Trade Desk › Paper
    // Trading v2 (owner, 5 Nov 2026; UI_DESIGN_V2.md §1). Their old URLs redirect there (RISK_TO_PAPER).
    // Quick Hedge (docs/RISK_AND_HEDGE_GAP_AND_PLAN_20261031.md). Listed last; the switcher shows it only when the
    // `portfolio_hedge` flag is on for the account (TradingDesk.tsx ViewSwitcher, HIDDEN_VIEWS).
    { key: "hedge", label: "Portfolio hedge" },
  ],
};

/** Views that exist but are shown in the switcher only when the account has the named feature flag. */
export const FLAGGED_VIEWS: Readonly<Record<string, string>> = { "risk/hedge": "portfolio_hedge", "market/recovery": "market_recovery" };

/** Sub-views ("<tab>/<view>/<sub>") shown in the sub-view switcher only when the account has the named feature flag. The
 *  owner's Chartink-style scans live under the existing Screener (3 Nov): Scan dashboard and Scan builder (DESIGN.md §7). */
export const FLAGGED_SUBS: Readonly<Record<string, string>> = {
  "market/screener/dashboard": "scan_builder",
  "market/screener/builder": "scan_builder",
};

/** The sub-views of a view ("<tab>/<view>"), the default first. A view with none is one page. */
export const SUB_VIEWS: Record<string, readonly DeskViewDef[]> = {
  "trade/scanner": [{ key: "ranked", label: "Ranked candidates" }, { key: "library", label: "Signal library & sources" }, { key: "scorecard", label: "Scorecard" }],
  "trade/chart": [{ key: "live", label: "Live chart" }, { key: "record", label: "Signal record" }],
  // Paper Trading v2 — the owner's six views, in his order, with his labels and numbers (5 Nov 2026: "We need to completely
  // replace the current paper trading dashboard"; docs/scanner_paper_trading/UI_DESIGN_V2.md §1). `pnl` keeps the old P&L
  // dashboard links working; the old keys redirect (PAPER_OLD_SUBS).
  "trade/paper": [
    { key: "overview", label: "Overview", num: "01" }, { key: "opportunities", label: "Scanner opportunities", num: "02" },
    { key: "allocation", label: "Capital allocation", num: "03" }, { key: "risk", label: "Portfolio risk", num: "04" },
    { key: "pnl", label: "Real-time P&L", num: "05" }, { key: "analytics", label: "Strategy analytics", num: "06", short: "Analytics" },
  ],
  // Market Desk › Screener: the screener as it was, then the Chartink-style scans on our own data (owner, 3 Nov)
  "market/screener": [{ key: "screens", label: "Screener" }, { key: "dashboard", label: "Scan dashboard" }, { key: "builder", label: "Scan builder" }],
};

/** A tab whose default view is not its first (the design's order is kept in SECTION_VIEWS). None today: Trade Desk opens
 *  its first section, AI Scanner › Ranked candidates (step 3, PR B). */
const DEFAULT_VIEW: Partial<Record<DeskSection, string>> = {};

export const subViewsOf = (tab: DeskPlace, view: string | null): readonly DeskViewDef[] => (view ? SUB_VIEWS[`${tab}/${view}`] ?? [] : []);
export const defaultSub = (tab: DeskPlace, view: string | null): string | null => subViewsOf(tab, view)[0]?.key ?? null;

export interface DeskLocation { tab: DeskPlace; view: string | null; sub?: string | null }

const PLACES: readonly string[] = [...DESK_SECTIONS, "portfolio", "copilot"];
export const isSection = (v: string | null | undefined): v is DeskSection => !!v && (DESK_SECTIONS as readonly string[]).includes(v);
const isPlace = (v: string | null | undefined): v is DeskPlace => !!v && PLACES.includes(v);

export function defaultView(tab: DeskPlace): string | null {
  return isSection(tab) ? DEFAULT_VIEW[tab] ?? SECTION_VIEWS[tab][0]?.key ?? null : null;
}

/** The location a (new-style) URL shows; an unknown view falls back to the tab's default. */
export function locationOf(params: URLSearchParams): DeskLocation {
  const raw = params.get("tab");
  const tab: DeskPlace = isPlace(raw) ? raw : "overview";
  if (!isSection(tab)) return { tab, view: null, sub: null };
  const views = SECTION_VIEWS[tab];
  if (!views.length) return { tab, view: null, sub: null };
  const v = params.get("view");
  const view = views.some((x) => x.key === v) ? (v as string) : (defaultView(tab) as string);
  const subs = subViewsOf(tab, view);
  const s = params.get("sub");
  return { tab, view, sub: subs.length ? (subs.some((x) => x.key === s) ? s : subs[0].key) : null };
}

export function viewLabel(loc: DeskLocation): string | null {
  if (!isSection(loc.tab) || !loc.view) return null;
  return SECTION_VIEWS[loc.tab].find((v) => v.key === loc.view)?.label ?? null;
}

export function subLabel(loc: DeskLocation): string | null {
  return loc.sub ? subViewsOf(loc.tab, loc.view).find((x) => x.key === loc.sub)?.label ?? null : null;
}

/** The breadcrumb: the location to the sub-view ("Trading desk › Trade Desk › Paper Trading › Live desk"), never the
 *  click path. */
export function crumbsOf(loc: DeskLocation): { tab: string; view: string | null; sub: string | null } {
  const view = viewLabel(loc);
  const sub = subLabel(loc);
  // A sub-view named like its view (Market Desk › Screener › Screener) adds nothing to the trail.
  return { tab: PLACE_LABEL[loc.tab], view, sub: sub && sub !== view ? sub : null };
}

/** Params the old desk kept for one tab's view; a tab change drops them (with `view` and `section`). */
export const VIEW_PARAMS = [
  // the Strategy Builder (tradingdesk/strategy)
  "direction", "instrument", "horizon", "build", "plan", "src_kind", "src_bucket", "src_date", "cand", "mode", "focus", "capital", "risk_inr",
  "risk_pct", "max_alloc", "min_rr", "horizon_days", "avoid_events", "multi_leg", "expiry",
  // the F&O lab (FnoTab.tsx) and Market Intelligence (IntelTab.tsx)
  "lab", "lab_sym", "lab_focus", "in_chip", "in_ev",
  // Trade Desk: the sub-view, the chart's plan (?tp=) and the journal's trade (Paper Trading)
  "sub", "tp", "trade",
  // Market Desk › Screener › Scan builder: the open saved scan; › Scan dashboard: the open dashboard tab (absent = Atlas fresh)
  "scan", "dash",
];

/** The Strategy Lab's own params (its wizard, the Strategy Builder, the F&O lab's hand-off), dropped when a lab URL opens the chart. */
const LAB_ONLY_PARAMS = [
  "direction", "instrument", "horizon", "build", "plan", "src_kind", "src_bucket", "src_date", "cand", "mode", "focus", "capital", "risk_inr",
  "risk_pct", "max_alloc", "min_rr", "horizon_days", "avoid_events", "multi_leg", "expiry", "lab", "lab_sym", "lab_focus", "underlying",
];

/** The place first (tab, view, section), then the hosted screens' own params in their order: a readable URL. */
export function canonical(params: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  const first = ["tab", "view", "sub", "section"];
  for (const k of first) {
    const v = params.get(k);
    if (v !== null) out.set(k, v);
  }
  params.forEach((v, k) => { if (!first.includes(k)) out.append(k, v); });
  return out;
}

/**
 * Market Desk views that moved to Trade Desk (Watchlists; AI Scanner › Scorecard). `?tab=market&view=<one>` opens Trade
 * Desk's default view until the Trade Desk tab gives them their own places.
 */
export const MOVED_TO_TRADE: ReadonlySet<string> = new Set(["watchlists", "scorecard"]);

/** Paper Trading's sub-views before v2 (owner, 5 Nov 2026) and the v2 view each now opens (UI_DESIGN_V2.md §1). */
export const PAPER_OLD_SUBS: Readonly<Record<string, string>> = { live: "pnl", journal: "pnl", settings: "allocation" };

/** The Risk Desk's Scanner-to-Paper Trading views (one day, 5 Nov) and the Paper Trading v2 sub-view each now opens. */
export const RISK_TO_PAPER: Readonly<Record<string, string>> = { overview: "overview", allocation: "allocation", portfolio: "risk" };

/** The old desk's tabs and More views (before 2026-10-27). */
const OLD_TABS = new Set(["scanner", "intel", "events", "chart", "smartmoney", "fno", "more"]);

/**
 * The new URL for an old desk URL, or null when the URL is already a new one (TradingDesk.tsx leaves the strategy-graphs
 * test harness alone before asking). The params the
 * hosted screens read are kept. `docked`: the Copilot is docked beside the desk (1400px and wider), so the old
 * More · AI Copilot page has no use there and More opens Market Overview.
 */
export function legacyRedirect(params: URLSearchParams, docked: boolean): URLSearchParams | null {
  const tab = params.get("tab");
  const p = new URLSearchParams(params);
  const set = (t: DeskPlace, view: string | null, section?: string, sub?: string) => {
    p.set("tab", t);
    if (view) p.set("view", view);
    else p.delete("view");
    const s = sub ?? (p.get("sub") && subViewsOf(t, view).some((x) => x.key === p.get("sub")) ? p.get("sub") : defaultSub(t, view));
    if (s) p.set("sub", s);
    else p.delete("sub");
    if (section) p.set("section", section);
    return canonical(p);
  };
  // Strategy Lab is gone (owner, 29 Oct): its URLs open the chart, keeping the stock and the plan.
  const toChart = () => {
    const sym = params.get("sym") ?? params.get("lab_sym") ?? params.get("focus") ?? params.get("underlying");
    for (const k of [...LAB_ONLY_PARAMS, "section", "view", "sub"]) p.delete(k);
    if (sym) p.set("sym", sym.toUpperCase());
    return set("trade", "chart", undefined, "live");
  };
  if (tab === "copilot" && docked) {
    p.delete("view");
    return set("overview", null);
  }
  if (tab !== null && !isPlace(tab) && !OLD_TABS.has(tab)) {
    // An unknown tab: Market Overview, as the old desk did.
    for (const k of ["view", "section"]) p.delete(k);
    return set("overview", null);
  }
  if (tab === null) return null; // the bare desk URL is Market Overview
  if (tab === "overview" && params.get("section") === "scanner") {
    // Market Overview's collapsed "All scanner candidates" moved to Trade Desk › AI Scanner › Ranked candidates (PR B).
    p.delete("section");
    return set("trade", "scanner", undefined, "ranked");
  }
  if (tab === "trade") {
    // Trade Desk's views before the owner's workbench structure (step 3, first cut): their new sections.
    const old = params.get("view");
    if (old === "lab" || old === "new") return toChart();
    // Live desk and Trade journal became Real-time P&L (Paper Trading v2, owner 5 Nov).
    if (old === "open" || old === "closed") return set("trade", "paper", undefined, "pnl");
    // Paper Trading's pre-v2 sub-views: their v2 places (live, journal → pnl; settings → allocation), keeping ?trade=.
    const oldSub = params.get("sub");
    if (old === "paper" && oldSub && Object.hasOwn(PAPER_OLD_SUBS, oldSub)) return set("trade", "paper", undefined, PAPER_OLD_SUBS[oldSub]);
  }
  if (tab === "risk" && Object.hasOwn(RISK_TO_PAPER, params.get("view") ?? "")) {
    // The Risk Desk's Scanner-to-Paper Trading views moved into Paper Trading v2 (owner, 5 Nov): overview · allocation · risk.
    const sub = RISK_TO_PAPER[params.get("view") as string];
    p.delete("sub");
    return set("trade", "paper", undefined, sub);
  }
  if (tab === "market" && params.get("view") === "screener" && params.get("section") === "chartink") {
    // Chartink sources moved from Market Desk › Screener to Trade Desk › AI Scanner › Signal library & sources (owner's design).
    return set("trade", "scanner", "chartink", "library");
  }
  if (tab === "market" && params.get("view") === "scanbuilder") {
    // The Scan Builder was its own Market Desk view for a day; it lives under the Screener now (owner, 3 Nov), keeping ?scan=.
    return set("market", "screener", undefined, "builder");
  }
  if (tab === "market" && MOVED_TO_TRADE.has(params.get("view") ?? "")) {
    // Watchlists and the Idea scorecard belong to Trade Desk (the owner's design; 27 Oct 19:40 IST).
    return params.get("view") === "scorecard" ? set("trade", "scanner", undefined, "scorecard") : set("trade", "watchlists");
  }
  if (isPlace(tab)) {
    // A new URL. A missing or unknown view becomes the tab's default, a missing or unknown sub-view the view's; a view
    // on a tab without views, or a sub-view on a view without them, is dropped.
    const loc = locationOf(params);
    return loc.view === params.get("view") && (loc.sub ?? null) === params.get("sub") ? null : set(loc.tab, loc.view, undefined, loc.sub ?? undefined);
  }
  switch (tab) {
    case "scanner": return set("trade", "scanner", undefined, "ranked");
    case "intel": return set("market", "intel");
    case "events": return set("market", "intel", "events");
    case "chart": return set("trade", "chart", undefined, "live");
    case "smartmoney": return set("market", "smartmoney");
    case "fno":
      if (params.get("lab") === "strategies") return toChart();
      return set("market", "smartmoney", "fno");
    case "more": {
      const view = params.get("view");
      if (view === "strategy") return toChart();
      if (view === "risk") return set("risk", "limits");
      if (view === "chartink") return set("trade", "scanner", "chartink", "library");
      p.delete("view");
      return docked ? set("overview", null) : set("copilot", null);
    }
    default: return null;
  }
}

/** The view an old tab name opens now (DeskState.openTab keeps its old names for the hosted screens). */
export function placeOfOldTab(old: string): { tab: DeskPlace; view: string | null; section?: string } {
  switch (old) {
    case "overview": return { tab: "overview", view: null };
    case "scanner": return { tab: "trade", view: "scanner" };
    case "intel": return { tab: "market", view: "intel" };
    case "events": return { tab: "market", view: "intel", section: "events" };
    case "chart": return { tab: "trade", view: "chart" };
    case "smartmoney": return { tab: "market", view: "smartmoney" };
    case "fno": return { tab: "market", view: "smartmoney", section: "fno" };
    case "portfolio": return { tab: "portfolio", view: null };
    default: return { tab: "overview", view: null };
  }
}

/** Trader mode: the rail's old tools open their Market Desk views (the owner's decision of 2026-10-27, 16:30). */
export const TRADER_TOOL_TO_DESK: Record<string, string> = {
  "tool/screener": "trader/desk?tab=market&view=screener",
  "tool/sector-heatmap": "trader/desk?tab=market&view=sectors",
  "tool/research": "trader/desk?tab=market&view=research",
};
