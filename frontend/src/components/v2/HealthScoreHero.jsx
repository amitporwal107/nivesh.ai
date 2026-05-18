/**
 * HealthScoreHero — promotes the existing health score from a tiny KPI
 * to a proper hero card with score band, grade, and sub-components.
 *
 * Consumes analytics.health_score which already has:
 *   { overall, diversification, risk, cost_efficiency, performance, grade }
 */
import React from "react";
import { Shield, TrendingUp, Briefcase, Target } from "lucide-react";
import { cn } from "@/lib/utils";

const SUB_METRICS = [
  { key: "diversification", label: "Diversification", icon: Briefcase, color: "indigo" },
  { key: "risk",            label: "Risk",            icon: Shield,    color: "amber"  },
  { key: "cost_efficiency", label: "Cost Efficiency", icon: TrendingUp,color: "emerald"},
  { key: "performance",     label: "Performance",     icon: Target,    color: "violet" },
];

function scoreBand(score) {
  if (score == null) return { tone: "Not analysed", ring: "border-white/10", bar: "bg-white/20",     text: "text-white/40" };
  if (score >= 90)   return { tone: "Excellent",   ring: "border-emerald-500/40", bar: "bg-emerald-500", text: "text-emerald-400" };
  if (score >= 75)   return { tone: "Strong",      ring: "border-violet-500/40",  bar: "bg-violet-500",  text: "text-violet-400"  };
  if (score >= 60)   return { tone: "Average",     ring: "border-amber-500/40",   bar: "bg-amber-500",   text: "text-amber-400"   };
  if (score >= 40)   return { tone: "Needs Work",  ring: "border-orange-500/40",  bar: "bg-orange-500",  text: "text-orange-400"  };
  return                  { tone: "High Risk",   ring: "border-rose-500/40",    bar: "bg-rose-500",    text: "text-rose-400"    };
}

const SUB_COLOR = {
  indigo:  { text: "text-indigo-400",  bar: "bg-indigo-500"  },
  amber:   { text: "text-amber-400",   bar: "bg-amber-500"   },
  emerald: { text: "text-emerald-400", bar: "bg-emerald-500" },
  violet:  { text: "text-violet-400",  bar: "bg-violet-500"  },
};

export default function HealthScoreHero({ analytics, loading, onAsk }) {
  const hs = analytics?.health_score;
  const overall = hs?.overall;
  const grade   = hs?.grade;
  const band    = scoreBand(overall);

  if (loading) {
    return (
      <div className="bg-[#1A1A1A] border border-white/5 p-6 rounded-2xl">
        <div className="h-5 w-40 bg-white/5 rounded animate-pulse mb-3" />
        <div className="h-12 w-32 bg-white/5 rounded animate-pulse" />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "relative overflow-hidden bg-[#1A1A1A] border rounded-2xl p-6 shadow-xl",
        band.ring,
      )}
      data-testid="health-score-hero"
    >
      <div className="absolute top-0 right-0 w-64 h-64 rounded-full blur-3xl -mr-32 -mt-32 opacity-30 bg-gradient-to-br from-current to-transparent" />

      <div className="relative z-10 flex items-start justify-between gap-6 flex-wrap">
        <div className="min-w-0 flex-1">
          <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] mb-2 font-mono">
            Portfolio Health Score
          </p>
          <div className="flex items-baseline gap-3">
            <span className={cn("text-5xl font-black tracking-tighter", band.text)}>
              {overall != null ? Math.round(overall) : "—"}
            </span>
            <span className="text-lg text-white/30 font-bold">/ 100</span>
            {grade && (
              <span className={cn("ml-2 px-2.5 py-0.5 text-xs font-black rounded-md border", band.ring, band.text)}>
                {grade}
              </span>
            )}
          </div>
          <p className={cn("text-xs font-bold mt-2 uppercase tracking-widest", band.text)}>
            {band.tone}
          </p>
        </div>

        {onAsk && overall != null && (
          <button
            onClick={onAsk}
            className="px-4 py-2 text-[10px] font-bold text-white/70 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 uppercase tracking-widest transition-all shrink-0"
            data-testid="health-ask-btn"
          >
            Why this score?
          </button>
        )}
      </div>

      {/* Sub-metric bars */}
      <div className="relative z-10 mt-6 pt-5 border-t border-white/5 grid grid-cols-2 md:grid-cols-4 gap-4">
        {SUB_METRICS.map(({ key, label, icon: Icon, color }) => {
          const v = hs?.[key];
          const c = SUB_COLOR[color];
          return (
            <div key={key} className="min-w-0">
              <div className="flex items-center gap-1.5 mb-1.5">
                <Icon className={cn("w-3 h-3 shrink-0", c.text)} />
                <p className="text-[9px] font-bold text-white/40 uppercase tracking-widest truncate">
                  {label}
                </p>
              </div>
              <div className="flex items-baseline gap-1.5 mb-1.5">
                <span className={cn("text-lg font-black", c.text)}>
                  {v != null ? Math.round(v) : "—"}
                </span>
                <span className="text-[9px] font-bold text-white/30">/100</span>
              </div>
              <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                <div
                  className={cn("h-full transition-all", c.bar)}
                  style={{ width: `${Math.min(v || 0, 100)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
