/**
 * PriorityChip — coloured pill (high/medium/low) with a hover popover that
 * enumerates WHY the client bubbled up. Reasons + factor breakdown come from
 * the backend priority_engine so advisors trust the ranking.
 *
 * V5 has no Tooltip primitive, so the popover is a pure-CSS group-hover card.
 */
import { AlertTriangle, Activity, CheckCircle2, Info } from "lucide-react";
import type { PriorityC } from "@/services/contracts/advisor.contract";

const META = {
  high:   { label: "High",   tone: "bg-neg/15 text-neg border-neg/30",       Icon: AlertTriangle, dot: "bg-neg" },
  medium: { label: "Medium", tone: "bg-warm/15 text-warm border-warm/30",    Icon: Activity,      dot: "bg-warm" },
  low:    { label: "Low",    tone: "bg-pos/15 text-pos border-pos/30",        Icon: CheckCircle2,  dot: "bg-pos" },
} as const;

export function PriorityChip({ priority }: { priority?: PriorityC | null }) {
  if (!priority) return null;
  const m = META[(priority.bucket as keyof typeof META)] || META.medium;
  const Icon = m.Icon;
  const pct = Math.round((priority.score || 0) * 100);
  const factors = priority.factors;

  return (
    <div className="relative inline-block group">
      <div
        data-testid={`priority-chip-${priority.bucket}`}
        className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold cursor-default ${m.tone}`}
      >
        <Icon className="w-3 h-3" />
        <span className="capitalize">{m.label}</span>
        <span className="text-[10px] tabular-nums opacity-70">· {pct}</span>
        <Info className="w-2.5 h-2.5 opacity-50" />
      </div>

      {/* Hover popover */}
      <div className="pointer-events-none absolute right-0 top-full mt-1.5 z-40 hidden w-64 rounded-lg border border-hairline bg-surface-1 p-3 text-xs shadow-pop group-hover:block">
        <div className="font-semibold mb-1.5 flex items-center gap-1.5 text-ink">
          <span className={`w-2 h-2 rounded-full ${m.dot}`} />
          {m.label} priority · score {pct}
        </div>
        <div className="space-y-1 text-ink-2">
          {(priority.reasons || []).map((r, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <span className="text-ink-4 mt-0.5">•</span>
              <span>{r}</span>
            </div>
          ))}
        </div>
        {factors && (
          <div className="mt-2 pt-2 border-t border-hairline">
            <div className="text-[9px] uppercase tracking-wider text-ink-4 mb-1">Factor breakdown</div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] tabular-nums text-ink-2">
              <span>Weakness</span><span className="text-right font-mono">{Math.round((factors.portfolio_weakness ?? 0) * 100)}%</span>
              <span>Risk</span><span className="text-right font-mono">{Math.round((factors.risk ?? 0) * 100)}%</span>
              <span>AUM</span><span className="text-right font-mono">{Math.round((factors.aum ?? 0) * 100)}%</span>
              <span>Recency</span><span className="text-right font-mono">{Math.round((factors.recency ?? 0) * 100)}%</span>
              <span>Action urg.</span><span className="text-right font-mono">{Math.round((factors.recommendation_severity ?? 0) * 100)}%</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
