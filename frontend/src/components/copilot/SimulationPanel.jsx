import React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ArrowRight, TrendingUp, Shield, Wallet, Save, CheckCircle2, FileText } from "lucide-react";

const MetricBlock = ({ label, before, after, format = (v) => v, testId, tone }) => {
  const improved = tone === "good";
  return (
    <div data-testid={testId} className="p-3 sm:p-4 rounded-xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900">
      <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-2">{label}</div>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-slate-500 dark:text-slate-400 line-through">{format(before)}</span>
        <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
        <span className={`font-semibold text-base ${improved ? "text-emerald-600 dark:text-emerald-400" : "text-slate-900 dark:text-white"}`}>
          {format(after)}
        </span>
      </div>
    </div>
  );
};

const RiskGauge = ({ before, after }) => {
  const pct = Math.max(0, Math.min(100, after));
  const pctBefore = Math.max(0, Math.min(100, before));
  const color = after >= 75 ? "bg-red-500" : after >= 50 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div data-testid="risk-gauge" className="p-4 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400">Risk Score</span>
        <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">0 = safe · 100 = risky</span>
      </div>
      <div className="relative h-2.5 bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden">
        <div className={`absolute inset-y-0 left-0 ${color} transition-all duration-700`} style={{ width: `${pct}%` }} />
        {/* before marker */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-slate-400 dark:bg-slate-500"
          style={{ left: `${pctBefore}%` }}
          title={`Before: ${before}`}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-slate-500 dark:text-slate-400">Before <b className="text-slate-700 dark:text-slate-300">{before}</b></span>
        <span className={`font-semibold ${after < before ? "text-emerald-600 dark:text-emerald-400" : "text-slate-700 dark:text-slate-300"}`}>
          After {after} {after < before && `(${after - before})`}
        </span>
      </div>
    </div>
  );
};

const AllocationBar = ({ label, beforePct, afterPct, color = "emerald" }) => {
  const colors = {
    emerald: "bg-emerald-500",
    blue: "bg-blue-500",
    amber: "bg-amber-500",
  };
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="font-medium text-slate-700 dark:text-slate-300">{label}</span>
        <span className="text-slate-500 dark:text-slate-400">
          {beforePct}% <ArrowRight className="w-3 h-3 inline mx-1" /> <b className="text-slate-900 dark:text-white">{afterPct}%</b>
        </span>
      </div>
      <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full relative overflow-hidden">
        <div className="absolute inset-y-0 left-0 bg-slate-300 dark:bg-slate-700" style={{ width: `${beforePct}%` }} />
        <div className={`absolute inset-y-0 left-0 ${colors[color]} transition-all duration-700`} style={{ width: `${afterPct}%` }} />
      </div>
    </div>
  );
};

const formatCurrency = (n) => {
  if (!n) return "₹0";
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(2)} L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(1)}K`;
  return `₹${n}`;
};

const SimulationPanel = ({ result, scenario, onApply, onSave, onViewPlan, applying, saving }) => {
  if (!result) return null;
  const { before, after, delta, top_changes } = result;

  return (
    <Card
      data-testid="simulation-panel"
      className="p-4 sm:p-6 rounded-2xl border-2 border-teal-200 dark:border-teal-800 bg-gradient-to-br from-teal-50/50 to-white dark:from-teal-950/20 dark:to-slate-900"
    >
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-teal-600 dark:text-teal-400 mb-1">
            Simulation Result
          </div>
          <h3 className="text-lg sm:text-xl font-semibold text-slate-900 dark:text-white">
            {scenario?.title || "What-if Analysis"}
          </h3>
        </div>
      </div>

      {/* Key metrics grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mb-5">
        <MetricBlock
          testId="metric-cagr"
          label="Expected CAGR"
          before={`${before.expected_cagr}%`}
          after={`${after.expected_cagr}%`}
          tone={delta.cagr > 0 ? "good" : "neutral"}
        />
        <MetricBlock
          testId="metric-risk"
          label="Risk"
          before={before.risk_label}
          after={after.risk_label}
          tone={delta.risk < 0 ? "good" : "neutral"}
        />
        <MetricBlock
          testId="metric-cost"
          label="Annual Cost"
          before={formatCurrency(before.annual_cost)}
          after={formatCurrency(after.annual_cost)}
          tone={after.annual_cost < before.annual_cost ? "good" : "neutral"}
        />
        <MetricBlock
          testId="metric-5y"
          label="5Y Projected"
          before={formatCurrency(before.projected_5y)}
          after={formatCurrency(after.projected_5y)}
          tone={delta.value_5y > 0 ? "good" : "neutral"}
        />
      </div>

      {/* Risk gauge */}
      <div className="mb-5">
        <RiskGauge before={before.risk_score} after={after.risk_score} />
      </div>

      {/* Allocation bars */}
      <div className="mb-5 p-4 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800">
        <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-3">
          Allocation — Before vs After
        </div>
        <div className="space-y-3">
          <AllocationBar label="Equity" beforePct={before.equity_pct} afterPct={after.equity_pct} color="blue" />
          <AllocationBar label="Debt" beforePct={before.debt_pct} afterPct={after.debt_pct} color="emerald" />
          {after.gold_pct > 0 && (
            <AllocationBar label="Gold" beforePct={0} afterPct={after.gold_pct} color="amber" />
          )}
        </div>
      </div>

      {/* Top changes */}
      <div className="mb-5 p-4 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800">
        <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-2">Top Changes</div>
        <ul className="space-y-1.5" data-testid="top-changes">
          {top_changes.map((c, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-300">
              <CheckCircle2 className="w-4 h-4 text-teal-500 flex-shrink-0 mt-0.5" strokeWidth={2} />
              <span>{c}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Action buttons */}
      <div className="flex flex-col sm:flex-row gap-2">
        <Button
          data-testid="apply-changes-btn"
          onClick={onApply}
          disabled={applying}
          className="flex-1 bg-teal-600 hover:bg-teal-700 text-white rounded-xl"
        >
          <TrendingUp className="w-4 h-4 mr-2" />
          {applying ? "Applying…" : "Apply Changes"}
        </Button>
        <Button
          data-testid="view-plan-btn"
          onClick={onViewPlan}
          variant="outline"
          className="flex-1 rounded-xl border-slate-200 dark:border-slate-700"
        >
          <FileText className="w-4 h-4 mr-2" />
          View Rebalance Plan
        </Button>
        <Button
          data-testid="save-scenario-btn"
          onClick={onSave}
          variant="outline"
          disabled={saving}
          className="flex-1 rounded-xl border-slate-200 dark:border-slate-700"
        >
          <Save className="w-4 h-4 mr-2" />
          {saving ? "Saving…" : "Save Scenario"}
        </Button>
      </div>
    </Card>
  );
};

export default SimulationPanel;
