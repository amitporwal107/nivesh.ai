import React from "react";
import {
  AlertCircle, ShieldCheck, Briefcase, TrendingUp, ChevronRight, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import PersonaHero from "@/components/v2/PersonaHero";
import HealthScoreHero from "@/components/v2/HealthScoreHero";
import AIAdvisorSummary from "@/components/v2/AIAdvisorSummary";
import Top3Actions from "@/components/v2/Top3Actions";
import GoalsProgressPanel from "@/components/v2/GoalsProgressPanel";
import { getPersonaActions, getPersonaHeadline } from "@/components/v2/personaActions";

const fmtRs = (n) => {
  if (n == null || n === 0) return "—";
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`;
  if (Math.abs(n) >= 1e3) return `₹${(n / 1e3).toFixed(1)} K`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

// Maps V1 insight signal_type to icon + accent color for the feed
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

const ACTION_COLOR = {
  indigo:  "text-indigo-400",
  emerald: "text-emerald-400",
  violet:  "text-violet-400",
  rose:    "text-rose-400",
  amber:   "text-amber-400",
  blue:    "text-blue-400",
  teal:    "text-teal-400",
  orange:  "text-orange-400",
  sky:     "text-sky-400",
};

export default function V2HomeScreen({
  analytics,
  insights,
  loading,
  setScreen,
  persona,
  personaLoading,
  onPersonaChange,
}) {
  const score      = analytics?.health_score?.overall ?? analytics?.healthScore ?? null;
  const totalValue = analytics?.total_value ?? analytics?.totalValue ?? null;
  const xirr       = analytics?.xirr ?? null;
  const costLeak   = analytics?.annual_cost_leak ?? 0;
  const riskBudget = analytics?.risk_budget_used ?? analytics?.riskBudgetUsed ?? null;
  const riskLabel  = analytics?.risk_profile?.category ?? "Moderate";

  const personaKey = persona?.persona || "retail_investor";
  const headline   = getPersonaHeadline(personaKey);
  const actions    = getPersonaActions(personaKey);

  // Compact KPI grid — Health Score now lives in its own hero card,
  // so this row focuses on the remaining 3 numeric anchors.
  const kpis = [
    {
      label: "Total Wealth",
      value: totalValue ? fmtRs(totalValue) : loading ? "…" : "—",
      detail: xirr ? `${xirr > 0 ? "+" : ""}${xirr.toFixed(1)}% XIRR` : "No data yet",
      detailColor: xirr > 0 ? "text-emerald-400" : "text-white/30",
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

  // Build intelligence feed from real insights (drop the ones already
  // surfaced in Top3Actions to avoid duplication).
  const feedItems = (insights || []).slice(3, 7).map((ins) => {
    const typeKey = (ins.signal_type || ins.type || "default").toLowerCase();
    const cfg = SIGNAL_ICON[typeKey] || SIGNAL_ICON.default;
    return {
      icon: cfg.icon,
      accent: cfg.accent,
      title: ins.title || ins.headline || "Insight",
      desc: ins.description || ins.body || "",
    };
  });

  const placeholders = [
    { icon: AlertCircle, accent: "indigo",  title: "Upload your CAS to get started", desc: "Connect your portfolio to see personalised AI insights." },
    { icon: ShieldCheck, accent: "emerald", title: "Risk profile pending", desc: "Complete your risk profile to unlock full portfolio analysis." },
  ];
  const displayFeed = feedItems.length > 0 ? feedItems : placeholders;

  const askCopilot = (q) => {
    if (q) sessionStorage.setItem("v2_pending_chat_message", q);
    setScreen("copilot");
  };

  return (
    <div className="space-y-6">
      {/* Persona-aware page title */}
      <div>
        <h2 className="text-2xl font-black text-white tracking-tight">{headline.title}</h2>
        <p className="text-sm text-white/40 mt-0.5">{headline.tagline}</p>
      </div>

      {/* Persona hero — inferred from CAS, lets user override */}
      <PersonaHero
        persona={persona}
        loading={personaLoading}
        onPersonaChange={onPersonaChange}
      />

      {/* Health Score + AI Advisor Summary side-by-side on lg */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3">
          <HealthScoreHero
            analytics={analytics}
            loading={loading}
            onAsk={() => askCopilot("Explain my portfolio health score in detail — diversification, risk, cost, and performance.")}
          />
        </div>
        <div className="lg:col-span-2">
          <AIAdvisorSummary
            persona={persona}
            analytics={analytics}
            loading={loading}
            onAsk={() => askCopilot("Why is my portfolio rated this way? What's the single biggest improvement I can make?")}
            onActions={() => setScreen("insights")}
          />
        </div>
      </div>

      {/* Compact KPI row — 3 cards (Wealth, Risk, Cost) */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {kpis.map((kpi) => (
          <div
            key={kpi.label}
            className="bg-[#1A1A1A] border border-white/5 p-5 rounded-2xl shadow-xl hover:border-white/10 transition-all group overflow-hidden relative"
          >
            <div className="absolute top-0 right-0 w-20 h-20 bg-white/5 rounded-full blur-2xl -mr-10 -mt-10 group-hover:bg-indigo-500/5 transition-colors" />
            <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] mb-2 font-mono">
              {kpi.label}
            </p>
            <h3 className="text-xl font-black text-white tracking-tight relative z-10">{kpi.value}</h3>
            <p className={cn("text-[9px] font-bold mt-2 uppercase tracking-tighter", kpi.detailColor)}>
              {kpi.detail}
            </p>
          </div>
        ))}
      </div>

      {/* Top 3 Actions + Goals progress side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Top3Actions
            insights={insights}
            loading={loading}
            onClick={() => setScreen("insights")}
            onViewAll={() => setScreen("insights")}
          />
        </div>
        <div className="lg:col-span-1">
          <GoalsProgressPanel onNavigate={() => setScreen("goals")} />
        </div>
      </div>

      {/* Intelligence Feed + Persona-branded Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
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
              const cls = accentClasses[item.accent] || accentClasses.indigo;
              const Icon = item.icon;
              return (
                <div
                  key={i}
                  className={cn(
                    "p-5 rounded-2xl border hover:scale-[1.01] transition-all cursor-pointer group",
                    cls.card,
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

        {/* Persona-branded Quick Actions */}
        <div className="bg-[#1A1A1A] border border-white/5 rounded-3xl flex flex-col shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-48 h-48 bg-indigo-500/5 rounded-full blur-3xl -mr-24 -mt-24" />
          <div className="p-6 border-b border-white/5 flex items-center justify-between">
            <h4 className="text-base font-bold text-white tracking-tight">Quick Actions</h4>
            {persona?.label && (
              <span className="text-[9px] font-bold text-white/40 uppercase tracking-widest">
                for {persona.label}
              </span>
            )}
          </div>
          <div className="p-6 flex-1 space-y-3 relative z-10">
            {actions.map((a) => {
              const Icon = a.icon;
              const colorClass = ACTION_COLOR[a.color] || "text-indigo-400";
              const handleClick = () => {
                // Deep-link to a specific Insights tab when the action wants
                // one — InsightsView reads this on mount and clears it.
                if (a.tab) {
                  try { sessionStorage.setItem("v2_insights_target_tab", a.tab); }
                  catch { /* ignore */ }
                }
                setScreen(a.screen);
              };
              return (
                <button
                  key={a.label}
                  data-testid={`quick-action-${a.label.toLowerCase().replace(/\s+/g, "-")}`}
                  onClick={handleClick}
                  className="w-full flex items-center gap-4 p-4 bg-white/5 rounded-xl border border-white/5 hover:bg-white/10 hover:border-white/10 transition-all group text-left"
                >
                  <Icon className={cn("w-5 h-5 shrink-0", colorClass)} />
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
