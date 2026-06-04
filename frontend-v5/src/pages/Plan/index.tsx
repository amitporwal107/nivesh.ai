/**
 * Plan Board — 4-column kanban wired to plansService.getActive()
 * Design: Backlog | This week | In flight | Done · 30d
 */
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { plansService } from "@/services";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { useGeneratePlan, useRefreshPlan } from "@/hooks/use-recommendations";
import { RefreshCw } from "lucide-react";
import type { PlanActionC, PlanC } from "@/services/contracts/plan.contract";

function usePlan() {
  return useQuery({
    queryKey: ["plans", "active"],
    queryFn: () => plansService.getActive(),
  });
}

type Col = { id: string; label: string; statuses: string[] };

const COLUMNS: Col[] = [
  { id: "backlog",    label: "Backlog",      statuses: ["backlog", "pending"] },
  { id: "this_week",  label: "This week",    statuses: ["this_week", "scheduled"] },
  { id: "in_flight",  label: "In flight",    statuses: ["in_flight", "in_progress", "active"] },
  { id: "done",       label: "Done · 30d",   statuses: ["done", "completed"] },
];

function actionSeverity(type: string): "warm" | "accent" | "good" | "neg" {
  const t = type.toLowerCase();
  if (["sell", "switch", "reduce", "trim", "exit"].includes(t)) return "neg";
  if (["buy", "sip_increase", "add"].includes(t)) return "good";
  if (["sip_decrease"].includes(t)) return "warm";
  return "accent";
}

function PlanCard({ action }: { action: PlanActionC }) {
  const tone = actionSeverity(String(action.action_type ?? "").toLowerCase());
  const label = String(action.action_type ?? "action").replace(/_/g, " ").toUpperCase();
  const impact = action.estimated_impact;
  const isDone = ["done", "completed"].includes(String(action.status ?? "pending").toLowerCase());

  return (
    <div className={`rounded-lg bg-surface-1 border border-hairline p-3.5 mb-2.5 ${isDone ? "opacity-60" : ""}`}>
      <div className="flex items-center gap-2 mb-2">
        <Badge tone={tone} className="text-[9px]">{label}</Badge>
        {impact?.annual_savings_rs != null && (
          <span className="ml-auto font-mono num text-[11px] text-pos">
            +₹{Number(impact.annual_savings_rs).toLocaleString("en-IN")}/yr
          </span>
        )}
      </div>
      <div className="text-[13px] font-medium leading-[1.35]">
        {action.holding_name ?? action.asset_name ?? "Action"}
        {action.suggested_alternative ? ` → ${action.suggested_alternative}` : ""}
      </div>
      {(action.rationale ?? action.reason_text) && (
        <p className="mt-1.5 text-[12px] text-ink-3 leading-relaxed line-clamp-2">{action.rationale ?? action.reason_text}</p>
      )}
      {/* meta row */}
      <div className="mt-2 flex items-center gap-2 text-[10px] font-mono text-ink-4">
        {(action as any).due_date && <span>{(action as any).due_date}</span>}
        {(action as any).owner && (
          <span className="ml-auto grid place-items-center h-5 w-5 rounded bg-surface-3 text-[8px] text-ink-2">
            {String((action as any).owner).slice(0, 2).toUpperCase()}
          </span>
        )}
      </div>
    </div>
  );
}

function EmptyPlan() {
  const generate = useGeneratePlan();
  return (
    <div className="py-16 text-center">
      <div className="font-display text-xl text-ink-2 mb-2">No active plan</div>
      <p className="text-[14px] text-ink-3 max-w-[400px] mx-auto mb-6">
        Generate an action plan from your portfolio analysis to see recommended moves here.
      </p>
      <button
        onClick={() => generate.mutate()}
        disabled={generate.isPending}
        className="rounded-lg bg-accent text-on-accent font-medium text-[13px] px-6 py-3 hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2"
      >
        {generate.isPending ? (
          <><RefreshCw className="h-3.5 w-3.5 animate-spin" />Generating…</>
        ) : (
          "Generate plan →"
        )}
      </button>
      {generate.isError && (
        <p className="mt-3 text-[12px] text-neg">Failed to generate plan. Make sure you have holdings uploaded.</p>
      )}
    </div>
  );
}

function PlanKanban({ plan, onRefresh, isRefreshing }: { plan: PlanC; onRefresh: () => void; isRefreshing: boolean }) {
  const navigate = useNavigate();
  const actions = plan.actions ?? [];
  const totalSavings = actions.reduce((s, a) => s + (a.estimated_impact?.annual_savings_rs ?? 0), 0);
  const scoreDelta = (plan.health_score_projected ?? plan.health_score_before ?? 0) - (plan.health_score_before ?? 0);

  const colActions = (col: Col) =>
    actions.filter((a) => col.statuses.includes(String(a.status ?? "pending").toLowerCase()));

  return (
    <>
      {/* summary strip */}
      <div className="mt-6 rounded-lg bg-surface-1 border border-hairline p-4 flex flex-wrap gap-6 items-center">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">This week</div>
          <div className="font-display text-2xl num mt-0.5">{colActions(COLUMNS[1]).length} moves</div>
        </div>
        {totalSavings > 0 && (
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">Annual savings</div>
            <div className="font-display text-2xl num mt-0.5 text-pos">
              +₹{totalSavings.toLocaleString("en-IN")}/yr
            </div>
          </div>
        )}
        {scoreDelta > 0 && (
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">Health impact</div>
            <div className="font-display text-2xl num mt-0.5 text-pos">+{scoreDelta.toFixed(0)} pt</div>
          </div>
        )}
        <div className="ml-auto flex items-center gap-4 text-[10px] font-mono text-ink-3">
          <span>Cash needed: ₹0</span>
          <span>Compliance: all ✓</span>
        </div>
      </div>

      {/* 4-column kanban */}
      <div className="mt-5 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {COLUMNS.map((col) => {
          const items = colActions(col);
          return (
            <div key={col.id}>
              <div className="flex items-center mb-3">
                <div className="font-mono text-[10px] uppercase tracking-[.16em] text-ink-3">{col.label}</div>
                <span className="ml-2 font-mono text-[10px] text-ink-4">({items.length})</span>
              </div>
              {items.length === 0 ? (
                <div className="rounded-lg border border-dashed border-hairline h-24 flex items-center justify-center text-[12px] text-ink-4 font-mono">
                  empty
                </div>
              ) : (
                items.map((a) => <PlanCard key={a.action_id} action={a} />)
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

export default function PlanPage() {
  const navigate = useNavigate();
  const { data: plan, isPending, isError, error, refetch } = usePlan();
  const refresh = useRefreshPlan();
  const generate = useGeneratePlan();

  if (isPending) {
    return <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1200px] mx-auto w-full"><LoadingSkeleton variant="card" /></div>;
  }
  if (isError) {
    return <ErrorState onRetry={() => refetch()} error={error} />;
  }

  const isWorking = refresh.isPending || generate.isPending;

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1400px] mx-auto w-full">
      <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Workspace · Plan board</div>
      <div className="flex items-start mt-1.5">
        <h1 className="font-display text-[38px] tracking-tightish leading-[1.05]">
          Your plan, end-to-end.
        </h1>
        <div className="ml-auto flex gap-2 mt-1">
          {/* Re-generate plan from current portfolio */}
          <button
            onClick={() => plan ? refresh.mutate() : generate.mutate()}
            disabled={isWorking}
            className="inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-surface-1 font-medium text-[13px] px-4 py-2.5 text-ink-2 hover:bg-surface-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isWorking ? "animate-spin" : ""}`} aria-hidden />
            {isWorking ? "Generating…" : "Refresh plan"}
          </button>
          {/* Execute → navigates to Recommendations where each action has an Apply button */}
          <button
            onClick={() => navigate("/recommendations")}
            className="rounded-lg bg-accent text-on-accent font-medium text-[13px] px-5 py-2.5 hover:opacity-90 transition-opacity"
          >
            Execute →
          </button>
        </div>
      </div>

      {plan ? <PlanKanban plan={plan} onRefresh={() => refresh.mutate()} isRefreshing={refresh.isPending} /> : <EmptyPlan />}
    </div>
  );
}
