import { Zap, AlertTriangle, TrendingDown, DollarSign, BarChart2, Target, ShieldAlert, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PortfolioInsight } from "@/types/portfolio";
import type { Severity } from "@/types/common";

// ── Category → display metadata ───────────────────────────────────────────────
// Includes categories emitted by new engines (risk_alignment, suitability)

const CAT_META: Record<string, { icon: React.ElementType; color: string }> = {
  overlap:         { icon: BarChart2,    color: "text-[#8B5CF6]" },
  concentration:   { icon: AlertTriangle,color: "text-warm"      },
  balance:         { icon: BarChart2,    color: "text-[#3B82F6]" },
  cost:            { icon: DollarSign,   color: "text-[#F59E0B]" },
  tax:             { icon: DollarSign,   color: "text-[#14B8A6]" },
  goal:            { icon: Target,       color: "text-accent"    },
  goal_drift:      { icon: Target,       color: "text-accent"    },
  underperformer:  { icon: TrendingDown, color: "text-neg"       },
  // New engine categories
  risk_alignment:  { icon: ShieldAlert,  color: "text-neg"       },
  suitability:     { icon: ShieldAlert,  color: "text-neg"       },
  persona:         { icon: ShieldCheck,  color: "text-[#8B5CF6]" },
  diversification: { icon: BarChart2,    color: "text-[#3B82F6]" },
};

// Severity uses the canonical Severity type: "info" | "watch" | "fix" | "good"
const SEV_BADGE: Record<Severity, string> = {
  fix:   "bg-[rgb(var(--neg)/0.12)] text-neg",
  watch: "bg-[rgb(var(--warm)/0.10)] text-warm",
  info:  "bg-[rgba(59,130,246,0.10)] text-[#3B82F6]",
  good:  "bg-[rgb(var(--pos)/0.10)] text-pos",
};
const SEV_LABEL: Record<Severity, string> = {
  fix: "URGENT", watch: "WATCH", info: "TIP", good: "GOOD",
};
const SEV_ORDER: Severity[] = ["fix", "watch", "info", "good"];

// ── Allocation drift synthetic insight ────────────────────────────────────────

export interface AllocationDrift {
  actual_pct: number;
  target_pct: number;
  label: string;
}

interface Props {
  insights: PortfolioInsight[];
  allocationDrift?: AllocationDrift | null;
}

function InsightRow({ insight }: { insight: PortfolioInsight }) {
  const cat = CAT_META[insight.category] ?? { icon: Zap, color: "text-ink-3" };
  const Icon = cat.icon;
  const sev: Severity = (insight.severity as Severity) ?? "info";
  return (
    <div className="flex items-start gap-3 px-4 py-3.5 hover:bg-surface-2 transition-colors cursor-default">
      <div className="shrink-0 h-8 w-8 rounded-lg bg-surface-2 flex items-center justify-center mt-0.5">
        <Icon className={cn("h-4 w-4", cat.color)} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] leading-snug text-ink">{insight.title}</p>
        {insight.detail && (
          <p className="text-[11.5px] text-ink-3 mt-0.5 leading-relaxed line-clamp-2">{insight.detail}</p>
        )}
      </div>
      <span className={cn("shrink-0 mt-0.5 font-mono text-[9px] uppercase tracking-[.08em] px-2 py-0.5 rounded-full", SEV_BADGE[sev])}>
        {SEV_LABEL[sev]}
      </span>
    </div>
  );
}

export function IntelligenceFeed({ insights, allocationDrift }: Props) {
  const sorted = [...insights].sort((a, b) =>
    SEV_ORDER.indexOf(a.severity as Severity) - SEV_ORDER.indexOf(b.severity as Severity)
  );

  const driftIns: PortfolioInsight | null = allocationDrift
    ? {
        id: "drift",
        category: "goal",
        severity: Math.abs(allocationDrift.actual_pct - allocationDrift.target_pct) > 15 ? "watch" : "info",
        title: `Portfolio drift: ${allocationDrift.label} ${allocationDrift.actual_pct.toFixed(0)}% vs target ${allocationDrift.target_pct}%`,
        detail: "Rebalance to align with your risk profile target allocation.",
      }
    : null;

  const display = [...(driftIns ? [driftIns] : []), ...sorted].slice(0, 4);
  if (display.length === 0) return null;

  return (
    <div className="rounded-lg bg-surface-1 border border-hairline overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-hairline">
        <div className="flex items-center gap-2">
          <Zap className="h-3.5 w-3.5 text-accent" />
          <span className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Intelligence feed</span>
        </div>
        <span className="font-mono text-[10px] text-ink-4 px-2 py-0.5 rounded-full bg-surface-2">{display.length} signals</span>
      </div>
      <div className="divide-y divide-[rgb(var(--line)/0.06)]">
        {display.map((ins, i) => <InsightRow key={ins.id ?? i} insight={ins} />)}
      </div>
    </div>
  );
}
