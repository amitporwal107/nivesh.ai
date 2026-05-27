/**
 * Plan Board — action kanban wired to plansService.getActive().
 */
import { useQuery } from "@tanstack/react-query";
import { plansService } from "@/services";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { PlanActionC, PlanC } from "@/services/contracts/plan.contract";

function usePlan() {
  return useQuery({
    queryKey: ["plans", "active"],
    queryFn: () => plansService.getActive(),
  });
}

type Col = { id: string; label: string; statuses: string[] };

const COLUMNS: Col[] = [
  { id: "pending", label: "To do",    statuses: ["pending"] },
  { id: "done",    label: "Done",     statuses: ["done"] },
  { id: "skipped", label: "Skipped",  statuses: ["skipped"] },
];

function actionTypeTone(type: string): "warm" | "accent" | "good" | "neg" {
  if (["sell", "switch"].includes(type)) return "neg";
  if (["buy", "sip_increase"].includes(type)) return "good";
  if (["sip_decrease"].includes(type)) return "warm";
  return "accent";
}

function PlanActionCard({ action }: { action: PlanActionC }) {
  const tone = actionTypeTone(String(action.action_type));
  const label = String(action.action_type).replace(/_/g, " ").toUpperCase();
  const impact = action.estimated_impact;

  return (
    <div className="rounded-lg bg-surface-1 border border-hairline p-3 mb-2">
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
        <p className="mt-1 text-[12px] text-ink-3 leading-relaxed">{action.rationale}</p>
      )}
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
      <button className="rounded-lg bg-accent text-white font-medium text-[13px] px-6 py-3 hover:bg-accent/90 transition-colors">
        Generate plan →
      </button>
    </div>
  );
}

function PlanKanban({ plan }: { plan: PlanC }) {
  const actions = plan.actions ?? [];
  const totalSavings = actions.reduce((s, a) => s + (a.estimated_impact?.annual_savings_rs ?? 0), 0);
  const scoreDelta = (plan.health_score_projected ?? plan.health_score_before ?? 0) - (plan.health_score_before ?? 0);

  return (
    <>
      {/* summary strip */}
      <div className="mt-6 rounded-lg bg-surface-1 border border-hairline p-4 flex flex-wrap gap-6">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">Total actions</div>
          <div className="font-display text-2xl num mt-0.5">{plan.actions_total ?? actions.length}</div>
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
        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[10px] text-ink-3">
            {plan.actions_done ?? 0} done · {plan.actions_pending ?? 0} pending
          </span>
        </div>
      </div>

      {/* kanban */}
      <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-4">
        {COLUMNS.map((col) => {
          const colActions = actions.filter((a) => col.statuses.includes(String(a.status ?? "pending")));
          return (
            <div key={col.id}>
              <div className="flex items-center mb-3">
                <div className="font-mono text-[10px] uppercase tracking-[.16em] text-ink-3">{col.label}</div>
                <span className="ml-2 font-mono text-[10px] text-ink-4">({colActions.length})</span>
              </div>
              {colActions.length === 0 ? (
                <div className="rounded-lg border border-dashed border-hairline h-24 flex items-center justify-center text-[12px] text-ink-4 font-mono">
                  empty
                </div>
              ) : (
                colActions.map((a) => <PlanActionCard key={a.action_id} action={a} />)
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

export default function PlanPage() {
  const { data: plan, isLoading, isError } = usePlan();

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Workspace · Plan board</div>
      <div className="flex items-start mt-1.5">
        <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05]">
          Your plan, end-to-end.
        </h1>
        <button className="ml-auto mt-1 rounded-lg bg-accent text-white font-medium text-[13px] px-5 py-2.5 hover:bg-accent/90 transition-colors">
          Execute →
        </button>
      </div>

      {isLoading && (
        <div className="py-16 text-center font-mono text-[12px] text-ink-3">Loading plan…</div>
      )}
      {isError && (
        <div className="py-16 text-center font-mono text-[12px] text-neg">Could not load plan.</div>
      )}
      {!isLoading && !isError && (plan ? <PlanKanban plan={plan} /> : <EmptyPlan />)}

      {/* legend */}
      {plan && (
        <Card className="mt-6 p-4">
          <CardLabel>Action types</CardLabel>
          <div className="flex flex-wrap gap-3 mt-3">
            {[
              { type: "sell / switch", tone: "neg" as const },
              { type: "buy", tone: "good" as const },
              { type: "sip_increase", tone: "good" as const },
              { type: "sip_decrease", tone: "warm" as const },
              { type: "hold", tone: "accent" as const },
            ].map((e) => (
              <div key={e.type} className="flex items-center gap-1.5">
                <Badge tone={e.tone} className="text-[9px]">{e.type.replace(/_/g, " ").toUpperCase()}</Badge>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
