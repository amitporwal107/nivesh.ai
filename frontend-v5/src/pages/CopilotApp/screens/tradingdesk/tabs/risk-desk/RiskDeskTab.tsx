/**
 * Smart trading desk · 04 Risk Desk (desk redesign step 4, docs/desk_redesign_20261027/PLAN.md §1 and §3).
 *
 *   limits     Limits & budgets    the eight profile limits with used / left, open risk reserved, positions n of 10,
 *                                  the regime / VIX factor, input freshness, the F&O structure caps     (LimitsView)
 *   controls   Controls & profile  kill switch and halt, control changes, the risk profile and its change form, live
 *                                  trading readiness                                                     (ControlsView)
 *   log        Decision log        every allow / reduce / block with its estimate, budgets and versions; lineage and
 *                                  replay                                                                 (DecisionLog)
 *
 * Plus, for an admin only, the job-health strip (parts.tsx JobStrip). Paper risk only: the real, broker-read portfolio's
 * risk checks are in My portfolio. The design's "Policy & runtime" view is left out (no backend); no slider anywhere.
 * Reads and writes: RiskControls.tsx, risk-controls.ts, risk-profile.ts, fnolab/governance-data.ts, ./risk-desk-data.ts.
 */
import { useCopilotShell } from "../../../../lib/shell-context";
import { ControlsView } from "./ControlsView";
import { DecisionLog } from "./DecisionLog";
import { LimitsView } from "./LimitsView";
import { JobStrip } from "./parts";

export type RiskDeskView = "limits" | "controls" | "log";

export default function RiskDeskTab({ view }: { view: string | null }) {
  const { mobile } = useCopilotShell();
  const v: RiskDeskView = view === "controls" || view === "log" ? view : "limits";
  return (
    <div data-testid="risk-desk" data-view={v} className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <JobStrip />
      {v === "controls" ? <ControlsView /> : v === "log" ? <DecisionLog /> : <LimitsView />}
    </div>
  );
}
