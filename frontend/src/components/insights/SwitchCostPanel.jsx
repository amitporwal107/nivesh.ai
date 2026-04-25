import React from "react";
import { TrendingUp, AlertTriangle, Calendar, Zap } from "lucide-react";

/**
 * Cost-of-Switch panel — visualises the PRD framework:
 *   Switch Cost % = Exit Load % + Tax Impact % + Slippage %
 *   Compare to Alpha %/yr → payback months
 *
 * Designed to sit inside an expanded fund row; pure read-only, no API calls.
 *
 * Props:
 *   impact: {switch_cost_pct, tax_impact_pct, exit_load_pct, slippage_pct,
 *            alpha_pct_annual, cost_saving, alpha_gain, tax_cost, exit_cost,
 *            slippage_cost, net_benefit}
 *   recommendation, action_strength, action: from the engine output
 *   testidPrefix: optional, defaults to "switch-cost"
 */
export default function SwitchCostPanel({
  impact,
  recommendation,
  action_strength: actionStrength,
  action,
  testidPrefix = "switch-cost",
}) {
  if (!impact) return null;
  // Pull and default — backend may send 0 or null on no-switch holdings.
  const cost = Number(impact.switch_cost_pct ?? 0);
  const tax = Number(impact.tax_impact_pct ?? 0);
  const exit = Number(impact.exit_load_pct ?? 0);
  const slip = Number(impact.slippage_pct ?? 0);
  const alpha = Number(impact.alpha_pct_annual ?? 0);
  const netBenefit = Number(impact.net_benefit ?? 0);

  // Edge case: no meaningful data, skip rendering
  if (cost === 0 && alpha === 0 && netBenefit === 0) return null;

  // Decision tone — friction band drives the colour
  let band, bandLabel, BandIcon;
  if (cost < 1) {
    band = "emerald"; bandLabel = "Low friction"; BandIcon = Zap;
  } else if (cost < 2) {
    band = "amber"; bandLabel = "Moderate friction"; BandIcon = TrendingUp;
  } else {
    band = "rose"; bandLabel = "High friction"; BandIcon = AlertTriangle;
  }
  const isStaggered = action === "STAGGERED_SWITCH";
  if (isStaggered) {
    band = "indigo"; bandLabel = "Staggered (STP)"; BandIcon = Calendar;
  }

  // Payback period in months. Only meaningful when alpha > 0.
  // payback_yrs = cost% / alpha%/yr. months = payback_yrs × 12.
  const paybackMonths = alpha > 0 ? Math.round((cost / alpha) * 12) : null;

  // Visual ratio for the cost-vs-alpha bars (capped to keep layout sane).
  const maxScale = Math.max(cost, alpha, 4) * 1.05;
  const costPct = (cost / maxScale) * 100;
  const alphaPct = (alpha / maxScale) * 100;

  const tones = {
    emerald: {
      head: "border-emerald-200 bg-emerald-50 dark:bg-emerald-900/20 dark:border-emerald-800",
      pill: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
      bar:  "bg-emerald-500",
    },
    amber: {
      head: "border-amber-200 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800",
      pill: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
      bar:  "bg-amber-500",
    },
    rose: {
      head: "border-rose-200 bg-rose-50 dark:bg-rose-900/20 dark:border-rose-800",
      pill: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
      bar:  "bg-rose-500",
    },
    indigo: {
      head: "border-indigo-200 bg-indigo-50 dark:bg-indigo-900/20 dark:border-indigo-800",
      pill: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300",
      bar:  "bg-indigo-500",
    },
  };
  const t = tones[band];

  const fmtRs = (v) => {
    const n = Number(v) || 0;
    if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)}Cr`;
    if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)}L`;
    if (n >= 1000) return `₹${(n / 1000).toFixed(1)}k`;
    return `₹${n.toFixed(0)}`;
  };

  return (
    <div
      className={`mt-3 rounded-md border ${t.head} px-3 py-2.5`}
      data-testid={`${testidPrefix}-panel`}
    >
      <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
        <div className="flex items-center gap-2">
          <div className="text-[9px] uppercase tracking-wider font-bold text-slate-600 dark:text-slate-400">
            Cost of Switch
          </div>
          <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold ${t.pill}`}>
            <BandIcon className="w-3 h-3" />
            {bandLabel}
          </span>
          {recommendation && (
            <span className="text-[10px] text-slate-500 dark:text-slate-400">
              · {recommendation}{actionStrength ? `/${actionStrength}` : ""}
            </span>
          )}
        </div>
        {paybackMonths != null && (
          <div className="text-[11px] text-slate-700 dark:text-slate-300" data-testid={`${testidPrefix}-payback`}>
            Payback: <span className="font-bold tabular-nums">{paybackMonths}</span> {paybackMonths === 1 ? "month" : "months"}
          </div>
        )}
      </div>

      {/* Two-bar comparison: cost (red/amber) vs alpha (emerald) */}
      <div className="space-y-1.5 mb-3" data-testid={`${testidPrefix}-bars`}>
        <div>
          <div className="flex items-center justify-between text-[10.5px] font-medium mb-0.5">
            <span className="text-slate-600 dark:text-slate-400">Total switch cost</span>
            <span className={`font-mono tabular-nums ${t.pill.split(" ").slice(1, 2).join(" ")}`} data-testid={`${testidPrefix}-cost-pct`}>
              {cost.toFixed(2)}%
            </span>
          </div>
          <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
            <div className={`h-full ${t.bar} transition-all`} style={{ width: `${costPct}%` }} />
          </div>
        </div>
        <div>
          <div className="flex items-center justify-between text-[10.5px] font-medium mb-0.5">
            <span className="text-slate-600 dark:text-slate-400">Alpha (annual)</span>
            <span className="font-mono tabular-nums text-emerald-700 dark:text-emerald-400" data-testid={`${testidPrefix}-alpha-pct`}>
              {alpha.toFixed(2)}%/yr
            </span>
          </div>
          <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
            <div className="h-full bg-emerald-500 transition-all" style={{ width: `${alphaPct}%` }} />
          </div>
        </div>
      </div>

      {/* Cost breakdown chips */}
      <div className="flex items-center gap-1.5 flex-wrap text-[10px]" data-testid={`${testidPrefix}-breakdown`}>
        <span className="text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">Breakdown:</span>
        <CostChip label="Tax" pct={tax} rs={impact.tax_cost} />
        <CostChip label="Exit load" pct={exit} rs={impact.exit_cost} />
        <CostChip label="Slippage" pct={slip} rs={impact.slippage_cost} />
        <span className="text-slate-400 dark:text-slate-500">=</span>
        <span className={`px-1.5 py-0.5 rounded font-mono tabular-nums font-bold ${t.pill}`}>
          {cost.toFixed(2)}%
        </span>
      </div>

      {/* Net benefit footer */}
      {(netBenefit !== 0 || (impact.cost_saving > 0 || impact.alpha_gain > 0)) && (
        <div className="text-[10.5px] text-slate-600 dark:text-slate-400 mt-2 flex items-center gap-2 flex-wrap" data-testid={`${testidPrefix}-footer`}>
          <span>
            Cost saving: <span className="font-mono tabular-nums text-emerald-700 dark:text-emerald-400">{fmtRs(impact.cost_saving)}</span>
          </span>
          {impact.alpha_gain > 0 && (
            <>
              <span className="text-slate-300 dark:text-slate-600">·</span>
              <span>
                Alpha gain: <span className="font-mono tabular-nums text-emerald-700 dark:text-emerald-400">{fmtRs(impact.alpha_gain)}</span>
              </span>
            </>
          )}
          <span className="text-slate-300 dark:text-slate-600">·</span>
          <span className="font-semibold">
            Net: <span className={`font-mono tabular-nums ${netBenefit >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}`}>
              {netBenefit >= 0 ? "+" : ""}{fmtRs(netBenefit)}
            </span>
          </span>
        </div>
      )}
    </div>
  );
}

const CostChip = ({ label, pct, rs }) => {
  const v = Number(pct ?? 0);
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-white/70 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-700"
      title={rs ? `${label}: ₹${Number(rs).toLocaleString("en-IN")}` : `${label}: ${v.toFixed(2)}%`}
      data-testid={`switch-cost-chip-${label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="font-mono tabular-nums text-slate-800 dark:text-slate-200 font-semibold">
        {v.toFixed(v < 1 ? 2 : 1)}%
      </span>
    </span>
  );
};
