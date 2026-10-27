/**
 * Smart trading desk — where things are (the owner's redesign of 2026-10-27, docs/desk_redesign_20261027/PLAN.md).
 * Pure URL logic: TradingDesk.tsx draws it, and the redirects and the breadcrumb come from here.
 *
 *   /app/trader/desk?tab=<tab>&view=<view>
 *
 *   01 Market Overview   tab=overview     one page (no views)
 *   02 Trade Desk        tab=trade        open (Open & pending) · closed (Closed & journal) · new (New trade); the old
 *                                         view=paper lands on open (tabs/trade-desk/TradeDeskTab.tsx)
 *   03 Market Desk       tab=market       intel · smartmoney · sectors · research · screener · watchlists
 *   04 Risk Desk         tab=risk         limits · controls · log
 *   My portfolio         tab=portfolio    the header button, not a numbered tab (the real, broker-read portfolio)
 *   AI Copilot           tab=copilot      the Copilot full height, where it is not docked (under 1400px)
 *
 * At most two levels: tab → view. `section=` names a part of a view to open and scroll to (Market Overview's collapsed
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

export interface DeskViewDef { key: string; label: string }

/** Each tab's views, the default first. A tab with none is one page. */
export const SECTION_VIEWS: Record<DeskSection, readonly DeskViewDef[]> = {
  overview: [],
  trade: [
    { key: "open", label: "Open & pending" },
    { key: "closed", label: "Closed & journal" },
    { key: "new", label: "New trade" },
  ],
  market: [
    { key: "intel", label: "Market Intelligence" },
    { key: "smartmoney", label: "Smart Money" },
    { key: "sectors", label: "Sector Rotation" },
    { key: "research", label: "Stock Research" },
    { key: "screener", label: "Screener" },
    { key: "watchlists", label: "Watchlists & alerts" },
  ],
  risk: [
    { key: "limits", label: "Exposure & limits" },
    { key: "controls", label: "Policy & runtime" },
    { key: "log", label: "Decision log" },
  ],
};

export interface DeskLocation { tab: DeskPlace; view: string | null }

const PLACES: readonly string[] = [...DESK_SECTIONS, "portfolio", "copilot"];
export const isSection = (v: string | null | undefined): v is DeskSection => !!v && (DESK_SECTIONS as readonly string[]).includes(v);
const isPlace = (v: string | null | undefined): v is DeskPlace => !!v && PLACES.includes(v);

export function defaultView(tab: DeskPlace): string | null {
  return isSection(tab) ? SECTION_VIEWS[tab][0]?.key ?? null : null;
}

/** The location a (new-style) URL shows; an unknown view falls back to the tab's default. */
export function locationOf(params: URLSearchParams): DeskLocation {
  const raw = params.get("tab");
  const tab: DeskPlace = isPlace(raw) ? raw : "overview";
  if (!isSection(tab)) return { tab, view: null };
  const views = SECTION_VIEWS[tab];
  if (!views.length) return { tab, view: null };
  const v = params.get("view");
  return { tab, view: views.some((x) => x.key === v) ? v : views[0].key };
}

export function viewLabel(loc: DeskLocation): string | null {
  if (!isSection(loc.tab) || !loc.view) return null;
  return SECTION_VIEWS[loc.tab].find((v) => v.key === loc.view)?.label ?? null;
}

/** The breadcrumb: the location, never the click path. */
export function crumbsOf(loc: DeskLocation): { tab: string; view: string | null } {
  return { tab: PLACE_LABEL[loc.tab], view: viewLabel(loc) };
}

/** Params the old desk kept for one tab's view; a tab change drops them (with `view` and `section`). */
export const VIEW_PARAMS = [
  // the Strategy Builder (tradingdesk/strategy)
  "direction", "instrument", "horizon", "build", "plan", "src_kind", "src_bucket", "src_date", "cand", "mode", "focus", "capital", "risk_inr",
  "risk_pct", "max_alloc", "min_rr", "horizon_days", "avoid_events", "multi_leg", "expiry",
  // the F&O lab (FnoTab.tsx) and Market Intelligence (IntelTab.tsx)
  "lab", "lab_sym", "lab_focus", "in_chip", "in_ev",
];

/** The place first (tab, view, section), then the hosted screens' own params in their order: a readable URL. */
export function canonical(params: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  for (const k of ["tab", "view", "section"]) {
    const v = params.get(k);
    if (v !== null) out.set(k, v);
  }
  params.forEach((v, k) => { if (k !== "tab" && k !== "view" && k !== "section") out.append(k, v); });
  return out;
}

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
  const set = (t: DeskPlace, view: string | null, section?: string) => {
    p.set("tab", t);
    if (view) p.set("view", view);
    else p.delete("view");
    if (section) p.set("section", section);
    return canonical(p);
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
  if (isPlace(tab)) {
    // A new URL. A missing or unknown view becomes the tab's default; a view on a tab without views is dropped.
    const loc = locationOf(params);
    return loc.view === params.get("view") ? null : set(loc.tab, loc.view);
  }
  switch (tab) {
    case "scanner": return set("overview", null, "scanner");
    case "intel": return set("market", "intel");
    case "events": return set("market", "intel", "events");
    case "chart": return set("market", "research");
    case "smartmoney": return set("market", "smartmoney");
    case "fno":
      if (params.get("lab") === "strategies") {
        p.delete("lab");
        return set("trade", "new", "fno");
      }
      return set("market", "smartmoney", "fno");
    case "more": {
      const view = params.get("view");
      if (view === "strategy") return set("trade", "new");
      if (view === "risk") return set("risk", "limits");
      if (view === "chartink") return set("market", "screener", "chartink");
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
    case "scanner": return { tab: "overview", view: null, section: "scanner" };
    case "intel": return { tab: "market", view: "intel" };
    case "events": return { tab: "market", view: "intel", section: "events" };
    case "chart": return { tab: "market", view: "research" };
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
