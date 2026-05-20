/**
 * OptimizationCard — Phase B/C/D drill-down for one duplicate-pair insight.
 *
 * Layered design — every section is independently loadable & graceful:
 *   1. Plan (Phase B): Keep / Exit columns with score, ER, CAGR, tax impact, rationale
 *   2. Redeploy (Phase C): allocation chips with bucket pitch + instrument hints
 *   3. Simulate (Phase D): Before/After table + 10Y wealth gain + stacked bar viz
 *
 * Fetches `/api/insights/{id}/optimization-plan` lazily on first expand.
 * Fetches `/api/insights/{id}/simulate` lazily when user opens the Simulate
 * section.
 */
import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2, XCircle, TrendingUp, Coins, Building2, Shield,
  Globe, Wallet, Sparkles, BarChart3, Loader2, AlertTriangle,
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const formatRs = (v) => {
  const n = Number(v) || 0;
  if (Math.abs(n) >= 1_00_000) return `${n < 0 ? "−" : ""}₹${(Math.abs(n) / 1_00_000).toFixed(2)}L`;
  if (Math.abs(n) >= 1_000) return `${n < 0 ? "−" : ""}₹${(Math.abs(n) / 1_000).toFixed(1)}K`;
  return `${n < 0 ? "−" : ""}₹${Math.round(Math.abs(n)).toLocaleString("en-IN")}`;
};

const BUCKET_ICON = {
  debt:          Wallet,
  gold:          Coins,
  international: Globe,
  equity:        TrendingUp,
  other:         Sparkles,
};

const Section = ({ title, children, accent = "amber" }) => (
  <div className="space-y-2">
    <p className={`text-[10px] font-bold tracking-wider uppercase text-${accent}-700 dark:text-${accent}-400`}>
      {title}
    </p>
    {children}
  </div>
);

const FundColumn = ({ fund, role, sub }) => {
  const isKeep = role === "keep";
  const accent = isKeep ? "emerald" : "red";
  const Icon = isKeep ? CheckCircle2 : XCircle;
  return (
    <div className={`rounded-xl p-3 border bg-${accent}-50/60 dark:bg-${accent}-500/5 border-${accent}-200 dark:border-${accent}-500/20`}>
      <div className="flex items-center gap-1.5">
        <Icon className={`w-3.5 h-3.5 text-${accent}-600 dark:text-${accent}-400 flex-shrink-0`} />
        <span className={`text-[10px] font-bold uppercase tracking-wider text-${accent}-700 dark:text-${accent}-400`}>
          {isKeep ? "Keep" : "Exit"}
        </span>
      </div>
      <p className="text-xs font-semibold text-slate-900 dark:text-white mt-1 leading-tight">
        {fund.fund_name}
      </p>
      <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1">
        <Stat label="Score" value={`${fund.total_score}/100`} />
        <Stat label="ER" value={`${fund.expense_ratio_pct}%`} />
        <Stat label="AUM" value={formatRs(fund.aum_rs)} />
        {fund.user_cagr_pct != null && (
          <Stat label="Your CAGR" value={`${fund.user_cagr_pct}%`} />
        )}
      </div>
      {sub}
    </div>
  );
};

const Stat = ({ label, value }) => (
  <div className="min-w-0">
    <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400 leading-tight">{label}</p>
    <p className="text-xs font-semibold text-slate-700 dark:text-zinc-300 leading-tight">{value}</p>
  </div>
);

const RedeployChip = ({ allocation }) => {
  const Icon = BUCKET_ICON[allocation.bucket] || Sparkles;
  return (
    <div className="rounded-lg p-2.5 bg-white/70 dark:bg-zinc-900/40 border border-white/40 dark:border-white/5">
      <div className="flex items-center gap-2">
        <Icon className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
        <span className="text-xs font-semibold text-slate-900 dark:text-white">{allocation.label}</span>
        <span className="ml-auto text-[10px] font-bold text-slate-700 dark:text-zinc-300" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          {formatRs(allocation.rs)}
        </span>
        <span className="text-[10px] text-slate-400">({allocation.pct}%)</span>
      </div>
      <p className="text-[10px] text-slate-500 dark:text-zinc-500 mt-1">{allocation.pitch}</p>
      {allocation.instruments && allocation.instruments.length > 0 && (
        <p className="text-[10px] text-slate-400 mt-0.5 truncate">
          e.g. {allocation.instruments[0]}
        </p>
      )}
    </div>
  );
};

// ── Before/After visualisation (stacked bars) ─────────────────────────
const AllocationBar = ({ alloc, label }) => {
  const buckets = [
    { key: "equity",        label: "Equity",       color: "#10B981" },
    { key: "international", label: "Intl",         color: "#3B82F6" },
    { key: "debt",          label: "Debt",         color: "#8B5CF6" },
    { key: "gold",          label: "Gold",         color: "#F59E0B" },
    { key: "other",         label: "Other",        color: "#94A3B8" },
  ];
  return (
    <div>
      <p className="text-[10px] font-bold tracking-wider uppercase text-slate-400 mb-1">{label}</p>
      <div className="flex h-6 rounded-md overflow-hidden border border-white/40 dark:border-white/5">
        {buckets.map((b) => {
          const pct = alloc[b.key] || 0;
          if (pct <= 0.5) return null;
          return (
            <div
              key={b.key}
              style={{ width: `${pct}%`, backgroundColor: b.color }}
              title={`${b.label}: ${pct}%`}
              className="flex items-center justify-center text-[9px] font-semibold text-white"
            >
              {pct >= 8 ? `${Math.round(pct)}%` : ""}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const SimulationView = ({ sim }) => {
  if (!sim) return null;
  const { switch_only, switch_and_redeploy } = sim;
  const scenarios = [
    { key: "switch_only", title: "Switch only", data: switch_only, hint: "Move freed capital into the keep fund — pure fee-savings play." },
    { key: "switch_and_redeploy", title: "Switch + Diversify", data: switch_and_redeploy, hint: "Redeploy capital into debt / gold / international — lower volatility, lower expected return." },
  ];

  return (
    <div className="space-y-3">
      {scenarios.map(({ key, title, data, hint }) => {
        if (!data) return null;
        const delta = data.delta || {};
        const positive = (delta.projected_10y_wealth_gain_rs || 0) > 0;
        return (
          <div key={key} className="rounded-xl border border-slate-200 dark:border-white/5 bg-white/60 dark:bg-zinc-900/30 p-3">
            <div className="flex items-baseline gap-2 flex-wrap">
              <p className="text-sm font-semibold text-slate-900 dark:text-white">{title}</p>
              <span className={`text-xs font-bold ${positive ? "text-emerald-600" : "text-red-500"}`}>
                {positive ? "+" : ""}{formatRs(delta.projected_10y_wealth_gain_rs)} over 10Y
              </span>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-zinc-500 mt-0.5">{hint}</p>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3">
              <Stat label="Funds" value={`${data.before.mf_count} → ${data.after.mf_count}`} />
              <Stat label="Expense" value={`${data.before.weighted_expense_ratio_pct}% → ${data.after.weighted_expense_ratio_pct}%`} />
              <Stat label="CAGR" value={`${data.before.blended_cagr_pct}% → ${data.after.blended_cagr_pct}%`} />
              <Stat label="10Y value" value={`${formatRs(data.before.projected_10y_value_rs)} → ${formatRs(data.after.projected_10y_value_rs)}`} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
              <AllocationBar alloc={data.before.allocation_pct} label="Before" />
              <AllocationBar alloc={data.after.allocation_pct} label="After" />
            </div>
          </div>
        );
      })}

      {sim?.plan?.placeholders && sim.plan.placeholders.length > 0 && (
        <div className="rounded-lg border border-amber-200 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-500/5 p-2.5">
          <p className="text-[10px] font-bold uppercase tracking-wider text-amber-700 dark:text-amber-400 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Data placeholders
          </p>
          <p className="text-[10px] text-slate-600 dark:text-zinc-400 mt-1">
            Scoring rubric not yet using: {sim.plan.placeholders.map((p) => p.split(" (")[0]).join(", ")}.
          </p>
        </div>
      )}
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────
export default function OptimizationCard({ insightId, onClose }) {
  const [plan, setPlan] = useState(null);
  const [planError, setPlanError] = useState(null);
  const [planLoading, setPlanLoading] = useState(false);

  const [sim, setSim] = useState(null);
  const [simError, setSimError] = useState(null);
  const [simLoading, setSimLoading] = useState(false);
  const [showSim, setShowSim] = useState(false);

  const loadPlan = useCallback(async () => {
    if (!insightId) return;
    setPlanLoading(true);
    setPlanError(null);
    try {
      const res = await axios.get(`${API}/insights/${insightId}/optimization-plan`, { withCredentials: true });
      setPlan(res.data);
    } catch (e) {
      setPlanError(e?.response?.data?.detail || e.message || "Could not load plan");
    } finally {
      setPlanLoading(false);
    }
  }, [insightId]);

  useEffect(() => {
    loadPlan();
  }, [loadPlan]);

  const loadSimulation = useCallback(async () => {
    if (!insightId || sim) return;
    setSimLoading(true);
    setSimError(null);
    try {
      const res = await axios.get(`${API}/insights/${insightId}/simulate`, { withCredentials: true });
      setSim(res.data);
    } catch (e) {
      setSimError(e?.response?.data?.detail || e.message || "Could not run simulation");
    } finally {
      setSimLoading(false);
    }
  }, [insightId, sim]);

  if (planLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-500 p-4">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Building optimisation plan…
      </div>
    );
  }
  if (planError) {
    return (
      <div className="text-xs text-amber-600 dark:text-amber-400 p-3 bg-amber-50/40 dark:bg-amber-500/5 rounded-lg">
        Couldn't load plan: {planError}
      </div>
    );
  }
  if (!plan) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4 p-4 bg-gradient-to-br from-slate-50 to-white dark:from-zinc-900/50 dark:to-[#121212] rounded-xl border border-slate-100 dark:border-white/5"
      data-testid={`optimization-card-${insightId}`}
    >
      {/* B: Keep / Exit columns */}
      <Section title="Recommended Action" accent="emerald">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <FundColumn fund={plan.keep} role="keep" />
          <FundColumn fund={plan.exit} role="exit" />
        </div>
      </Section>

      {/* Headline numbers */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <NumberTile label="Capital released"    value={formatRs(plan.capital_released_rs)}    accent="#3B82F6" />
        <NumberTile label="Annual fee savings"  value={`${formatRs(plan.annual_fee_savings_rs)}/yr`} accent="#10B981" />
        <NumberTile label="Tax impact"          value={formatRs(plan.tax_impact_rs)}          accent="#F59E0B" />
        <NumberTile label="Score gap"           value={`+${Math.round(plan.keep.total_score - plan.exit.total_score)} pts`} accent="#8B5CF6" />
      </div>

      {/* Rationale */}
      {plan.rationale && plan.rationale.length > 0 && (
        <Section title="Why this fund wins">
          <ul className="space-y-1">
            {plan.rationale.map((r, i) => (
              <li key={i} className="text-xs text-slate-600 dark:text-zinc-400 flex gap-2">
                <span className="text-emerald-500 flex-shrink-0">→</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* C: Redeploy chips */}
      {plan.redeploy?.allocations?.length > 0 && (
        <Section title="Where to redeploy the freed capital" accent="blue">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {plan.redeploy.allocations.map((a) => (
              <RedeployChip key={a.bucket} allocation={a} />
            ))}
          </div>
          {plan.redeploy.rationale && (
            <p className="text-[10px] text-slate-500 dark:text-zinc-500 mt-1">{plan.redeploy.rationale.join(" ")}</p>
          )}
        </Section>
      )}

      {/* D: Simulate Switch */}
      <div>
        {!showSim ? (
          <button
            type="button"
            onClick={() => { setShowSim(true); loadSimulation(); }}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 hover:bg-violet-100 dark:hover:bg-violet-500/20 font-medium"
            data-testid={`simulate-${insightId}`}
          >
            <BarChart3 className="w-3.5 h-3.5" /> Simulate Switch (10Y projection)
          </button>
        ) : (
          <Section title="Before vs After (10-year projection)" accent="violet">
            {simLoading && (
              <div className="flex items-center gap-2 text-xs text-slate-500 p-3">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Running simulation…
              </div>
            )}
            {simError && <p className="text-xs text-amber-600">{simError}</p>}
            {sim && <SimulationView sim={sim} />}
          </Section>
        )}
      </div>

      {onClose && (
        <div className="pt-1">
          <button type="button" onClick={onClose} className="text-[11px] text-slate-400 hover:text-slate-600">
            Close optimisation panel
          </button>
        </div>
      )}
    </motion.div>
  );
}

const NumberTile = ({ label, value, accent }) => (
  <div className="rounded-lg px-3 py-2 bg-white/60 dark:bg-zinc-900/30 border border-slate-200 dark:border-white/5">
    <p className="text-[9px] font-bold tracking-wider uppercase text-slate-500 dark:text-zinc-500">{label}</p>
    <p className="text-sm font-bold mt-0.5" style={{ color: accent, fontFamily: "'Outfit', sans-serif" }}>
      {value}
    </p>
  </div>
);
