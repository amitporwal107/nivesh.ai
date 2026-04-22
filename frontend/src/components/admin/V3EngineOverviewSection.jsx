import React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Gauge, Shield, Target, ArrowRightLeft, TrendingUp, Activity } from "lucide-react";

/**
 * V3 Engine Overview — a read-only, at-a-glance display of the V3 scoring
 * primitive weights and guardrail thresholds. Source-of-truth lives in
 * services/v3_scoring.py; this panel keeps admins oriented while they tune
 * tactical rule thresholds in the RulesConfigSection below.
 *
 * All numbers are mirrored from the Excel spec that drives v3_scoring.py,
 * so editing this file without updating the backend produces misleading
 * telemetry — a maintenance warning is shown in the help text.
 */

const COMPOSITES = [
  {
    key: "quality",
    label: "Quality",
    icon: Gauge,
    tone: "text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 dark:text-emerald-400",
    weights: [
      { k: "Performance (ret_1y/3y/5y vs cat avg)", v: 25 },
      { k: "Risk-Adjusted (Sharpe + Sortino)",       v: 20 },
      { k: "Consistency (rolling 12m windows)",      v: 20 },
      { k: "Drawdown (max_drawdown_pct)",            v: 15 },
      { k: "Cost (expense_ratio_direct)",            v: 10 },
      { k: "AUM / Age",                              v: 10 },
    ],
  },
  {
    key: "health",
    label: "Health",
    icon: Activity,
    tone: "text-sky-600 bg-sky-50 dark:bg-sky-950/40 dark:text-sky-400",
    weights: [
      { k: "Manager Tenure",              v: 25 },
      { k: "AUM Stability",               v: 20 },
      { k: "Turnover Ratio",              v: 15 },
      { k: "Top-10 Concentration",        v: 15 },
      { k: "Downside Protection",         v: 15 },
      { k: "Expense Trend (3y delta)",    v: 10 },
    ],
  },
  {
    key: "exit",
    label: "Exit",
    icon: ArrowRightLeft,
    tone: "text-rose-600 bg-rose-50 dark:bg-rose-950/40 dark:text-rose-400",
    weights: [
      { k: "Overlap (vs portfolio)",   v: 25 },
      { k: "Tax Impact",               v: 25 },
      { k: "Quality (inverted)",       v: 25 },
      { k: "Cost",                     v: 15 },
      { k: "Portfolio Fit",            v: 10 },
    ],
  },
  {
    key: "add",
    label: "Add",
    icon: TrendingUp,
    tone: "text-indigo-600 bg-indigo-50 dark:bg-indigo-950/40 dark:text-indigo-400",
    weights: [
      { k: "Gap Fit (asset alloc + diversification)",  v: 30 },
      { k: "Low Overlap with existing",                 v: 25 },
      { k: "Quality",                                    v: 20 },
      { k: "Need (portfolio deficit)",                   v: 15 },
      { k: "Cost",                                       v: 10 },
    ],
  },
];

const SWITCH_FORMULA = [
  "(Q_new − Q_old)",
  "+ Overlap reduction %",
  "+ Cost saving ₹/yr  ÷ 10,000",
  "− Tax cost ₹       ÷ 10,000",
];
const GUARDRAILS = [
  { code: "HIGH_QUALITY_PROTECTION", rule: "Block EXIT if Quality ≥ 75 AND Health ≥ 70",   override: "overlap > 80% overrides" },
  { code: "TAX_EXCEEDS_BENEFIT",      rule: "Block EXIT if tax cost > annual benefit",       override: "no override" },
  { code: "RECENT_INVESTMENT",        rule: "Block EXIT if holding age < 6 months",          override: "no override" },
  { code: "LOW_CONFIDENCE",           rule: "Reduce action count if confidence_score < 50", override: "flag, not block" },
];

const WeightBar = ({ item, total }) => {
  const pct = (item.v / total) * 100;
  return (
    <div className="flex items-center gap-2 text-[11px]" data-testid={`v3-weight-${item.k}`}>
      <div className="flex-1 min-w-0 truncate text-slate-600 dark:text-slate-300" title={item.k}>{item.k}</div>
      <div className="w-20 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div className="h-full bg-gradient-to-r from-slate-400 to-slate-600 dark:from-slate-500 dark:to-slate-300" style={{ width: `${pct}%` }} />
      </div>
      <div className="w-8 text-right font-mono tabular-nums text-slate-800 dark:text-slate-200">{item.v}%</div>
    </div>
  );
};

const CompositeCard = ({ composite }) => {
  const Icon = composite.icon;
  const total = composite.weights.reduce((a, w) => a + w.v, 0);
  return (
    <div
      data-testid={`v3-composite-${composite.key}`}
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/60 p-4 space-y-3"
    >
      <div className="flex items-center gap-2">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${composite.tone}`}>
          <Icon className="w-4 h-4" />
        </div>
        <div className="flex-1">
          <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{composite.label}</div>
          <div className="text-[10px] uppercase tracking-wider text-slate-400">Composite · Σ = {total}%</div>
        </div>
      </div>
      <div className="space-y-1.5">
        {composite.weights.map(w => <WeightBar key={w.k} item={w} total={total} />)}
      </div>
    </div>
  );
};

export default function V3EngineOverviewSection() {
  return (
    <Card
      data-testid="admin-v3-engine-overview"
      className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none overflow-hidden"
    >
      <CardContent className="p-5 sm:p-6 space-y-5">
        <div className="flex items-start gap-3 flex-wrap">
          <div className="w-10 h-10 rounded-xl bg-violet-50 dark:bg-violet-950/60 text-violet-600 dark:text-violet-400 flex items-center justify-center">
            <Gauge className="w-5 h-5" strokeWidth={2} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">V3 Engine Overview</h3>
              <Badge variant="outline" className="text-[10px]">Excel-backed · deterministic</Badge>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Composite-score weights and guardrails for the V3 deterministic scoring engine.
              Source of truth: <code className="font-mono">services/v3_scoring.py</code>.
              Use the Rules Config section below for live-tunable thresholds.
            </p>
          </div>
        </div>

        {/* Composite weights grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {COMPOSITES.map(c => <CompositeCard key={c.key} composite={c} />)}
        </div>

        {/* Switch score formula */}
        <div
          data-testid="v3-switch-formula"
          className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/60 p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <ArrowRightLeft className="w-4 h-4 text-slate-500" />
            <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">Switch Score Formula</div>
            <Badge variant="outline" className="text-[10px]">recommend ≥ 2.0</Badge>
          </div>
          <code className="block text-[12px] font-mono leading-relaxed text-slate-700 dark:text-slate-300">
            {SWITCH_FORMULA.join("  ")}
          </code>
        </div>

        {/* Guardrails table */}
        <div
          data-testid="v3-guardrails-table"
          className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/60 overflow-hidden"
        >
          <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800 flex items-center gap-2">
            <Shield className="w-4 h-4 text-slate-500" />
            <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">Guardrails</div>
            <span className="text-[11px] text-slate-500">Pre-action sanity checks · prevent expensive mistakes</span>
          </div>
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {GUARDRAILS.map(g => (
              <div key={g.code} className="px-4 py-2.5 grid grid-cols-12 gap-3 items-start text-[12px]">
                <div className="col-span-4 font-mono text-slate-800 dark:text-slate-200" data-testid={`guardrail-${g.code}`}>
                  {g.code}
                </div>
                <div className="col-span-5 text-slate-600 dark:text-slate-300">{g.rule}</div>
                <div className="col-span-3 text-right text-slate-400 italic">{g.override}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-start gap-2 text-[11px] text-slate-500 dark:text-slate-400 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/40 px-3 py-2 rounded-lg">
          <Target className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
          <span>
            <strong className="text-amber-700 dark:text-amber-400">Read-only:</strong>{" "}
            These weights are hard-coded in the backend for auditability.
            Editing them requires a code deploy so that unit tests re-validate the composite math.
            For live-tunable thresholds (AMC concentration, debt floor, overlap trigger, confidence cut-off, etc.),
            use the <strong>Rules Config</strong> section below.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
