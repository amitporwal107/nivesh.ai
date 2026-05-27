import { useGoals } from "@/hooks/use-goals";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Goal } from "@/types/goal";

function formatRs(paise: number) {
  const rs = paise / 100;
  if (rs >= 1_00_00_000) return `₹${(rs / 1_00_00_000).toFixed(1)} Cr`;
  if (rs >= 1_00_000) return `₹${(rs / 1_00_000).toFixed(1)} L`;
  if (rs >= 1_000) return `₹${(rs / 1_000).toFixed(1)}k`;
  return `₹${rs.toLocaleString("en-IN")}`;
}

function GoalRow({ goal }: { goal: Goal }) {
  const pct = Math.round(goal.progress * 100);
  return (
    <li className="grid grid-cols-[1.6fr_80px_1fr_90px_80px_40px] gap-3 items-center py-3 border-t border-[rgb(var(--line)/0.10)]">
      <div>
        <div className="text-[14px] font-medium">{goal.icon} {goal.name}</div>
        <div className="font-mono text-[10px] text-ink-3 mt-0.5 tracking-tight">
          by {goal.targetDate} · {formatRs(goal.targetAmount)}
        </div>
      </div>
      <div className={`font-mono num text-[13px] ${goal.onTrack ? "text-pos" : "text-warm"}`}>{pct}%</div>
      <div className="h-1.5 bg-surface-3 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: goal.onTrack ? "var(--color-pos)" : "var(--color-warm)" }}
        />
      </div>
      <div className="font-mono num text-[12px] text-ink-2">{formatRs(goal.monthlySip)}/mo</div>
      <Badge tone={goal.onTrack ? "good" : "warm"} className="text-[9px]">
        {goal.progress >= 1 ? "DONE" : goal.onTrack ? "ON TRACK" : "BEHIND"}
      </Badge>
      <span className="text-ink-3 text-right">›</span>
    </li>
  );
}

export default function GoalsPage() {
  const { data, isLoading, isError } = useGoals();

  if (isLoading) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <div className="h-64 flex items-center justify-center font-mono text-[12px] text-ink-3">
          Loading goals…
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <div className="h-64 flex items-center justify-center font-mono text-[12px] text-neg">
          Could not load goals. Try again later.
        </div>
      </div>
    );
  }

  const { goals, totals } = data;
  const onTrackCount = totals.onTrack;
  const totalCount = totals.total;
  const totalTarget = goals.reduce((s, g) => s + g.targetAmount, 0);
  const totalCurrent = goals.reduce((s, g) => s + g.currentAmount, 0);

  const headlineStatus = onTrackCount === totalCount
    ? "All goals on track."
    : onTrackCount === 0
    ? "Goals need attention."
    : `${onTrackCount} of ${totalCount} goals on track.`;

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Goals</div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
        {headlineStatus}
      </h1>
      <p className="text-[15.5px] text-ink-2 mt-3 max-w-[600px] leading-relaxed">
        Track your financial milestones — from home down-payments to retirement — with monthly SIP projections.
      </p>

      {/* KPI strip */}
      <div className="mt-7 grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "On track", value: `${onTrackCount} / ${totalCount}`, sub: "goals", tone: "text-pos" },
          { label: "Total target", value: formatRs(totalTarget), sub: "combined", tone: "text-ink" },
          { label: "Current corpus", value: formatRs(totalCurrent), sub: "invested", tone: "text-ink" },
          { label: "Gap", value: formatRs(Math.max(0, totalTarget - totalCurrent)), sub: "to raise", tone: "text-warm" },
        ].map((kpi) => (
          <div key={kpi.label} className="rounded-lg bg-surface-1 border border-hairline p-4">
            <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">{kpi.label}</div>
            <div className={`font-display text-2xl num mt-1 ${kpi.tone}`}>{kpi.value}</div>
            <div className="font-mono text-[10px] text-ink-3 mt-0.5">{kpi.sub}</div>
          </div>
        ))}
      </div>

      {/* Goals list */}
      <Card className="mt-5 p-6">
        <div className="flex items-center mb-2">
          <CardLabel>All goals · funded %</CardLabel>
          <button className="ml-auto text-[12px] text-accent hover:underline underline-offset-4">
            + Add goal
          </button>
        </div>
        {goals.length === 0 ? (
          <div className="py-12 text-center font-mono text-[12px] text-ink-3">
            No goals yet. Add your first goal to get started.
          </div>
        ) : (
          <ul>
            {goals.map((g) => <GoalRow key={g.id} goal={g} />)}
          </ul>
        )}
      </Card>

      {/* message */}
      {totals.atRisk > 0 && (
        <div className="mt-4 rounded-lg bg-warm-soft border border-warm/20 p-4 text-[13.5px]">
          <span className="font-medium text-warm">{totals.atRisk} goal{totals.atRisk > 1 ? "s" : ""} at risk</span>
          {" — "}consider a SIP top-up or extending the horizon to close the gap.
        </div>
      )}
    </div>
  );
}
