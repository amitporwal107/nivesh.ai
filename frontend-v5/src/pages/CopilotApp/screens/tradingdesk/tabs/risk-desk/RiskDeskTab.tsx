/**
 * Smart trading desk · 04 Risk Desk (desk redesign step 4, docs/desk_redesign_20261027/PLAN.md §1 and §3).
 *
 *   limits     Limits & budgets    the eight profile limits with used / left, open risk reserved, positions n of 10,
 *                                  the regime / VIX factor, input freshness, the F&O structure caps     (LimitsView)
 *   controls   Controls & profile  kill switch and halt, control changes, the risk profile and its change form, live
 *                                  trading readiness                                                     (ControlsView)
 *   log        Decision log        every allow / reduce / block with its estimate, budgets and versions; lineage and
 *                                  replay                                                                 (DecisionLog)
 *   hedge      Portfolio hedge     Quick Hedge: three Nifty put / put-spread choices for the equity-linked holdings, what each
 *                                  costs and does under falls (flag `portfolio_hedge`; hedge-data.ts)      (HedgeView)
 *   overview   Trading overview    Scanner-to-Paper Trading (owner, 5 Nov 2026; docs/scanner_paper_trading): the SPT account's
 *                                  capital, risk vs limits, drawdown ladder, kill switch, counts, warnings (TradingOverview)
 *   allocation Capital allocation  capital vs risk side by side, the ranked opportunities sized by your limits, recalculate
 *                                  (CapitalAllocation)
 *   portfolio  Portfolio risk      planned vs stressed risk, loss utilisation, sector concentration, stress scenarios,
 *                                  positions at risk (PortfolioRisk). The SPT reads: ./spt-risk-api.ts
 *
 * Plus, for an admin only, the job-health strip (parts.tsx JobStrip). Paper risk only: the real, broker-read portfolio's
 * risk checks are in My portfolio. The design's "Policy & runtime" view is left out (no backend); no slider anywhere.
 * Reads and writes: RiskControls.tsx, risk-controls.ts, risk-profile.ts, fnolab/governance-data.ts, ./risk-desk-data.ts.
 */
import { useCopilotShell } from "../../../../lib/shell-context";
import { CapitalAllocation } from "./CapitalAllocation";
import { ControlsView } from "./ControlsView";
import { DecisionLog } from "./DecisionLog";
import { HedgeView } from "./HedgeView";
import { LimitsView } from "./LimitsView";
import { JobStrip } from "./parts";
import { PortfolioRisk } from "./PortfolioRisk";
import { TradingOverview } from "./TradingOverview";

export type RiskDeskView = "limits" | "controls" | "log" | "hedge" | "overview" | "allocation" | "portfolio";
const VIEWS: readonly RiskDeskView[] = ["limits", "controls", "log", "hedge", "overview", "allocation", "portfolio"];

export default function RiskDeskTab({ view }: { view: string | null }) {
  const { mobile } = useCopilotShell();
  const v: RiskDeskView = (VIEWS as readonly string[]).includes(view ?? "") ? (view as RiskDeskView) : "limits";
  return (
    <div data-testid="risk-desk" data-view={v} className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <JobStrip />
      {v === "controls" ? <ControlsView /> : v === "log" ? <DecisionLog /> : v === "hedge" ? <HedgeView />
        : v === "overview" ? <TradingOverview /> : v === "allocation" ? <CapitalAllocation /> : v === "portfolio" ? <PortfolioRisk /> : <LimitsView />}
    </div>
  );
}
