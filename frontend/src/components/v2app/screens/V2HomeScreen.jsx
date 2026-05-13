import React from "react";
import {
  AlertCircle, ShieldCheck, Briefcase, TrendingUp,
  ArrowUpRight, ChevronRight, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

const fmtRs = (n) => {
  if (n == null || n === 0) return "—";
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`;
  if (Math.abs(n) >= 1e3) return `₹${(n / 1e3).toFixed(1)} K`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

// Maps V1 insight signal_type to icon + accent color
const SIGNAL_ICON = {
  risk:        { icon: AlertCircle,  accent: "indigo" },
  cost:        { icon: Briefcase,    accent: "white"  },
  tax:         { icon: ShieldCheck,  accent: "emerald"},
  default:     { icon: Zap,          accent: "indigo" },
};

const accentClasses = {
  indigo:  { card: "bg-indigo-500/5 border-indigo-500/10 hover:bg-indigo-500/10",   icon: "bg-indigo-500/20 text-indigo-400"  },
  emerald: { card: "bg-emerald-500/5 border-emerald-500/10 hover:bg-emerald-500/10", icon: "bg-emerald-500/20 text-emerald-400" },
  white:   { card: "bg-white/[0.02] border-white/5 hover:bg-white/5",               icon: "bg-white/5 text-white/40"           },
};

export default function V2HomeScreen({ analytics, insights, loading, setScreen }) {
  const score      = analytics?.health_score?.overall ?? analytics?.healthScore ?? null;
  const totalValue = analytics?.total_value ?? analytics?.totalValue ?? null;
  const xirr       = analytics?.xirr ?? null;
  const costLeak   = analytics?.annual_cost_leak ?? 0;
  const riskBudget = analytics?.risk_budget_used ?? analytics?.riskBudgetUsed ?? null;
  const riskLabel  = analytics?.risk_profile?.category ?? "Moderate";

  const kpis = [
    {
      label: "Total Wealth",
      value: totalValue ? fmtRs(totalValue) : loading ? "…" : "—",
      detail: xirr ? `${xirr > 0 ? "+" : ""}${xirr.toFixed(1)}% XIRR` : "No data yet",
      detailColor: xirr > 0 ? "text-emerald-400" : "text-white/30",
    },
    {
      label: "Health Score",
      value: score != null ? `${Math.round(score)}/100` : loading ? "…" : "—",
      detail: score != null ? (score >= 75 ? "Above Peer Avg" : score >= 50 ? "Average" : "Needs Attention") : "Not analysed",
      detailColor: score >= 75 ? "text-emerald-400" : score >= 50 ? "text-amber-400" : "text-rose-400",
      progress: score,
    },
    {
      label: "Risk Budget",
      value: riskBudget != null ? `${Math.round(riskBudget)}%` : riskLabel,
      detail: riskLabel,
      detailColor: "text-amber-400",
    },
    {
      label: "Cost Savings",
      value: costLeak > 0 ? fmtRs(costLeak) : "—",
      detail: costLeak > 0 ? "Annual leak (Regular plans)" : "No leakage detected",
      detailColor: "text-indigo-400",
    },
  ];

  // Build intelligence feed from real insights
  const feedItems = (insights || []).slice(0, 4).map((ins) => {
    const typeKey = (ins.signal_type || ins.type || "default").toLowerCase();
    const cfg = SIGNAL_ICON[typeKey] || SIGNAL_ICON.default;
    return {
      icon: cfg.icon,
      accent: cfg.accent,
      title: ins.title || ins.headline || "Insight",
      desc: ins.description || ins.body || "",
    };
  });

  // Fallback cards when no insights yet
  const placeholders = [
    { icon: AlertCircle, accent: "indigo",  title: "Upload your CAS to get started", desc: "Connect your portfolio to see personalised AI insights and recommendations." },
    { icon: ShieldCheck, accent: "emerald", title: "Risk profile pending", desc: "Complete your risk profile to unlock full portfolio analysis and rebalancing advice." },
  ];
  const displayFeed = feedItems.length > 0 ? feedItems : placeholders;

  return (
    <div className="space-y-8">
      {/* KPI grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map((kpi) => (
          <div
            key={kpi.label}
            className="bg-[#1A1A1A] border border-white/5 p-5 rounded-2xl shadow-xl hover:border-white/10 transition-all group overflow-hidden relative"
          >
            <div className="absolute top-0 right-0 w-20 h-20 bg-white/5 rounded-full blur-2xl -mr-10 -mt-10 group-hover:bg-indigo-500/5 transition-colors" />
            <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] mb-2 font-mono">
              {kpi.label}
            </p>
            <div className="flex items-end justify-between relative z-10">
              <h3 className="text-xl font-black text-white tracking-tight">{kpi.value}</h3>
              {kpi.progress != null && (
                <div className="w-10 bg-white/5 h-1.5 rounded-full overflow-hidden mb-1 ml-2">
                  <div
                    className="h-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.4)]"
                    style={{ width: `${Math.min(kpi.progress, 100)}%` }}
                  />
                </div>
              )}
            </div>
            <p className={cn("text-[9px] font-bold mt-2 uppercase tracking-tighter", kpi.detailColor)}>
              {kpi.detail}
            </p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Intelligence feed */}
        <div className="lg:col-span-2 bg-[#1A1A1A] border border-white/5 rounded-3xl flex flex-col shadow-2xl overflow-hidden">
          <div className="p-6 border-b border-white/5 flex justify-between items-center">
            <h4 className="text-base font-bold text-white tracking-tight">Intelligence Feed</h4>
            {feedItems.length > 0 && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 bg-rose-500/10 text-rose-400 text-[9px] font-bold rounded-lg border border-rose-500/20 uppercase tracking-widest">
                {feedItems.length} Signal{feedItems.length !== 1 ? "s" : ""}
              </div>
            )}
          </div>
          <div className="p-6 space-y-4 flex-1">
            {displayFeed.map((item, i) => {
              const cls = accentClasses[item.accent];
              const Icon = item.icon;
              return (
                <div
                  key={i}
                  className={cn(
                    "p-5 rounded-2xl border hover:scale-[1.01] transition-all cursor-pointer group",
                    cls.card
                  )}
                  onClick={() => setScreen("insights")}
                >
                  <div className="flex items-start gap-4">
                    <div className={cn("p-2.5 rounded-xl shrink-0 group-hover:scale-110 transition-transform", cls.icon)}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <div>
                      <p className="font-bold text-white text-sm tracking-tight mb-1">{item.title}</p>
                      {item.desc && (
                        <p className="text-xs text-white/40 leading-relaxed font-medium line-clamp-2">
                          {item.desc}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="p-4 border-t border-white/5 flex justify-end gap-6">
            <button
              onClick={() => setScreen("insights")}
              className="text-[9px] font-bold text-indigo-400 uppercase tracking-[0.2em] hover:text-indigo-300 transition-colors"
            >
              View All Insights
            </button>
          </div>
        </div>

        {/* Sentiment / quick actions */}
        <div className="bg-[#1A1A1A] border border-white/5 rounded-3xl flex flex-col shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-48 h-48 bg-indigo-500/5 rounded-full blur-3xl -mr-24 -mt-24" />
          <div className="p-6 border-b border-white/5">
            <h4 className="text-base font-bold text-white tracking-tight">Quick Actions</h4>
          </div>
          <div className="p-6 flex-1 space-y-3 relative z-10">
            {[
              { label: "AI Copilot Chat",       icon: TrendingUp,  screen: "copilot",    color: "text-indigo-400", desc: "Ask anything about your portfolio" },
              { label: "Portfolio Analysis",    icon: Briefcase,   screen: "portfolio",  color: "text-emerald-400", desc: "Holdings, returns, allocation" },
              { label: "Market Intelligence",   icon: ArrowUpRight, screen: "markets",   color: "text-amber-400",  desc: "Regime · Sectors · Trade ideas" },
              { label: "Investment Goals",      icon: ShieldCheck, screen: "goals",      color: "text-rose-400",   desc: "Track your financial goals" },
            ].map((a) => {
              const Icon = a.icon;
              return (
                <button
                  key={a.label}
                  onClick={() => setScreen(a.screen)}
                  className="w-full flex items-center gap-4 p-4 bg-white/5 rounded-xl border border-white/5 hover:bg-white/10 hover:border-white/10 transition-all group text-left"
                >
                  <Icon className={cn("w-5 h-5 shrink-0", a.color)} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold text-white">{a.label}</p>
                    <p className="text-[10px] text-white/30">{a.desc}</p>
                  </div>
                  <ChevronRight className="w-4 h-4 text-white/10 group-hover:text-indigo-400 transition-all shrink-0" />
                </button>
              );
            })}
          </div>
          <div className="p-4 border-t border-white/5">
            <button
              onClick={() => setScreen("markets")}
              className="w-full text-[9px] font-bold text-indigo-400 uppercase tracking-[0.2em] py-2 rounded-xl hover:bg-white/5 transition-all text-center"
            >
              Enter Market Intelligence Hub
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
