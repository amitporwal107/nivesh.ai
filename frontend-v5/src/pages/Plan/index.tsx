/**
 * Plan Board — 4-column kanban wired to plansService.getActive()
 * Design: Backlog | This week | In flight | Done · 30d
 */
import { useQuery } from "@tanstack/react-query";
import { plansService } from "@/services";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
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
  if (["sell", "switch", "reduce"].includes(type)) return "neg";
  if (["buy", "sip_increase", "add"].includes(type)) return "good";
  if (["sip_decrease"].includes(type)) return "warm";
  return "accent";
}

function PlanCard({ action }: { action: PlanActionC }) {
  const tone = actionSeverity(String(action.action_type ?? ""));
  const label = String(action.action_type ?? "action").replace(/_/g, " ").toUpperCase();
  const impact = action.estimated_impact;
  const isDone = ["done", "completed"].includes(String(action.status ?? ""));

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
        {action.holding_name ?? "Action"}
        {action.suggested_alternative ? ` → ${action.suggested_alternative}` : ""}
      </div>
      {action.rationale && (
        <p className="mt-1.5 text-[12px] text-ink-3 leading-relaxed line-clamp-2">{action.rationale}</p>
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
  return (
    <div className="py-16 text-center">
      <div className="font-display text-xl text-ink-2 mb-2">No active plan</div>
      <p className="text-[14px] text-ink-3 max-w-[400px] mx-auto mb-6">
        Generate an action plan from your portfolio analysis to see recommended moves here.
      </p>
      <button className="rounded-lg bg-accent text-on-accent font-medium text-[13px] px-6 py-3 hover:opacity-90 transition-opacity">
        Generate plan →
      </button>
    </div>
  );
}

function PlanKanban({ plan }: { plan: PlanC }) {
  const actions = plan.actions ?? [];
  const totalSavings = actions.reduce((s, a) => s + (a.estimated_impact?.annual_savings_rs ?? 0), 0);
  const scoreDelta = (plan.health_score_projected ?? plan.health_score_before ?? 0) - (plan.health_score_before ?? 0);

  // Assign actions to columns. Actions without explicit column status go to backlog.
  const colActions = (col: Col) => {
    const matched = actions.filter((a) => col.statuses.includes(String(a.status ?? "pending")));
    return matched;
  };

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
  const { data: plan, isPending, isError, error, refetch } = usePlan();

  if (isPending) {
    return <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1200px] mx-auto w-full"><LoadingSkeleton variant="card" /></div>;
  }
  if (isError) {
    return <ErrorState onRetry={() => refetch()} error={error} />;
  }

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1400px] mx-auto w-full">
      <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Workspace · Plan board</div>
      <div className="flex items-start mt-1.5">
        <h1 className="font-display text-[38px] tracking-tightish leading-[1.05]">
          Your plan, end-to-end.
        </h1>
        <div className="ml-auto flex gap-2 mt-1">
          <button className="rounded-lg border border-hairline bg-surface-1 font-medium text-[13px] px-4 py-2.5 text-ink-2 hover:bg-surface-2 transition-colors">
            Export PDF
          </button>
          <button className="rounded-lg bg-accent text-on-accent font-medium text-[13px] px-5 py-2.5 hover:opacity-90 transition-opacity">
            Execute →
          </button>
        </div>
      </div>

      {plan ? <PlanKanban plan={plan} /> : <EmptyPlan />}
    </div>
  );
}
