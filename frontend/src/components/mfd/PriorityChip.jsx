import React from "react";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";
import { AlertTriangle, Activity, CheckCircle2, Info } from "lucide-react";

/**
 * PriorityChip — coloured pill showing high/medium/low plus a tooltip
 * that enumerates WHY this client bubbled up. The "reasons" array comes
 * straight from the priority_engine's rule-based diagnostic so MFDs
 * trust the ranking instead of treating it as a black box.
 */
const META = {
  high:   { label: "High",   tone: "bg-rose-100 text-rose-800 border-rose-300",         icon: AlertTriangle,  dot: "bg-rose-500" },
  medium: { label: "Medium", tone: "bg-amber-100 text-amber-800 border-amber-300",       icon: Activity,       dot: "bg-amber-500" },
  low:    { label: "Low",    tone: "bg-emerald-100 text-emerald-800 border-emerald-300", icon: CheckCircle2,   dot: "bg-emerald-500" },
};

export default function PriorityChip({ priority }) {
  if (!priority) return null;
  const m = META[priority.bucket] || META.medium;
  const Icon = m.icon;
  const pct = Math.round((priority.score || 0) * 100);
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            data-testid={`priority-chip-${priority.bucket}`}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold cursor-default ${m.tone}`}
          >
            <Icon className="w-3 h-3" />
            <span className="capitalize">{m.label}</span>
            <span className="text-[10px] tabular-nums opacity-70">· {pct}</span>
            <Info className="w-2.5 h-2.5 opacity-50" />
          </div>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs p-3 text-xs" side="left">
          <div className="font-bold mb-1.5 flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${m.dot}`} />
            {m.label} priority · score {pct}
          </div>
          <div className="space-y-1">
            {(priority.reasons || []).map((r, i) => (
              <div key={i} className="flex items-start gap-1.5">
                <span className="text-slate-500 mt-0.5">•</span>
                <span>{r}</span>
              </div>
            ))}
          </div>
          {priority.factors && (
            <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700">
              <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">
                Factor breakdown
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] tabular-nums">
                <span className="text-slate-600">Weakness</span>
                <span className="text-right font-mono">{(priority.factors.portfolio_weakness * 100).toFixed(0)}%</span>
                <span className="text-slate-600">Risk</span>
                <span className="text-right font-mono">{(priority.factors.risk * 100).toFixed(0)}%</span>
                <span className="text-slate-600">AUM</span>
                <span className="text-right font-mono">{(priority.factors.aum * 100).toFixed(0)}%</span>
                <span className="text-slate-600">Recency</span>
                <span className="text-right font-mono">{(priority.factors.recency * 100).toFixed(0)}%</span>
                <span className="text-slate-600">Action urg.</span>
                <span className="text-right font-mono">{(priority.factors.recommendation_severity * 100).toFixed(0)}%</span>
              </div>
            </div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
