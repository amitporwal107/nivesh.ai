/**
 * Copilot app — the view map.
 *
 * Every screen in the one-screen Copilot lives under APP_BASE. A "view" is the
 * path below it ("" = home, "tool/screener", "page/watchlist", …), which is what
 * screens pass to `go()` from the shell context.
 *
 * Design source: frontend-v5/design/nivesh-copilot/Nivesh Copilot.dc.html
 * (toolsNav / saved / opsNav in its script block).
 */
export const APP_BASE = "/app";

export type Mode = "investor" | "trader" | "advisor";

export const MODE_LABEL: Record<Mode, string> = {
  investor: "Investor",
  trader: "Trader",
  advisor: "Advisor",
};

export interface NavItem {
  /** Path below APP_BASE, without a leading slash. */
  view: string;
  label: string;
  /** Small mono tag shown at the right of the row (e.g. "F&O"). */
  tag?: string;
}

/**
 * The sector rotation heatmap (screens/index.ts), which no rail lists. In Trader mode this route opens the desk's
 * Market Desk › Sector Rotation (index.tsx); it opens from the Screener, the desk's sector card, and by URL.
 */
export const SECTOR_HEATMAP_VIEW = "tool/sector-heatmap";

/**
 * The equity strategy builder (screen → backtest → save), mounted inside the shell. The "Backtest in the strategy
 * builder" links open it here; the old standalone /strategy-builder URL now redirects to the desk's Trade Desk (routes.tsx).
 */
export const STRATEGY_BUILDER_VIEW = "trader/strategy";

const INVESTOR_TOOLS: NavItem[] = [
  { view: "tool/analysis", label: "Portfolio analysis" },
  { view: "tool/recommend", label: "Recommendations" },
  // The original v5 dashboards, mounted inside the shell.
  { view: "tool/risk", label: "Risk" },
  { view: "tool/goals", label: "Goals" },
  { view: "tool/tax", label: "Tax" },
  { view: "tool/research", label: "Stock & fund research" },
  { view: "tool/screener", label: "Screener" },
  { view: "tool/markets", label: "Markets" },
];

/** Advisor mode: the client book plus the original v5 advisor tools. */
const ADVISOR_TOOLS: NavItem[] = [
  { view: "advisor", label: "Client book" },
  { view: "advisor/workspace", label: "Advisor workspace" },
  { view: "advisor/client-360", label: "Client 360" },
  { view: "advisor/sip-board", label: "SIP board" },
  { view: "tool/research", label: "Stock & fund research" },
  { view: "tool/screener", label: "Screener" },
  { view: "tool/markets", label: "Markets" },
];

const TRADER_TOOLS: NavItem[] = [
  // The desk's four tabs, My portfolio and the docked Copilot. The old Trader desk, Options lab and F&O lab were removed
  // in the redesign's step 6 (2026-10-27); their URLs redirect into the desk (lib/retired-views.ts).
  { view: "trader/desk", label: "Smart trading desk", tag: "AI" },
  // The original strategy builder (screen → backtest → save), mounted inside the shell.
  { view: "trader/strategy", label: "Strategy builder" },
  { view: "tool/screener", label: "Screener" },
  { view: "tool/markets", label: "Markets" },
  { view: "tool/research", label: "Stock research" },
];

/** Every tool screen a mode has (the screens stay mounted; the Trader rail lists fewer, see toolsNav). */
export function allToolsNav(mode: Mode): NavItem[] {
  return mode === "trader" ? TRADER_TOOLS : mode === "advisor" ? ADVISOR_TOOLS : INVESTOR_TOOLS;
}

/**
 * The tools the Trader rail lists: the Smart trading desk (the owner's decision of 2026-10-27, 16:30) and, since 2026-11-01
 * (docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md, slice W1), two rows that open desk views directly: Screener (Market Desk)
 * and Watchlists (Trade Desk). Stock research and Sector rotation are still only views of the Market Desk, and in Trader mode
 * their old routes open those views (index.tsx, screens/tradingdesk/desk-nav.ts TRADER_TOOL_TO_DESK). The other Trader screens
 * remain reachable by URL.
 */
const TRADER_RAIL_TOOLS: NavItem[] = [
  { view: "trader/desk", label: "Smart trading desk", tag: "AI" },
  { view: "trader/desk?tab=market&view=screener", label: "Screener" },
  { view: "trader/desk?tab=trade&view=watchlists", label: "Watchlists" },
];

/**
 * Which row of `items` is the current page. A row's `view` may carry a query ("trader/desk?tab=market&view=screener"): it matches
 * when the path is the same and every one of its params is in `search`. A row with no query (the desk's own row) is current only
 * when no sibling row with the same path matches, so the desk row does not stay lit while Screener is open.
 */
export function isNavCurrent(item: NavItem, items: NavItem[], view: string, search = ""): boolean {
  const [path, query = ""] = item.view.split("?");
  if (path !== view) return false;
  const have = new URLSearchParams(search);
  const matches = (q: string) => {
    for (const [k, v] of new URLSearchParams(q)) if (have.get(k) !== v) return false;
    return true;
  };
  if (query) return matches(query);
  return !items.some((o) => o !== item && o.view.startsWith(`${path}?`) && matches(o.view.split("?")[1]));
}

/** Tools shown in the rail for a mode. */
export function toolsNav(mode: Mode): NavItem[] {
  return mode === "trader" ? TRADER_RAIL_TOOLS : allToolsNav(mode);
}

export const WORKSPACE_NAV: NavItem[] = [
  { view: "page/watchlist", label: "Watchlist & alerts" },
  { view: "page/saved", label: "Saved" },
  { view: "page/history", label: "Past conversations" },
  { view: "page/plan", label: "Action plan" },
  { view: "page/ledger", label: "Portfolio ledger" },
  { view: "page/positions", label: "Open positions" },
  { view: "page/paper", label: "Paper trades" },
  { view: "page/brokers", label: "Broker connections" },
  { view: "page/settings", label: "Settings" },
];

/** Workspace rows the rail lists (Trader: Settings only); the other workspace pages remain reachable by direct URL. */
export function workspaceNav(mode: Mode): NavItem[] {
  return mode === "trader" ? WORKSPACE_NAV.filter((n) => n.view === "page/settings") : WORKSPACE_NAV;
}

/** Internal pages — admins only. */
export const INTERNAL_NAV: NavItem[] = [
  { view: "builder", label: "Tool builder" },
  { view: "ops/tools", label: "Tool registry" },
  { view: "ops/feeds", label: "Feed health" },
  { view: "ops/audit", label: "Audit log" },
  { view: "ops/kpis", label: "KPIs" },
];

/** Where each mode lands when it is selected. Trader: the Smart trading desk's Market Overview (the redesign of 2026-10-27). */
export const MODE_HOME: Record<Mode, string> = {
  investor: "",
  trader: "trader/desk",
  advisor: "advisor",
};

/** Absolute router path for a view. */
export function viewPath(view: string): string {
  const v = view.replace(/^\/+/, "");
  return v ? `${APP_BASE}/${v}` : APP_BASE;
}

/** The rail lists threads touched within this window; older ones live under page/history. */
export const RECENT_THREAD_MS = 2 * 24 * 60 * 60 * 1000;

export function isRecentThread(updatedAt?: string, now = Date.now()): boolean {
  const t = updatedAt ? Date.parse(updatedAt) : NaN;
  return Number.isFinite(t) && now - t <= RECENT_THREAD_MS;
}

export function threadView(sessionId: string): string {
  return `t/${encodeURIComponent(sessionId)}`;
}

/** The view for a router pathname ("/app/tool/screener" → "tool/screener"). */
export function viewOf(pathname: string): string {
  if (!pathname.startsWith(APP_BASE)) return "";
  return pathname.slice(APP_BASE.length).replace(/^\/+|\/+$/g, "");
}

/** Session id when the pathname is a thread, else undefined. */
export function threadIdOf(pathname: string): string | undefined {
  const m = viewOf(pathname).match(/^t\/([^/]+)$/);
  return m ? decodeURIComponent(m[1]) : undefined;
}
