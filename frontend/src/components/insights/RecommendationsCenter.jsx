import React, { useMemo, useState, useCallback } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle, TrendingUp, Target, ChevronDown, ChevronRight,
  CheckCircle2, Circle, MessageSquare, Sparkles, Layers, Coins,
  Building2, Shield, Wallet, RefreshCw, AlertCircle, ArrowRight,
} from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import OptimizationCard from "@/components/insights/OptimizationCard";
import WidgetRenderer from "@/components/copilot/widgets/WidgetRenderer";
import { recommendationToInsightEnvelope } from "@/components/insights/recommendationToInsightCard";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Feature flag — when true, every recommendation card on the Insights
// page renders through the unified InsightCardWidget instead of the
// bespoke per-insight JSX. Toggle via localStorage:
//
//   localStorage.setItem("nivesh.unified_card_layout", "1")  → on
//   localStorage.removeItem("nivesh.unified_card_layout")    → off
//
// Kept opt-in so we can A/B against the current layout before flipping
// the default — RecommendationsCenter has rich mark-as-done / theme
// grouping behaviour that we want to confirm survives unchanged.
const UNIFIED_CARD_LAYOUT = (() => {
  try {
    return typeof window !== "undefined" &&
      window.localStorage?.getItem("nivesh.unified_card_layout") === "1";
  } catch {
    return false;
  }
})();

// ── Severity + theme visual config ──────────────────────────────────────
const SEVERITY = {
  critical:     { color: "#EF4444", bg: "bg-red-500/10",      border: "border-red-500/20",      label: "Critical",     icon: AlertTriangle },
  important:    { color: "#F59E0B", bg: "bg-amber-500/10",    border: "border-amber-500/20",    label: "Important",    icon: AlertCircle },
  optimization: { color: "#3B82F6", bg: "bg-blue-500/10",     border: "border-blue-500/20",     label: "Opportunity",  icon: TrendingUp },
  positive:     { color: "#10B981", bg: "bg-emerald-500/10",  border: "border-emerald-500/20",  label: "Good",         icon: Target },
};

const THEME_ICON = {
  duplication:           Layers,
  overlap:               Layers,
  amc_concentration:     Building2,
  category_concentration: Shield,
  sector_risk:           Shield,
  drift:                 RefreshCw,
  allocation_gap:        Wallet,
  cost:                  Coins,
  other:                 Sparkles,
};

const TAB_DEFS = [
  { id: "all",          label: "All",           sev: null },
  { id: "critical",     label: "Critical",      sev: "critical" },
  { id: "important",    label: "Important",     sev: "important" },
  { id: "opportunities",label: "Opportunities", sev: "optimization" },
  { id: "completed",    label: "Completed",     sev: "_completed" },
];

const formatRs = (v) => {
  const n = Number(v) || 0;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(2)}L`;
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}K`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const SEV_ORDER = { critical: 0, important: 1, optimization: 2, positive: 3 };

const THEME_LABEL = {
  duplication: "Duplicate Funds", overlap: "Fund Overlap",
  amc_concentration: "AMC Concentration", category_concentration: "Category Concentration",
  sector_risk: "Sector Risk", drift: "Allocation Drift",
  allocation_gap: "Allocation Gaps", cost: "Cost Leakage", other: "Other",
};

// Works for both backend-enriched insights (.theme/.severity present) and
// unenriched basicInsights (only .title/.type/.impact available).
const deriveSeverity = (insight) => {
  if (insight.severity && SEVERITY[insight.severity]) return insight.severity;
  const itype = (insight.type || "").toLowerCase();
  const impact = (insight.impact || "").toLowerCase();
  if (itype === "success") return "positive";
  if (itype === "alert" || (itype === "warning" && impact === "high")) return "critical";
  if (itype === "opportunity" && impact === "high") return "important";
  if (itype === "opportunity" || impact === "low" || itype === "info") return "optimization";
  return "important";
};

// Parses title text directly when backend theme is absent, so basicInsights
// (which never went through _enrich_insights) classify correctly.
const deriveTheme = (insight) => {
  if (insight.theme && insight.theme !== "other") return insight.theme;
  const t = (insight.title || insight.headline || "").toLowerCase();
  const d = (insight.description || insight.detail || insight.action || "").toLowerCase();
  const text = `${t} ${d}`;
  if (/overlap\s+\d+%/.test(t) || t.includes("same fund") || t.includes("consolidate")) return "duplication";
  if (t.includes("overlap") || d.includes("overlap")) return "overlap";
  if (t.includes("amc") || t.includes("fund house") || /holds.*%.*of.*mf/i.test(text)) return "amc_concentration";
  if (t.includes("category concentration") || text.includes("mf corpus") || text.includes("guardrail")) return "category_concentration";
  if (t.includes("sector") && !t.includes("cap")) return "sector_risk";
  if (t.includes("drift") || t.includes("rebalance") || (t.includes("equity") && t.includes("target"))) return "drift";
  if (t.includes("direct") || t.includes("regular plan") || t.includes("expense") || t.includes("switch to direct")) return "cost";
  if (t.includes("debt") || t.includes("allocation") || t.includes("gold") || t.includes("emergency")) return "allocation_gap";
  return "other";
};

const deriveThemeLabel = (insight) => insight.theme_label || THEME_LABEL[deriveTheme(insight)] || "Other";

const matchHoldings = (insight, perfCards) => {
  if (!perfCards || perfCards.length === 0) return [];
  const txt = `${insight.title || insight.headline || ""} ${insight.description || insight.detail || ""} ${insight.action || ""}`.toLowerCase();
  return perfCards.filter((h) => {
    const name = (h.name || "").toLowerCase();
    const sector = (h.sector || "").toLowerCase();
    const type = (h.asset_type || "").toLowerCase();
    if (name.length > 10 && txt.includes(name.slice(0, 12))) return true;
    if (txt.includes("gold") && (sector.includes("gold") || type === "gold")) return true;
    if (txt.includes("debt") && (type.includes("debt") || sector.includes("debt"))) return true;
    if (txt.includes("small cap") && sector.includes("small cap")) return true;
    if (txt.includes("regular") && name.includes("regular")) return true;
    if (txt.includes("mutual fund") && type === "mutual_fund") return true;
    return false;
  }).slice(0, 8);
};

// ── Hero: "Here are your N most important actions" ─────────────────────
// Reads from locally-computed counts — never from backend summary — so it
// works correctly even before the user has run a full analysis.
// ── Hero: "₹X Lakhs can be optimized" — the spec's optimisation engine framing.
// Disabled in the AI Overview path (2026-05-20 directive) — the Action Matrix's
// Top-5 banner upstream covers the same framing. Prefix retained so lint
// recognises this as deliberately-unused; restore by removing the underscore.
const _HeroSummary = ({ counts, summary, totalInsights, completedCount, topActions, onScrollToActions }) => {
  const { critical, important, opportunities: opps } = counts;

  // Optimisation aggregates (only present once backend returns enriched summary)
  const optimizableRs   = Number(summary?.total_optimizable_rs || 0);
  const annualSavingsRs = Number(summary?.potential_fee_savings_annual_rs || 0);
  const wealth10yRs     = Number(summary?.projected_wealth_gain_10y_rs || 0);
  const currentFunds    = Number(summary?.current_fund_count || 0);
  const targetFunds     = Number(summary?.target_fund_count || 0);
  const divCurrent      = summary?.diversification_score_current;
  const divTarget       = summary?.diversification_score_target;
  const dupCount        = Number(summary?.duplicate_fund_count || 0);

  const hasOptimization = optimizableRs > 0 || annualSavingsRs > 0 || dupCount > 0;

  // Headline — leads with money optimised when we have it, falls back to count-based copy
  let headline;
  let subtext;
  if (hasOptimization) {
    headline = `${formatRs(optimizableRs)} can be optimised`;
    const parts = [];
    if (annualSavingsRs > 0) parts.push(`save ${formatRs(annualSavingsRs)}/yr in fees`);
    if (currentFunds && targetFunds && currentFunds > targetFunds) {
      parts.push(`simplify ${currentFunds} → ${targetFunds} funds`);
    }
    if (divCurrent && divTarget && divTarget > divCurrent) {
      parts.push(`diversification ${divCurrent} → ${divTarget}`);
    }
    subtext = parts.length ? parts.join(" · ") : "Consolidate duplicate funds to unlock long-term gains.";
  } else if (critical > 0) {
    headline = `${critical} critical action${critical === 1 ? "" : "s"} need your attention`;
    subtext = `Plus ${important} important and ${opps} optimisation${opps === 1 ? "" : "s"}.`;
  } else if (important > 0) {
    headline = `${important} important recommendation${important === 1 ? "" : "s"} to review`;
    subtext = `Plus ${opps} optimisation opportunit${opps === 1 ? "y" : "ies"}.`;
  } else if (opps > 0) {
    headline = `${opps} optimisation opportunit${opps === 1 ? "y" : "ies"} detected`;
    subtext = "No critical issues — focus on these to tune your portfolio.";
  } else {
    headline = "Portfolio looks healthy";
    subtext = "No high-priority issues found.";
  }

  return (
    <div className="rounded-2xl bg-gradient-to-br from-amber-50 via-orange-50 to-rose-50 dark:from-amber-500/10 dark:via-orange-500/5 dark:to-rose-500/10 border border-amber-200/60 dark:border-amber-500/20 p-5 md:p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="w-4 h-4 text-amber-600" />
            <p className="text-[10px] font-bold tracking-wider uppercase text-amber-700 dark:text-amber-400">
              Portfolio Optimisation Opportunities
            </p>
          </div>
          <h2 className="text-2xl md:text-3xl font-bold text-slate-900 dark:text-white leading-tight" data-testid="rec-hero-headline">
            {headline}
          </h2>
          <p className="text-sm text-slate-500 dark:text-zinc-500 mt-1">{subtext}</p>

          {/* Top-3 action chips */}
          {topActions.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">
                Start with these
              </p>
              {topActions.map((ins, i) => {
                const sev = SEVERITY[deriveSeverity(ins)] || SEVERITY.important;
                const ThemeIcon = THEME_ICON[deriveTheme(ins)] || Sparkles;
                const title = ins.title || ins.headline || "";
                return (
                  <button
                    key={ins.insight_id || `top-${i}`}
                    type="button"
                    onClick={onScrollToActions}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl bg-white/70 dark:bg-zinc-900/50 border border-white/60 dark:border-white/5 hover:bg-white dark:hover:bg-zinc-900/80 transition text-left group"
                  >
                    <span
                      className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 text-[10px] font-bold text-white"
                      style={{ backgroundColor: sev.color }}
                    >
                      {i + 1}
                    </span>
                    <ThemeIcon className="w-3.5 h-3.5 flex-shrink-0 text-slate-400" />
                    <span className="text-xs font-medium text-slate-700 dark:text-zinc-300 flex-1 truncate">
                      {title}
                    </span>
                    <ArrowRight className="w-3 h-3 text-slate-400 flex-shrink-0 group-hover:translate-x-0.5 transition-transform" />
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {totalInsights > 0 && (
          <div className="flex-shrink-0 text-right">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Progress</p>
            <p className="text-2xl font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
              {completedCount}/{totalInsights}
            </p>
            <div className="w-24 h-1.5 rounded-full bg-slate-200/60 dark:bg-zinc-700/40 mt-1.5 overflow-hidden">
              <div
                className="h-full bg-emerald-500 transition-all"
                style={{ width: totalInsights > 0 ? `${(completedCount / totalInsights) * 100}%` : "0%" }}
              />
            </div>
            <p className="text-[10px] text-slate-400 mt-1">
              {totalInsights > 0 ? `${Math.round((completedCount / totalInsights) * 100)}% done` : ""}
            </p>
          </div>
        )}
      </div>

      {/* Optimisation metric tiles when backend provides aggregates,
          severity counts otherwise */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-5">
        {hasOptimization ? (
          <>
            <StatTile
              label="Annual savings"
              value={annualSavingsRs > 0 ? `${formatRs(annualSavingsRs)}` : "—"}
              sublabel={annualSavingsRs > 0 ? "in fees" : null}
              accent="#10B981"
              testid="hero-tile-savings"
            />
            <StatTile
              label="Funds to consolidate"
              value={dupCount > 0 ? dupCount : (currentFunds && targetFunds ? `${currentFunds} → ${targetFunds}` : "—")}
              sublabel={dupCount > 0 ? "duplicates" : null}
              accent="#3B82F6"
              testid="hero-tile-funds"
            />
            <StatTile
              label="Diversification"
              value={(divCurrent != null && divTarget != null && divTarget > divCurrent) ? `${divCurrent} → ${divTarget}` : "—"}
              sublabel={(divCurrent != null && divTarget != null) ? `+${Math.max(0, divTarget - divCurrent)} pts` : null}
              accent="#8B5CF6"
              testid="hero-tile-diversification"
            />
            <StatTile
              label="10Y wealth gain"
              value={wealth10yRs > 0 ? formatRs(wealth10yRs) : "—"}
              sublabel={wealth10yRs > 0 ? "@ 12% CAGR" : null}
              accent="#F59E0B"
              testid="hero-tile-wealth"
            />
          </>
        ) : (
          <>
            <StatTile label="Critical"      value={critical > 0 ? critical : "—"}          accent="#EF4444" />
            <StatTile label="Important"     value={important > 0 ? important : "—"}        accent="#F59E0B" />
            <StatTile label="Opportunities" value={opps > 0 ? opps : "—"}                  accent="#3B82F6" />
            <StatTile label="Resolved"      value={completedCount > 0 ? completedCount : "—"} accent="#10B981" />
          </>
        )}
      </div>

      {/* Status footer — severity breakdown stays visible even when opt numbers show */}
      {hasOptimization && (critical > 0 || important > 0 || opps > 0) && (
        <p className="text-[11px] text-slate-500 dark:text-zinc-500 mt-3 flex flex-wrap gap-x-3 gap-y-1">
          {critical > 0 && <span><span className="font-semibold text-red-500">{critical}</span> critical</span>}
          {important > 0 && <span><span className="font-semibold text-amber-500">{important}</span> important</span>}
          {opps > 0 && <span><span className="font-semibold text-blue-500">{opps}</span> opportunities</span>}
          {completedCount > 0 && <span><span className="font-semibold text-emerald-500">{completedCount}</span> resolved</span>}
        </p>
      )}
    </div>
  );
};

const StatTile = ({ label, value, accent, sublabel, testid }) => (
  <div className="bg-white/70 dark:bg-zinc-900/40 rounded-xl px-3 py-2.5 border border-white/40 dark:border-white/5" data-testid={testid}>
    <p className="text-[9px] font-bold tracking-wider uppercase text-slate-500 dark:text-zinc-500">{label}</p>
    <p className="text-lg font-bold mt-0.5 leading-tight" style={{ color: accent, fontFamily: "'Outfit', sans-serif" }}>
      {value}
    </p>
    {sublabel && (
      <p className="text-[9px] text-slate-400 dark:text-zinc-500 mt-0.5">{sublabel}</p>
    )}
  </div>
);

// ── Single insight card ───────────────────────────────────────────────
const InsightCard = ({ insight, perfCards, onMarkDone, onAsk, onUnmark, fmt, highlight }) => {
  // All hooks first (rules of hooks) — both paths read them so the
  // unified-layout early return doesn't disrupt the call order.
  const [open, setOpen] = useState(false);
  const [marking, setMarking] = useState(false);
  const affectedHoldings = useMemo(
    () => matchHoldings(insight, perfCards),
    [insight, perfCards],
  );

  // Unified-layout opt-in path: render the insight as an InsightCardWidget
  // envelope so visual chrome matches the Copilot chat. Action chips wire
  // back to the same callbacks the legacy card uses (mark/ask/unmark).
  if (UNIFIED_CARD_LAYOUT) {
    const envelope = recommendationToInsightEnvelope(insight);
    const handleAction = (actionId) => {
      if (actionId === "rec_ask") {
        const prompt = insight.action
          ? `Tell me more about this recommendation: "${insight.title}". Specifically — ${insight.action}`
          : `Explain this insight in detail: ${insight.title}`;
        onAsk(prompt);
      } else if (actionId === "rec_mark_done" && insight.insight_id) {
        onMarkDone(insight.insight_id);
      } else if (actionId === "rec_unmark" && insight.insight_id) {
        onUnmark(insight.insight_id);
      }
    };
    return (
      <div
        data-testid={`rec-card-${insight.insight_id || insight.title}`}
        className={`${highlight ? "ring-2 ring-amber-400/40 rounded-[var(--cp-radius-lg)]" : ""} ${insight.completed ? "opacity-60" : ""}`}
      >
        <WidgetRenderer envelope={envelope} embedded="insights" onAction={handleAction} />
      </div>
    );
  }

  const sev = SEVERITY[deriveSeverity(insight)] || SEVERITY.important;
  const SevIcon = sev.icon;
  const ThemeIcon = THEME_ICON[deriveTheme(insight)] || THEME_ICON.other;
  const benefit = insight.benefit || {};
  const completed = !!insight.completed;
  const title = insight.title || insight.headline || "";
  const description = insight.description || insight.detail || "";
  // `affectedHoldings` is already computed in the hooks block above.

  const handleMark = async (e) => {
    e.stopPropagation();
    if (!insight.insight_id) return;
    setMarking(true);
    try {
      if (completed) {
        await onUnmark(insight.insight_id);
      } else {
        await onMarkDone(insight.insight_id);
      }
    } finally {
      setMarking(false);
    }
  };

  const handleAsk = (e) => {
    e.stopPropagation();
    const prompt =
      insight.action
        ? `Tell me more about this recommendation: "${insight.title}". Specifically — ${insight.action}`
        : `Explain this insight in detail: ${insight.title}`;
    onAsk(prompt);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={`rounded-xl border overflow-hidden transition-opacity ${sev.border} ${highlight ? "ring-2 ring-amber-400/40" : ""} ${completed ? "opacity-60" : ""}`}
      data-testid={`rec-card-${insight.insight_id || title}`}
    >
      <div
        className={`p-4 cursor-pointer ${sev.bg} hover:opacity-90 transition-opacity`}
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-start gap-3">
          <SevIcon className="w-4 h-4 flex-shrink-0 mt-1" style={{ color: sev.color }} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className={`text-sm font-semibold text-slate-900 dark:text-white ${completed ? "line-through" : ""}`}>
                {title}
              </p>
              <span
                className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                style={{ backgroundColor: `${sev.color}22`, color: sev.color }}
              >
                {sev.label}
              </span>
              <span className="inline-flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded bg-slate-100 dark:bg-zinc-800/60 text-slate-600 dark:text-zinc-400">
                <ThemeIcon className="w-2.5 h-2.5" />
                {deriveThemeLabel(insight)}
              </span>
            </div>

            {benefit.summary && (
              <p className="text-xs font-medium text-emerald-700 dark:text-emerald-400 mt-1.5">
                {benefit.summary}
              </p>
            )}

            <p className="text-xs text-slate-500 dark:text-zinc-500 mt-1 line-clamp-2">
              {description}
            </p>

            {/* AMC-concentration cards get an explicit "How to reduce"
                next-step line — the spec said the card states the fact
                ("HDFC holds 44%") but never tells the user what to do. */}
            {deriveTheme(insight) === "amc_concentration" && _amcReductionHint(insight) && (
              <p className="text-xs text-slate-700 dark:text-zinc-300 mt-1.5 leading-relaxed">
                {_amcReductionHint(insight)}
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={handleMark}
            disabled={marking || !insight.insight_id}
            title={completed ? "Unmark as done" : "Mark as done"}
            className="flex-shrink-0 p-1 rounded-md hover:bg-white/40 dark:hover:bg-white/5 transition disabled:opacity-50"
            data-testid={`rec-mark-${insight.insight_id || insight.title}`}
          >
            {completed
              ? <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              : <Circle className="w-5 h-5 text-slate-400" />}
          </button>
          <ChevronDown
            className={`w-4 h-4 text-slate-400 flex-shrink-0 mt-1 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </div>
      </div>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="bg-white dark:bg-[#121212] border-t border-slate-100 dark:border-white/5"
          >
            <div className="p-4 space-y-3">
              {description && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Details</p>
                  <p className="text-xs text-slate-600 dark:text-zinc-400 leading-relaxed">{description}</p>
                </div>
              )}

              {insight.action && (
                <div className="p-3 bg-emerald-50 dark:bg-emerald-900/15 rounded-lg border border-emerald-200 dark:border-emerald-500/20">
                  <p className="text-[10px] font-bold tracking-wider uppercase text-emerald-600 mb-1">Recommended Action</p>
                  <p className="text-xs text-emerald-700 dark:text-emerald-300 font-medium">{insight.action}</p>
                </div>
              )}

              {/* Expected impact chips */}
              {(benefit.fee_savings_annual_rs > 0 || benefit.health_score_delta > 0 || benefit.simplicity_delta_pct > 0) && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Expected Impact</p>
                  <div className="flex flex-wrap gap-1.5">
                    {benefit.fee_savings_annual_rs > 0 && (
                      <span className="text-[10px] px-2 py-1 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 font-medium">
                        Fee savings: {formatRs(benefit.fee_savings_annual_rs)}/yr
                      </span>
                    )}
                    {benefit.health_score_delta > 0 && (
                      <span className="text-[10px] px-2 py-1 rounded-full bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 font-medium">
                        Health score: +{benefit.health_score_delta}
                      </span>
                    )}
                    {benefit.simplicity_delta_pct > 0 && (
                      <span className="text-[10px] px-2 py-1 rounded-full bg-purple-50 dark:bg-purple-500/10 text-purple-700 dark:text-purple-400 font-medium">
                        Simplicity: −{benefit.simplicity_delta_pct}% holdings
                      </span>
                    )}
                    {benefit.tax_savings_rs > 0 && (
                      <span className="text-[10px] px-2 py-1 rounded-full bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 font-medium">
                        Tax: {formatRs(benefit.tax_savings_rs)}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {insight.current_value && insight.target_value && (
                <div className="flex gap-3">
                  <div className="flex-1 p-2 rounded-lg bg-red-50 dark:bg-red-500/5 border border-red-200 dark:border-red-500/20">
                    <p className="text-[9px] font-bold uppercase text-red-500">Current</p>
                    <p className="text-xs font-medium text-slate-700 dark:text-zinc-300 mt-0.5">{insight.current_value}</p>
                  </div>
                  <div className="flex-1 p-2 rounded-lg bg-emerald-50 dark:bg-emerald-500/5 border border-emerald-200 dark:border-emerald-500/20">
                    <p className="text-[9px] font-bold uppercase text-emerald-600">Target</p>
                    <p className="text-xs font-medium text-slate-700 dark:text-zinc-300 mt-0.5">{insight.target_value}</p>
                  </div>
                </div>
              )}

              {insight.affected_funds && insight.affected_funds.length > 0 && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Affected Funds</p>
                  <div className="flex flex-wrap gap-1.5">
                    {insight.affected_funds.map((f, fi) => (
                      <span key={`af-${fi}`} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800/50 text-slate-600 dark:text-zinc-400">
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {affectedHoldings.length > 0 && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Holdings Impact</p>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {affectedHoldings.map((h, hi) => (
                      <div key={`aff-${hi}`} className="flex items-center justify-between py-1 px-2 bg-slate-50 dark:bg-[#1A1A1A] rounded-lg text-xs">
                        <span className="text-slate-700 dark:text-zinc-300 truncate flex-1">{h.name}</span>
                        <span className={`font-medium ml-2 ${h.pct_return >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                          {h.pct_return >= 0 ? "+" : ""}{h.pct_return}%
                        </span>
                        <span className="text-slate-500 ml-2">{fmt ? fmt(h.current_value) : formatRs(h.current_value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Phase B/C/D: Keep / Exit / Redeploy / Simulate panel for duplicate-pair insights */}
              {insight.insight_id && ["duplication", "overlap"].includes(deriveTheme(insight)) && (
                <OptimizationCard insightId={insight.insight_id} />
              )}

              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={handleAsk}
                  className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-zinc-800/60 text-slate-700 dark:text-zinc-300 hover:bg-slate-200 dark:hover:bg-zinc-700/60 font-medium"
                  data-testid={`rec-ask-${insight.insight_id || insight.title}`}
                >
                  <MessageSquare className="w-3 h-3" /> Ask Nivesh
                </button>
                <button
                  type="button"
                  onClick={handleMark}
                  disabled={marking || !insight.insight_id}
                  className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium disabled:opacity-50 ${
                    completed
                      ? "bg-slate-100 dark:bg-zinc-800/60 text-slate-600 dark:text-zinc-400"
                      : "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/25"
                  }`}
                >
                  {completed ? <Circle className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
                  {completed ? "Unmark" : "Mark Done"}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

// ── Theme group (collapsible) ─────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────
// Duplicate / Overlap collapsed views
//
// Pre-PR: every pair was rendered as its own InsightCard inline → 40+
// stacked rows in the "Duplicate Funds" theme made the page unscrollable.
// Post-PR: the theme collapses into 1-2 summary cards; clicking opens a
// modal listing the underlying pairs. Matches the user directive
// 2026-05-20: "summarize like this 10 funds are duplicated with regular
// and direct schemes; click on duplicate funds displays in separate popup".
// ─────────────────────────────────────────────────────────────────────

/** Normalise a fund name so we can match a Regular plan against its Direct
 *  counterpart. Strips suffixes like " - Direct - Growth", " Direct Plan",
 *  " - Growth", etc., plus extra whitespace. Case-insensitive. */
const _normaliseFundName = (s) => {
  if (!s) return "";
  return s
    .toLowerCase()
    .replace(/\s*[-–]\s*direct(\s+plan)?\b/gi, "")
    .replace(/\s*[-–]\s*regular(\s+plan)?\b/gi, "")
    .replace(/\s+direct(\s+plan)?\b/gi, "")
    .replace(/\s+regular(\s+plan)?\b/gi, "")
    .replace(/\s*[-–]\s*growth\b/gi, "")
    .replace(/\s+growth\b/gi, "")
    .replace(/\s*[-–]\s*idcw\b/gi, "")
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
};

/** Decide whether the two fund names on a duplicate-funds insight are the
 *  same fund's Regular vs Direct plan. Heuristic: their normalised forms
 *  match AND at least one of the original names mentions "Direct". */
const isRegularVsDirect = (insight) => {
  const funds = insight?.affected_funds || [];
  if (funds.length < 2) {
    // Some payloads stuff both fund names into the title:
    //   "Nippon India Small Cap Growth and Nippon India Small Cap Direct Growth overlap 97%"
    const m = (insight?.title || "").match(/^(.+?)\s+and\s+(.+?)\s+overlap/i);
    if (!m) return false;
    return _checkRegDirPair(m[1], m[2]);
  }
  return _checkRegDirPair(funds[0], funds[1]);
};

const _checkRegDirPair = (a, b) => {
  if (!a || !b) return false;
  const norm = _normaliseFundName(a) === _normaliseFundName(b);
  const oneIsDirect =
    /\bdirect\b/i.test(a || "") || /\bdirect\b/i.test(b || "");
  return norm && oneIsDirect;
};

/** Sum of `fee_savings_annual_rs` across a set of insights. Treats missing
 *  values as 0 — never imputes. Used for the headline benefit on the
 *  Regular-vs-Direct summary card. */
const _sumFeeSavings = (insights) => {
  return insights.reduce(
    (s, ins) => s + (ins?.benefit?.fee_savings_annual_rs || 0),
    0,
  );
};

/** Modal listing the underlying pairs of a collapsed group. Reuses the
 *  existing Dialog primitive so styling matches HoldingDrilldownModal. */
const PairsListModal = ({ open, onClose, title, description, items, perfCards, onMarkDone, onUnmark, onAsk, fmt }) => {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-auto rounded-2xl">
        <DialogHeader>
          <DialogTitle className="text-lg font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            {title}
          </DialogTitle>
          {description && (
            <DialogDescription className="text-xs text-slate-400">
              {description}
            </DialogDescription>
          )}
        </DialogHeader>
        <div className="space-y-2 mt-2">
          {items.map((ins, i) => (
            <InsightCard
              key={ins.insight_id || `pair-${i}`}
              insight={ins}
              perfCards={perfCards}
              onMarkDone={onMarkDone}
              onUnmark={onUnmark}
              onAsk={onAsk}
              fmt={fmt}
            />
          ))}
          {items.length === 0 && (
            <p className="text-xs text-slate-500 text-center py-6 italic">No pairs to show.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

/** Single summary tile for a collapsed group (Regular-vs-Direct OR
 *  same-category overlaps). Click anywhere on the row to open the modal. */
const CollapsedSummaryCard = ({ icon: Icon, accent, title, subtitle, benefit, count, onOpen }) => (
  <button
    type="button"
    onClick={onOpen}
    className={`w-full text-left rounded-xl border ${accent} p-4 flex items-center gap-3 hover:bg-slate-50/60 dark:hover:bg-white/[0.03] transition-colors focus:outline-none focus:ring-2 focus:ring-white/20`}
  >
    <Icon className="w-5 h-5 flex-shrink-0" />
    <div className="flex-1 min-w-0">
      <p className="text-sm font-semibold text-slate-900 dark:text-white">{title}</p>
      <p className="text-xs text-slate-500 dark:text-zinc-500 mt-0.5">{subtitle}</p>
      {benefit && (
        <p className="text-xs font-bold text-emerald-500 mt-1" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          {benefit}
        </p>
      )}
    </div>
    <span className="text-[10px] px-2 py-0.5 rounded bg-slate-100 dark:bg-zinc-800/60 text-slate-500 dark:text-zinc-400 flex-shrink-0">
      {count} pair{count === 1 ? "" : "s"}
    </span>
    <ArrowRight className="w-4 h-4 text-slate-400 flex-shrink-0" />
  </button>
);

/** Collapsed Duplicate Funds theme — splits Regular-vs-Direct from
 *  same-category, renders ≤2 summary cards, opens a modal per click. */
const CollapsedDuplicatesGroup = ({ items, perfCards, fmt, onMarkDone, onUnmark, onAsk }) => {
  const [openModal, setOpenModal] = useState(null);  // 'regdir' | 'cat' | null

  const regDir = items.filter(isRegularVsDirect);
  const sameCat = items.filter((i) => !isRegularVsDirect(i));

  if (regDir.length === 0 && sameCat.length === 0) return null;

  const feeSavings = _sumFeeSavings(regDir);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-zinc-300">
        <Layers className="w-3.5 h-3.5" />
        <span>Duplicate Funds</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-zinc-800/60 text-slate-500 dark:text-zinc-500">
          {regDir.length + sameCat.length}
        </span>
      </div>

      {regDir.length > 0 && (
        <CollapsedSummaryCard
          icon={(props) => <Coins {...props} className={`${props.className} text-emerald-500`} />}
          accent="border-emerald-500/25 bg-emerald-500/5"
          title={`${regDir.length} fund${regDir.length === 1 ? "" : "s"} held in both Regular and Direct plans`}
          subtitle="Switch to Direct → typically saves 0.5-1.5 pp/yr in expense ratio"
          benefit={feeSavings > 0 ? `~${fmt ? fmt(feeSavings) : `₹${feeSavings.toLocaleString("en-IN")}`}/yr in fee savings` : null}
          count={regDir.length}
          onOpen={() => setOpenModal("regdir")}
        />
      )}

      {sameCat.length > 0 && (
        <CollapsedSummaryCard
          icon={(props) => <Layers {...props} className={`${props.className} text-amber-500`} />}
          accent="border-amber-500/25 bg-amber-500/5"
          title={`${sameCat.length} fund pair${sameCat.length === 1 ? "" : "s"} duplicated within the same category`}
          subtitle="Consolidate into the better-scoring fund (Consolidation Score)"
          benefit={null}
          count={sameCat.length}
          onOpen={() => setOpenModal("cat")}
        />
      )}

      <PairsListModal
        open={openModal === "regdir"}
        onClose={() => setOpenModal(null)}
        title="Regular ↔ Direct plan duplicates"
        description="Same scheme held in both Regular and Direct plans. Switching the Regular position to Direct typically saves 0.5-1.5pp/yr in expense ratio."
        items={regDir}
        perfCards={perfCards}
        onMarkDone={onMarkDone}
        onUnmark={onUnmark}
        onAsk={onAsk}
        fmt={fmt}
      />
      <PairsListModal
        open={openModal === "cat"}
        onClose={() => setOpenModal(null)}
        title="Same-category duplicates"
        description="Two funds in the same category with high stock-level overlap. Consolidate into the higher-scoring fund based on its consolidation score."
        items={sameCat}
        perfCards={perfCards}
        onMarkDone={onMarkDone}
        onUnmark={onUnmark}
        onAsk={onAsk}
        fmt={fmt}
      />
    </div>
  );
};

/** Collapsed Fund Overlap theme — one summary card, click to expand. */
const CollapsedOverlapGroup = ({ items, perfCards, fmt, onMarkDone, onUnmark, onAsk }) => {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-zinc-300">
        <TrendingUp className="w-3.5 h-3.5" />
        <span>Fund Overlap</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-zinc-800/60 text-slate-500 dark:text-zinc-500">
          {items.length}
        </span>
      </div>
      <CollapsedSummaryCard
        icon={(props) => <TrendingUp {...props} className={`${props.className} text-sky-500`} />}
        accent="border-sky-500/25 bg-sky-500/5"
        title={`${items.length} fund pair${items.length === 1 ? "" : "s"} with high stock-level overlap`}
        subtitle="Consolidate into the best-suited alternative based on consolidation score"
        benefit={null}
        count={items.length}
        onOpen={() => setOpen(true)}
      />
      <PairsListModal
        open={open}
        onClose={() => setOpen(false)}
        title="Overlapping fund pairs"
        description="Funds whose underlying stock holdings overlap significantly. Consolidate into whichever scores higher on the consolidation rubric (performance, risk-adj, expense, manager stability, drawdown control)."
        items={items}
        perfCards={perfCards}
        onMarkDone={onMarkDone}
        onUnmark={onUnmark}
        onAsk={onAsk}
        fmt={fmt}
      />
    </div>
  );
};

/** AMC-concentration enhancement — wraps an InsightCard with a "How to
 *  reduce" line that gives the user an actionable next step. */
const _amcReductionHint = (insight) => {
  // Title shape: "HDFC holds 44% of your MF corpus"
  const m = (insight?.title || "").match(/^(\S+) holds (\d+(?:\.\d+)?)% of your MF corpus/i);
  if (!m) return null;
  const [, amc, pctStr] = m;
  const pct = parseFloat(pctStr);
  const excessPp = Math.max(0, Math.round(pct - 25));   // 25% target ceiling
  return (
    <>
      <span className="font-semibold">How to reduce:</span>{" "}
      redirect new SIPs away from {amc} until exposure drops below 25%.
      {excessPp >= 5 && (
        <> Consider switching ~{excessPp}pp (the excess over the ceiling) to a different fund house.</>
      )}
    </>
  );
};


const ThemeGroup = ({ theme, label, items, perfCards, onMarkDone, onUnmark, onAsk, fmt, highlightIds }) => {
  const [open, setOpen] = useState(true);
  const Icon = THEME_ICON[theme] || THEME_ICON.other;
  if (!items.length) return null;
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-white transition w-full"
      >
        {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        <Icon className="w-3.5 h-3.5" />
        <span>{label}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-zinc-800/60 text-slate-500 dark:text-zinc-500">
          {items.length}
        </span>
      </button>
      {open && (
        <div className="space-y-2 ml-1">
          {items.map((ins, i) => (
            <InsightCard
              key={ins.insight_id || `${theme}-${i}`}
              insight={ins}
              perfCards={perfCards}
              onMarkDone={onMarkDone}
              onUnmark={onUnmark}
              onAsk={onAsk}
              fmt={fmt}
              highlight={highlightIds?.has(ins.insight_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────
const SUGGESTED_PROMPTS = [
  "Which 3 actions should I take first?",
  "What happens if I consolidate overlapping funds?",
  "How much can I save by switching to Direct plans?",
  "Show me the best replacement for my duplicate funds.",
];

export default function RecommendationsCenter({
  insights,
  summary: _summary,   // kept on the API for the deprecated hero; alias-rename so lint stays quiet
  perfCards,
  fmt,
  onAfterChange,
}) {
  const [activeTab, setActiveTab] = useState("all");
  const [localCompletions, setLocalCompletions] = useState({});
  const actionsRef = React.useRef(null);

  const enriched = useMemo(() =>
    (insights || []).map((ins) => {
      const id = ins.insight_id;
      const local = id !== undefined ? localCompletions[id] : undefined;
      return local !== undefined ? { ...ins, completed: local } : ins;
    }),
  [insights, localCompletions]);

  // Counts derived entirely from local array — works before backend analysis runs
  const counts = useMemo(() => {
    const c = { all: 0, critical: 0, important: 0, opportunities: 0, completed: 0 };
    enriched.forEach((ins) => {
      const sev = deriveSeverity(ins);
      if (ins.completed) {
        c.completed += 1;
      } else {
        c.all += 1;
        if (sev === "critical") c.critical += 1;
        else if (sev === "important") c.important += 1;
        else c.opportunities += 1;
      }
    });
    return c;
  }, [enriched]);

  // Top-3 by severity (critical > important > optimization), excluding completed
  const topActions = useMemo(() =>
    [...enriched]
      .filter((ins) => !ins.completed)
      .sort((a, b) => (SEV_ORDER[deriveSeverity(a)] ?? 99) - (SEV_ORDER[deriveSeverity(b)] ?? 99))
      .slice(0, 3),
  [enriched]);

  // IDs used to ring-highlight the top-3 cards in the All tab list
  const topActionIds = useMemo(
    () => new Set(topActions.map((i) => i.insight_id).filter(Boolean)),
    [topActions],
  );

  const filtered = useMemo(() => {
    if (activeTab === "completed") return enriched.filter((i) => i.completed);
    if (activeTab === "all") return enriched.filter((i) => !i.completed);
    const sevMap = { critical: "critical", important: "important", opportunities: "optimization" };
    return enriched.filter((i) => !i.completed && deriveSeverity(i) === sevMap[activeTab]);
  }, [enriched, activeTab]);

  const grouped = useMemo(() => {
    const map = new Map();
    filtered.forEach((ins) => {
      const t = deriveTheme(ins);
      if (!map.has(t)) map.set(t, { label: deriveThemeLabel(ins), order: ins.theme_order ?? 99, items: [] });
      map.get(t).items.push(ins);
    });
    return Array.from(map.entries())
      .sort((a, b) => a[1].order - b[1].order || a[0].localeCompare(b[0]))
      .map(([theme, v]) => ({ theme, ...v }));
  }, [filtered]);

  const onAsk = useCallback((prompt) => {
    try { sessionStorage.setItem("nivesh_chat_prefill", prompt || ""); } catch { /* ignore */ }
    window.location.hash = "chat";
  }, []);

  const markDone = useCallback(async (insightId) => {
    setLocalCompletions((s) => ({ ...s, [insightId]: true }));
    try {
      await axios.post(`${API}/insights/${insightId}/complete`, {}, { withCredentials: true });
      toast.success("Marked as done");
      if (onAfterChange) onAfterChange();
    } catch {
      setLocalCompletions((s) => ({ ...s, [insightId]: false }));
      toast.error("Could not mark as done");
    }
  }, [onAfterChange]);

  const unmarkDone = useCallback(async (insightId) => {
    setLocalCompletions((s) => ({ ...s, [insightId]: false }));
    try {
      await axios.delete(`${API}/insights/${insightId}/complete`, { withCredentials: true });
      toast.success("Reopened");
      if (onAfterChange) onAfterChange();
    } catch {
      setLocalCompletions((s) => ({ ...s, [insightId]: true }));
      toast.error("Could not reopen");
    }
  }, [onAfterChange]);

  if (!enriched.length) return null;

  const totalInsights = enriched.length;
  // `completedCount` was previously passed to HeroSummary; removed with the hero.

  return (
    <section className="space-y-4" data-testid="recommendations-center">
      {/* HeroSummary removed — the Action Matrix's Top-5 banner upstream
          already covers the "N recommendations to review" framing. Keeping
          two top-of-page summaries was redundant and ate vertical space. */}

      {/* Priority tabs */}
      <div className="flex gap-1 bg-slate-100 dark:bg-[#1A1A1A] rounded-xl p-1 border border-slate-200 dark:border-white/5 overflow-x-auto scrollbar-hide">
        {TAB_DEFS.map((t) => {
          const count = counts[t.id];
          const active = activeTab === t.id;
          return (
            <button
              type="button"
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              data-testid={`rec-tab-${t.id}`}
              className={`flex-shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg transition-all whitespace-nowrap ${
                active
                  ? "bg-white dark:bg-zinc-800 text-slate-900 dark:text-white shadow-sm"
                  : "text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-white"
              }`}
            >
              {t.label}
              {count > 0 && (
                <span className={`ml-1.5 text-[10px] px-1.5 py-0.5 rounded ${active ? "bg-slate-100 dark:bg-zinc-700" : "bg-slate-200/60 dark:bg-zinc-800/80"}`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Grouped action cards */}
      <div ref={actionsRef} className="scroll-mt-4">
        {grouped.length === 0 ? (
          <div className="rounded-2xl border border-slate-100 dark:border-white/5 bg-white dark:bg-[#121212] p-8 text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
            <p className="text-sm font-medium text-slate-900 dark:text-white">
              {activeTab === "completed" ? "Nothing completed yet" : "Nothing in this category"}
            </p>
            <p className="text-xs text-slate-500 dark:text-zinc-500 mt-1">
              {activeTab === "completed" ? "Mark recommendations as done to track progress here." : "Try another tab."}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {grouped.map((g) => {
              // Collapse the two highest-cardinality themes into summary
              // cards with a click-to-expand modal. Without this, a 40-item
              // duplicates group makes the page un-scannable.
              if (g.theme === "duplication") {
                return (
                  <CollapsedDuplicatesGroup
                    key={g.theme}
                    items={g.items}
                    perfCards={perfCards}
                    onMarkDone={markDone}
                    onUnmark={unmarkDone}
                    onAsk={onAsk}
                    fmt={fmt}
                  />
                );
              }
              if (g.theme === "overlap") {
                return (
                  <CollapsedOverlapGroup
                    key={g.theme}
                    items={g.items}
                    perfCards={perfCards}
                    onMarkDone={markDone}
                    onUnmark={unmarkDone}
                    onAsk={onAsk}
                    fmt={fmt}
                  />
                );
              }
              return (
                <ThemeGroup
                  key={g.theme}
                  theme={g.theme}
                  label={g.label}
                  items={g.items}
                  perfCards={perfCards}
                  onMarkDone={markDone}
                  onUnmark={unmarkDone}
                  onAsk={onAsk}
                  fmt={fmt}
                  highlightIds={activeTab === "all" ? topActionIds : null}
                />
              );
            })}
          </div>
        )}
      </div>

      {/* Suggested Copilot prompts */}
      {totalInsights > 0 && (
        <div className="rounded-2xl bg-white dark:bg-[#121212] border border-slate-100 dark:border-white/5 p-4">
          <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-2">
            Ask Nivesh Copilot
          </p>
          <div className="flex flex-wrap gap-2">
            {SUGGESTED_PROMPTS.map((q) => (
              <button
                type="button"
                key={q}
                onClick={() => onAsk(q)}
                className="text-xs px-3 py-1.5 rounded-full bg-slate-100 dark:bg-zinc-800/60 text-slate-700 dark:text-zinc-300 hover:bg-slate-200 dark:hover:bg-zinc-700/60 transition"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
