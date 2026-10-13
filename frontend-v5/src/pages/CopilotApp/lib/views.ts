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
  { view: "trader", label: "Trader desk", tag: "F&O" },
  { view: "tool/optlab", label: "Options lab", tag: "F&O" },
  // The original strategy builder (screen → backtest → save), mounted inside the shell.
  { view: "trader/strategy", label: "Strategy builder" },
  { view: "tool/screener", label: "Screener" },
  { view: "tool/markets", label: "Markets" },
  { view: "tool/research", label: "Stock research" },
];

/** Tools shown in the rail for a mode. */
export function toolsNav(mode: Mode): NavItem[] {
  return mode === "trader" ? TRADER_TOOLS : mode === "advisor" ? ADVISOR_TOOLS : INVESTOR_TOOLS;
}

export const WORKSPACE_NAV: NavItem[] = [
  { view: "page/watchlist", label: "Watchlist & alerts" },
  { view: "page/saved", label: "Saved" },
  { view: "page/plan", label: "Action plan" },
  { view: "page/ledger", label: "Portfolio ledger" },
  { view: "page/paper", label: "Paper trades" },
  { view: "page/brokers", label: "Broker connections" },
  { view: "page/settings", label: "Settings" },
];

/** Internal pages — admins only. */
export const INTERNAL_NAV: NavItem[] = [
  { view: "builder", label: "Tool builder" },
  { view: "ops/tools", label: "Tool registry" },
  { view: "ops/feeds", label: "Feed health" },
  { view: "ops/audit", label: "Audit log" },
  { view: "ops/kpis", label: "KPIs" },
];

/** Where each mode lands when it is selected. */
export const MODE_HOME: Record<Mode, string> = {
  investor: "",
  trader: "trader",
  advisor: "advisor",
};

/** Absolute router path for a view. */
export function viewPath(view: string): string {
  const v = view.replace(/^\/+/, "");
  return v ? `${APP_BASE}/${v}` : APP_BASE;
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
