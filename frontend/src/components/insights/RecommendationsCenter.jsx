import React, { useMemo, useState, useCallback } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle, TrendingUp, Target, ChevronDown, ChevronRight,
  CheckCircle2, Circle, MessageSquare, Sparkles, Layers, Coins,
  Building2, Shield, Wallet, RefreshCw, AlertCircle,
} from "lucide-react";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

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

// Insights from the legacy path may not carry severity/theme — derive defensively.
const deriveSeverity = (insight) => {
  if (insight.severity && SEVERITY[insight.severity]) return insight.severity;
  if (insight.type === "warning" && insight.impact === "high") return "critical";
  if (insight.type === "opportunity" || insight.impact === "low") return "optimization";
  return "important";
};
const deriveTheme = (insight) => insight.theme || "other";
const deriveThemeLabel = (insight) => insight.theme_label || ({
  duplication: "Duplicate Funds", overlap: "Fund Overlap",
  amc_concentration: "AMC Concentration", category_concentration: "Category Concentration",
  sector_risk: "Sector Risk", drift: "Allocation Drift",
  allocation_gap: "Allocation Gaps", cost: "Cost Leakage", other: "Other",
}[deriveTheme(insight)] || "Other");

// Match holdings to an insight by name/sector/keyword — mirrors the legacy
// getAffectedHoldings in InsightsView so the new card keeps showing holdings.
const matchHoldings = (insight, perfCards) => {
  if (!perfCards || perfCards.length === 0) return [];
  const txt = `${insight.title || ""} ${insight.description || ""} ${insight.action || ""}`.toLowerCase();
  return perfCards.filter((h) => {
    const name = (h.name || "").toLowerCase();
    const sector = (h.sector || "").toLowerCase();
    const type = (h.asset_type || "").toLowerCase();
    if (txt.includes(name.slice(0, 15))) return true;
    if (txt.includes("gold") && (sector.includes("gold") || type === "gold")) return true;
    if (txt.includes("debt") && (type.includes("debt") || sector.includes("debt"))) return true;
    if (txt.includes("small cap") && sector.includes("small cap")) return true;
    if (txt.includes("regular") && name.includes("regular")) return true;
    if (txt.includes("mutual fund") && type === "mutual_fund") return true;
    return false;
  }).slice(0, 8);
};

// ── Hero summary card ──────────────────────────────────────────────────
const HeroSummary = ({ summary, totalInsights, completedCount }) => {
  const critical = summary?.critical_count || 0;
  const important = summary?.important_count || 0;
  const opps = summary?.opportunity_count || 0;
  const feeSavings = summary?.potential_fee_savings_annual_rs || 0;
  const taxSavings = summary?.potential_tax_savings_rs || 0;
  const dupCount = summary?.duplicate_fund_count || 0;

  return (
    <div className="rounded-2xl bg-gradient-to-br from-amber-50 via-orange-50 to-rose-50 dark:from-amber-500/10 dark:via-orange-500/5 dark:to-rose-500/10 border border-amber-200/60 dark:border-amber-500/20 p-5 md:p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="w-4 h-4 text-amber-600" />
            <p className="text-[10px] font-bold tracking-wider uppercase text-amber-700 dark:text-amber-400">
              Portfolio Optimization
            </p>
          </div>
          <h2 className="text-xl md:text-2xl font-bold text-slate-900 dark:text-white">
            {critical > 0
              ? `${critical} high-priority action${critical === 1 ? "" : "s"} identified`
              : important > 0
              ? `${important} recommendation${important === 1 ? "" : "s"} to review`
              : opps > 0
              ? `${opps} opportunit${opps === 1 ? "y" : "ies"} to optimize`
              : "Portfolio looks healthy"}
          </h2>
          <p className="text-sm text-slate-600 dark:text-zinc-400 mt-1">
            {totalInsights} insight{totalInsights === 1 ? "" : "s"} detected
            {completedCount > 0 && ` · ${completedCount} resolved`}
          </p>
        </div>
        {totalInsights > 0 && (
          <div className="text-right">
            <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400">Progress</p>
            <p className="text-2xl font-bold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
              {completedCount}/{totalInsights}
            </p>
            <div className="w-28 h-1.5 rounded-full bg-slate-200/60 dark:bg-zinc-700/40 mt-1 overflow-hidden">
              <div
                className="h-full bg-emerald-500 transition-all"
                style={{ width: totalInsights > 0 ? `${(completedCount / totalInsights) * 100}%` : "0%" }}
              />
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-5">
        <StatTile label="Critical" value={critical} accent="#EF4444" />
        <StatTile label="Important" value={important} accent="#F59E0B" />
        <StatTile label="Fee savings" value={feeSavings > 0 ? `${formatRs(feeSavings)}/yr` : "—"} accent="#10B981" />
        <StatTile label="Duplicate funds" value={dupCount > 0 ? dupCount : "—"} accent="#3B82F6" />
      </div>

      {taxSavings > 0 && (
        <p className="text-xs text-slate-500 dark:text-zinc-500 mt-3">
          Estimated tax savings: <span className="font-medium text-emerald-600">{formatRs(taxSavings)}</span>
        </p>
      )}
    </div>
  );
};

const StatTile = ({ label, value, accent }) => (
  <div className="bg-white/70 dark:bg-zinc-900/40 rounded-xl px-3 py-2.5 border border-white/40 dark:border-white/5">
    <p className="text-[9px] font-bold tracking-wider uppercase text-slate-500 dark:text-zinc-500">{label}</p>
    <p className="text-lg font-bold mt-0.5" style={{ color: accent, fontFamily: "'Outfit', sans-serif" }}>
      {value}
    </p>
  </div>
);

// ── Single insight card ───────────────────────────────────────────────
const InsightCard = ({ insight, perfCards, onMarkDone, onAsk, onUnmark, fmt }) => {
  const [open, setOpen] = useState(false);
  const [marking, setMarking] = useState(false);
  const sev = SEVERITY[deriveSeverity(insight)] || SEVERITY.important;
  const SevIcon = sev.icon;
  const ThemeIcon = THEME_ICON[deriveTheme(insight)] || THEME_ICON.other;
  const benefit = insight.benefit || {};
  const completed = !!insight.completed;
  const affectedHoldings = useMemo(() => matchHoldings(insight, perfCards), [insight, perfCards]);

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
      className={`rounded-xl border overflow-hidden transition-opacity ${sev.border} ${completed ? "opacity-60" : ""}`}
      data-testid={`rec-card-${insight.insight_id || insight.title}`}
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
                {insight.title}
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
              {insight.description}
            </p>
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
              {insight.description && (
                <div>
                  <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">Details</p>
                  <p className="text-xs text-slate-600 dark:text-zinc-400 leading-relaxed">{insight.description}</p>
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
const ThemeGroup = ({ theme, label, items, perfCards, onMarkDone, onUnmark, onAsk, fmt }) => {
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
  summary,
  perfCards,
  fmt,
  onAfterChange,
}) {
  const [activeTab, setActiveTab] = useState("all");
  const [localCompletions, setLocalCompletions] = useState({}); // optimistic overlay

  // Apply optimistic overlay so the UI doesn't flicker waiting for refetch
  const enriched = useMemo(() =>
    (insights || []).map((ins) => {
      const id = ins.insight_id;
      const local = id && localCompletions[id];
      return local !== undefined ? { ...ins, completed: local } : ins;
    }),
  [insights, localCompletions]);

  const counts = useMemo(() => {
    const c = { all: 0, critical: 0, important: 0, opportunities: 0, completed: 0 };
    enriched.forEach((ins) => {
      const sev = deriveSeverity(ins);
      if (ins.completed) c.completed += 1;
      else {
        c.all += 1;
        if (sev === "critical") c.critical += 1;
        else if (sev === "important") c.important += 1;
        else c.opportunities += 1;
      }
    });
    return c;
  }, [enriched]);

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
      .sort((a, b) => a[1].order - b[1].order)
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
  const completedCount = counts.completed;

  return (
    <section className="space-y-4" data-testid="recommendations-center">
      <HeroSummary summary={summary} totalInsights={totalInsights} completedCount={completedCount} />

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

      {/* Grouped cards */}
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
          {grouped.map((g) => (
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
            />
          ))}
        </div>
      )}

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
