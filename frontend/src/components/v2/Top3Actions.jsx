/**
 * Top3Actions — surfaces the 3 highest-impact actions from existing
 * insights data. Ranks by impact (high → medium → low) then by type
 * (opportunity → warning → action → info).
 */
import React from "react";
import {
  Zap, AlertTriangle, ArrowRight, Sparkles, TrendingUp, Shield,
} from "lucide-react";
import { cn } from "@/lib/utils";

const TYPE_META = {
  opportunity: { icon: Sparkles,       color: "emerald", rank: 1 },
  warning:     { icon: AlertTriangle,  color: "amber",   rank: 2 },
  action:      { icon: Zap,            color: "indigo",  rank: 3 },
  risk:        { icon: Shield,         color: "rose",    rank: 2 },
  info:        { icon: TrendingUp,     color: "white",   rank: 4 },
  default:     { icon: Zap,            color: "indigo",  rank: 5 },
};

const IMPACT_RANK = { high: 1, medium: 2, low: 3 };

const COLORS = {
  emerald: { bg: "bg-emerald-500/10",  border: "border-emerald-500/15", icon: "text-emerald-400", chip: "bg-emerald-500/15 text-emerald-300" },
  amber:   { bg: "bg-amber-500/10",    border: "border-amber-500/15",   icon: "text-amber-400",   chip: "bg-amber-500/15 text-amber-300"   },
  indigo:  { bg: "bg-indigo-500/10",   border: "border-indigo-500/15",  icon: "text-indigo-400",  chip: "bg-indigo-500/15 text-indigo-300"  },
  rose:    { bg: "bg-rose-500/10",     border: "border-rose-500/15",    icon: "text-rose-400",    chip: "bg-rose-500/15 text-rose-300"    },
  white:   { bg: "bg-white/[0.03]",    border: "border-white/10",       icon: "text-white/60",    chip: "bg-white/10 text-white/70"        },
};

function rankInsights(insights) {
  return [...(insights || [])]
    .map((ins) => {
      const type = (ins.signal_type || ins.type || "default").toLowerCase();
      const meta = TYPE_META[type] || TYPE_META.default;
      const impactKey = (ins.impact || ins.priority || "medium").toLowerCase();
      return {
        ins,
        type,
        meta,
        impactRank: IMPACT_RANK[impactKey] ?? 9,
      };
    })
    .sort((a, b) => {
      if (a.impactRank !== b.impactRank) return a.impactRank - b.impactRank;
      return a.meta.rank - b.meta.rank;
    })
    .slice(0, 3);
}

export default function Top3Actions({ insights, loading, onClick, onViewAll }) {
  if (loading) {
    return (
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5">
        <div className="h-4 w-32 bg-white/5 rounded animate-pulse mb-4" />
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-white/5 rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  const ranked = rankInsights(insights);

  return (
    <div
      className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl"
      data-testid="top-3-actions"
    >
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-black text-white tracking-tight flex items-center gap-2">
          <Zap className="w-4 h-4 text-amber-400" />
          Top Recommended Actions
        </h4>
        {ranked.length > 0 && onViewAll && (
          <button
            onClick={onViewAll}
            className="text-[9px] font-bold text-indigo-400 uppercase tracking-[0.2em] hover:text-indigo-300 transition-colors"
          >
            View All
          </button>
        )}
      </div>

      {ranked.length === 0 ? (
        <div className="py-8 text-center">
          <Sparkles className="w-8 h-8 text-white/20 mx-auto mb-2" />
          <p className="text-xs text-white/40">
            No urgent actions — your portfolio looks healthy.
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {ranked.map(({ ins, type, meta }, i) => {
            const Icon = meta.icon;
            const c = COLORS[meta.color] || COLORS.indigo;
            return (
              <button
                key={i}
                onClick={() => onClick?.(ins)}
                data-testid={`top-action-${i}`}
                className={cn(
                  "w-full flex items-start gap-3 p-3.5 rounded-xl border text-left transition-all group",
                  c.bg, c.border,
                  "hover:scale-[1.01] hover:border-white/20",
                )}
              >
                <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center shrink-0 border", c.bg, c.border)}>
                  <Icon className={cn("w-4 h-4", c.icon)} strokeWidth={2} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                    <p className="text-xs font-bold text-white truncate">{ins.title || "Untitled action"}</p>
                    <span className={cn("text-[8px] font-bold px-1.5 py-0.5 rounded uppercase tracking-widest", c.chip)}>
                      {type}
                    </span>
                  </div>
                  <p className="text-[11px] text-white/50 leading-snug line-clamp-2">
                    {ins.action || ins.description || ins.body || ""}
                  </p>
                </div>
                <ArrowRight className="w-3.5 h-3.5 text-white/20 group-hover:text-indigo-400 transition-colors shrink-0 mt-1" />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
