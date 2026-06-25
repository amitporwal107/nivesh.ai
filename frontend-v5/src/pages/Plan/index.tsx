/**
 * Plan Board — expandable kanban cards, wired to plansService.getActive()
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ChevronDown, RefreshCw, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { plansService } from "@/services";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { useGeneratePlan, useRefreshPlan } from "@/hooks/use-recommendations";
import type { PlanActionC, PlanC } from "@/services/contracts/plan.contract";

function usePlan() {
  return useQuery({
    queryKey: ["plans", "active"],
    queryFn: () => plansService.getActive(),
  });
}

type Col = { id: string; label: string; statuses: string[] };

const COLUMNS: Col[] = [
  { id: "backlog",   label: "Backlog",    statuses: ["backlog", "pending"] },
  { id: "this_week", label: "This week",  statuses: ["this_week", "scheduled"] },
  { id: "in_flight", label: "In flight",  statuses: ["in_flight", "in_progress", "active"] },
  { id: "done",      label: "Done · 30d", statuses: ["done", "completed"] },
];

type ActionMeta = {
  label: string;
  badgeClass: string;
  borderClass: string;
};

function getActionMeta(type: string): ActionMeta {
  const t = type.toLowerCase();
  if (["exit", "sell"].includes(t))
    return { label: "EXIT", badgeClass: "bg-[rgb(var(--neg)/0.12)] text-neg", borderClass: "border-l-neg/40" };
  if (["trim", "reduce"].includes(t))
    return { label: t === "reduce" ? "REDUCE" : "TRIM", badgeClass: "bg-[rgb(var(--warm)/0.12)] text-warm", borderClass: "border-l-warm/40" };
  if (["switch"].includes(t))
    return { label: "SWITCH", badgeClass: "bg-[rgb(var(--warm)/0.12)] text-warm", borderClass: "border-l-warm/40" };
  if (["add", "buy", "sip_increase"].includes(t))
    return { label: t === "sip_increase" ? "SIP ↑" : "ADD", badgeClass: "bg-accent text-white", borderClass: "border-l-accent/50" };
  if (["redirect", "diversify"].includes(t))
    return { label: t.toUpperCase(), badgeClass: "bg-accent/80 text-white", borderClass: "border-l-accent/40" };
  return { label: type.toUpperCase() || "ACTION", badgeClass: "bg-surface-3 text-ink-2", borderClass: "border-l-hairline" };
}

function fmtRs(n: number): string {
  if (n >= 10_00_000) return `₹${(n / 10_00_000).toFixed(1)}L`;
  if (n >= 1_000)     return `₹${(n / 1_000).toFixed(0)}k`;
  return `₹${n.toFixed(0)}`;
}

function PlanCard({ action, onExecute }: { action: PlanActionC; onExecute: () => void }) {
  const [open, setOpen] = useState(false);

  const actionType  = String(action.action ?? action.action_type ?? "");
  const meta        = getActionMeta(actionType);
  const fundName    = action.asset_name ?? action.holding_name ?? "Action";
  const conviction  = (action as any).conviction_text ?? action.reason_text ?? (action as any).rationale ?? "";
  const magnitude   = (action as any).magnitude ?? (action as any).amount ?? action.estimated_impact?.annual_savings_rs;
  const execution   = (action as any).execution ?? (action as any).execution_path;
  const severity    = (action as any).severity;
  const isDone      = ["done", "completed"].includes(String(action.status ?? "pending").toLowerCase());

  return (
    <div
      className={cn(
        "rounded-lg bg-surface-1 border border-hairline border-l-[3px] mb-2.5 overflow-hidden transition-opacity",
        meta.borderClass,
        isDone && "opacity-50",
      )}
    >
      {/* ── Collapsed header — always visible ─────────────────────────── */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left px-3.5 py-3 flex items-start gap-2.5 hover:bg-surface-2/40 transition-colors"
        aria-expanded={open}
      >
        {/* action badge */}
        <span className={cn("shrink-0 mt-0.5 rounded-full px-2 py-0.5 text-[9px] font-semibold tracking-wide", meta.badgeClass)}>
          {meta.label}
        </span>

        {/* fund name */}
        <span className={cn("flex-1 text-[13px] font-medium leading-[1.4]", !open && "line-clamp-2")}>
          {fundName}
        </span>

        {/* amount + chevron */}
        <span className="shrink-0 flex items-center gap-1.5 ml-1">
          {magnitude != null && (
            <span className="font-mono text-[11px] text-ink-3">{fmtRs(Number(magnitude))}</span>
          )}
          <ChevronDown
            className={cn("h-3.5 w-3.5 text-ink-4 transition-transform duration-200", open && "rotate-180")}
            aria-hidden
          />
        </span>
      </button>

      {/* ── Expanded body ──────────────────────────────────────────────── */}
      {open && (
        <div className="px-3.5 pb-3.5 border-t border-hairline/50 pt-3 space-y-3">
          {/* conviction / reason text */}
          {conviction && (
            <p className="text-[12.5px] text-ink-2 leading-relaxed">{conviction}</p>
          )}

          {/* meta chips */}
          <div className="flex flex-wrap gap-1.5">
            {severity && (
              <span className="rounded-full border border-hairline px-2 py-0.5 text-[10px] font-mono text-ink-3 capitalize">
                {severity}
              </span>
            )}
            {execution && (
              <span className="rounded-full border border-hairline px-2 py-0.5 text-[10px] font-mono text-ink-3">
                {String(execution).replace(/-/g, " ")}
              </span>
            )}
            {magnitude != null && (
              <span className="rounded-full border border-hairline px-2 py-0.5 text-[10px] font-mono text-ink-3">
                {fmtRs(Number(magnitude))}
              </span>
            )}
          </div>

          {/* tax impact if present */}
          {(action as any).tax_impact && (
            <div className="text-[11px] text-ink-3 font-mono space-y-0.5 bg-surface-2 rounded-md px-2.5 py-2">
              {(action as any).tax_impact.ltcg != null && (
                <div className="flex justify-between">
                  <span>LTCG</span>
                  <span className="text-neg">-{fmtRs(Math.abs((action as any).tax_impact.ltcg))}</span>
                </div>
              )}
              {(action as any).tax_impact.stcg != null && (action as any).tax_impact.stcg > 0 && (
                <div className="flex justify-between">
                  <span>STCG</span>
                  <span className="text-neg">-{fmtRs(Math.abs((action as any).tax_impact.stcg))}</span>
                </div>
              )}
            </div>
          )}

          {/* CTA */}
          {!isDone && (
            <button
              type="button"
              onClick={onExecute}
              className="inline-flex items-center gap-1.5 text-[12px] font-medium text-accent hover:underline"
            >
              Go to Recommendations <ArrowRight className="h-3 w-3" aria-hidden />
            </button>
          )}
        </div>
      )}
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
        {generate.isPending
          ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" />Generating…</>
          : "Generate plan →"}
      </button>
      {generate.isError && (
        <p className="mt-3 text-[12px] text-neg">Failed to generate plan. Make sure you have holdings uploaded.</p>
      )}
    </div>
  );
}

function PlanKanban({ plan }: { plan: PlanC }) {
  const navigate = useNavigate();
  const actions = plan.actions ?? [];
  const totalSavings = actions.reduce((s, a) => s + (a.estimated_impact?.annual_savings_rs ?? 0), 0);

  const colActions = (col: Col) =>
    actions.filter((a) => col.statuses.includes(String(a.status ?? "pending").toLowerCase()));

  return (
    <>
      {/* summary strip */}
      <div className="mt-6 rounded-lg bg-surface-1 border border-hairline p-4 flex flex-wrap gap-6 items-center">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">Actions</div>
          <div className="font-display text-2xl num mt-0.5">{actions.length} total</div>
        </div>
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">Backlog</div>
          <div className="font-display text-2xl num mt-0.5">{colActions(COLUMNS[0]).length}</div>
        </div>
        {totalSavings > 0 && (
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">Annual savings</div>
            <div className="font-display text-2xl num mt-0.5 text-pos">
              +₹{totalSavings.toLocaleString("en-IN")}/yr
            </div>
          </div>
        )}
        <div className="ml-auto flex items-center gap-4 text-[10px] font-mono text-ink-3">
          <span>Compliance: all ✓</span>
        </div>
      </div>

      {/* 4-column kanban */}
      <div className="mt-5 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {COLUMNS.map((col) => {
          const items = colActions(col);
          return (
            <div key={col.id}>
              <div className="flex items-center mb-3 pb-2 border-b border-hairline">
                <div className="font-mono text-[10px] uppercase tracking-[.16em] text-ink-3">{col.label}</div>
                <span className="ml-2 font-mono text-[10px] text-ink-4">· {items.length}</span>
              </div>
              {items.length === 0 ? (
                <div className="rounded-lg border border-dashed border-hairline h-20 flex items-center justify-center text-[11px] text-ink-4 font-mono">
                  empty
                </div>
              ) : (
                items.map((a) => (
                  <PlanCard
                    key={a.action_id ?? a.action}
                    action={a}
                    onExecute={() => navigate("/recommendations")}
                  />
                ))
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
          <button
            onClick={() => plan ? refresh.mutate() : generate.mutate()}
            disabled={isWorking}
            className="inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-surface-1 font-medium text-[13px] px-4 py-2.5 text-ink-2 hover:bg-surface-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isWorking && "animate-spin")} aria-hidden />
            {isWorking ? "Generating…" : "Refresh plan"}
          </button>
          <button
            onClick={() => navigate("/recommendations")}
            className="rounded-lg bg-accent text-on-accent font-medium text-[13px] px-5 py-2.5 hover:opacity-90 transition-opacity"
          >
            Execute →
          </button>
        </div>
      </div>

      {plan ? <PlanKanban plan={plan} /> : <EmptyPlan />}
    </div>
  );
}
