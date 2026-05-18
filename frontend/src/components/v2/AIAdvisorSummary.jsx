/**
 * AIAdvisorSummary — composes a persona-aware "wealth advisor" paragraph
 * from existing analytics fields. No LLM call needed for v1; the persona
 * + health-score + cost-leak + xirr combination is rich enough to feel
 * personalized. Swap in an LLM-generated body later by reading
 * analytics.ai_summary or a dedicated endpoint.
 */
import React from "react";
import { Sparkles, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

const fmtRs = (n) => {
  if (n == null || n === 0) return "₹0";
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`;
  if (Math.abs(n) >= 1e3) return `₹${(n / 1e3).toFixed(1)} K`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

function buildSummary({ persona, analytics }) {
  const score    = analytics?.health_score?.overall;
  const total    = analytics?.total_value;
  const xirr     = analytics?.xirr;
  const costLeak = analytics?.annual_cost_leak;
  const personaKey = persona?.persona || "retail_investor";

  // Score-band copy
  let scoreLine;
  if (score == null) {
    scoreLine = "Upload your CAS to unlock a personalized health analysis.";
  } else if (score >= 75) {
    scoreLine = `Your portfolio is fundamentally strong (${Math.round(score)}/100).`;
  } else if (score >= 60) {
    scoreLine = `Your portfolio is on solid footing but has room to improve (${Math.round(score)}/100).`;
  } else {
    scoreLine = `Your portfolio has structural issues worth addressing (${Math.round(score)}/100).`;
  }

  // Cost / leak callout
  const leakLine = costLeak > 5000
    ? ` Switching regular-plan funds to direct could save ${fmtRs(costLeak)} a year.`
    : "";

  // XIRR callout (only if we have a real number)
  const xirrLine = xirr != null && Math.abs(xirr) > 0.5
    ? ` Your money has been compounding at ${xirr > 0 ? "+" : ""}${xirr.toFixed(1)}% CAGR.`
    : "";

  // Persona-tailored next step
  const personaNext = {
    retail_investor:      " Rebalance and goal-mapping are the two biggest levers from here.",
    mutual_fund_investor: " The biggest wins are detecting fund overlap and shifting to direct plans.",
    stock_investor:       " Focus next on sector concentration and quality scoring of your top holdings.",
    swing_trader:         " Pair this with regime monitoring and tighter position-sizing rules.",
    intraday_trader:      " Combine with daily regime calls and per-trade risk caps.",
    options_trader:       " Watch your Greeks exposure and IV percentile before the next leg.",
    mfd_advisor:          " Cross-check this against your client book for drift and suitability gaps.",
    hni_investor:         " Stress-testing and tax harvesting will move the needle most at your scale.",
    retirement_planner:   " Run a corpus-adequacy check and a glide-path to debt over the next decade.",
    tax_saver:            " March is the deadline — harvest losses and max out 80C this FY.",
    beginner_investor:    " Start with one diversified SIP and a 6-month emergency fund — that's the foundation.",
    nri_investor:         " Confirm repatriation status and currency hedge ratio before adding to positions.",
  };
  const nextLine = personaNext[personaKey] || personaNext.retail_investor;

  // First line — context anchor with value
  const valueLine = total != null && total > 0
    ? `Your portfolio of ${fmtRs(total)} is being read like a private-wealth dashboard.`
    : "";

  return [valueLine, scoreLine, leakLine + xirrLine, nextLine]
    .filter(Boolean)
    .join(" ")
    .trim();
}

export default function AIAdvisorSummary({ persona, analytics, loading, onAsk, onActions }) {
  if (loading) {
    return (
      <div className="bg-[#1A1A1A] border border-white/5 p-6 rounded-2xl">
        <div className="h-5 w-32 bg-white/5 rounded animate-pulse mb-3" />
        <div className="space-y-2">
          <div className="h-3 w-full bg-white/5 rounded animate-pulse" />
          <div className="h-3 w-5/6 bg-white/5 rounded animate-pulse" />
          <div className="h-3 w-3/4 bg-white/5 rounded animate-pulse" />
        </div>
      </div>
    );
  }

  const body = buildSummary({ persona, analytics });

  return (
    <div
      className="relative overflow-hidden bg-[#1A1A1A] border border-indigo-500/15 rounded-2xl p-6 shadow-xl"
      data-testid="ai-advisor-summary"
    >
      <div className="absolute top-0 right-0 w-48 h-48 rounded-full blur-3xl -mr-24 -mt-24 bg-gradient-to-br from-indigo-500/10 to-transparent" />

      <div className="relative z-10">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 rounded-lg bg-indigo-500/15 flex items-center justify-center border border-indigo-500/20">
            <Sparkles className="w-3.5 h-3.5 text-indigo-400" strokeWidth={2} />
          </div>
          <p className="text-[9px] font-bold text-white/40 uppercase tracking-[0.2em] font-mono">
            AI Advisor Summary
          </p>
        </div>

        <p className="text-sm text-white/80 leading-relaxed">
          {body}
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          {onActions && (
            <button
              onClick={onActions}
              className="px-3 py-1.5 text-[10px] font-bold text-white bg-indigo-500/20 hover:bg-indigo-500/30 rounded-lg border border-indigo-500/30 uppercase tracking-widest transition-all flex items-center gap-1.5"
              data-testid="advisor-see-actions"
            >
              See Recommendations <ArrowRight className="w-3 h-3" />
            </button>
          )}
          {onAsk && (
            <button
              onClick={onAsk}
              className="px-3 py-1.5 text-[10px] font-bold text-white/70 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg border border-white/10 uppercase tracking-widest transition-all"
              data-testid="advisor-ask-why"
            >
              Ask Why
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
