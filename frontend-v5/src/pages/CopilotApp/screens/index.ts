/**
 * Screen registry — view path (below the app base) → lazily loaded screen.
 * Home and the answer thread are not here; the shell renders those itself.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

type Screen = LazyExoticComponent<ComponentType>;

export const SCREENS: Record<string, Screen> = {
  "tool/analysis": lazy(() => import("./Analysis")),
  "tool/recommend": lazy(() => import("./Recommend")),
  "tool/research": lazy(() => import("./Research")),
  "tool/screener": lazy(() => import("./Screener")),
  "tool/markets": lazy(() => import("./Markets")),
  "tool/optlab": lazy(() => import("./OptionsLab")),
  trader: lazy(() => import("./Trader")),
  "trader/desk": lazy(() => import("./TradingDesk")),
  "trader/strategy": lazy(() => import("./desk/StrategyBuilder")),
  "page/watchlist": lazy(() => import("./Watchlist")),
  "page/saved": lazy(() => import("./Saved")),
  "page/plan": lazy(() => import("./Plan")),
  "page/ledger": lazy(() => import("./Ledger")),
  "page/paper": lazy(() => import("./Paper")),
  "page/brokers": lazy(() => import("./Brokers")),
  "page/settings": lazy(() => import("./Settings")),
  advisor: lazy(() => import("./Advisor")),
  // Screens of the original v5 app, mounted unchanged inside the shell.
  "tool/risk": lazy(() => import("./legacy/Risk")),
  "tool/goals": lazy(() => import("./legacy/Goals")),
  "tool/tax": lazy(() => import("./legacy/Tax")),
  "advisor/workspace": lazy(() => import("./legacy/AdvisorWorkspace")),
  "advisor/client-360": lazy(() => import("./legacy/Client360")),
  "advisor/sip-board": lazy(() => import("./advisor/SipBoard")),
  onboarding: lazy(() => import("./Onboarding")),
};

/** Internal screens — reachable by admins only. */
export const ADMIN_SCREENS: Record<string, Screen> = {
  builder: lazy(() => import("./ToolBuilder")),
  "ops/tools": lazy(() => import("./OpsTools")),
  "ops/feeds": lazy(() => import("./OpsFeeds")),
  "ops/audit": lazy(() => import("./OpsAudit")),
  "ops/kpis": lazy(() => import("./OpsKpis")),
};
