import React from "react";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import {
  Sparkles, CheckCircle2, AlertTriangle, Wrench, ShieldCheck, Info,
  Wallet, Layers, TrendingDown, Droplets,
} from "lucide-react";

/**
 * V2.5 Plan Hero Card — "one-screen decision" surface.
 *
 * Surfaces the three numbers that actually matter:
 *   • portfolio_score (0-100 donut)
 *   • confidence_score + label
 *   • plan_summary (hero text)
 * plus the before→after improvements grid and degraded / do-nothing banners.
 */

const SCORE_COLOR = (s) => {
  if (s >= 80) return "#10b981";   // emerald
  if (s >= 60) return "#f59e0b";   // amber
  if (s >= 40) return "#f97316";   // orange
  return "#ef4444";                 // red
};

const SCORE_LABEL = (s) => {
  if (s >= 80) return "Healthy";
  if (s >= 60) return "Good";
  if (s >= 40) return "Needs work";
  return "Critical";
};

const CONF_COLOR = {
  High:   "text-emerald-700 bg-emerald-50 border-emerald-200",
  Medium: "text-amber-700 bg-amber-50 border-amber-200",
  Low:    "text-red-700 bg-red-50 border-red-200",
};

const ScoreDonut = ({ score, size = 108 }) => {
  const s = Number(score) || 0;
  const color = SCORE_COLOR(s);
  const data = [
    { name: "filled", value: s, color },
    { name: "rest", value: Math.max(0, 100 - s), color: "#e2e8f0" },
  ];
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            cx="50%"
            cy="50%"
            innerRadius={size * 0.34}
            outerRadius={size * 0.47}
            startAngle={90}
            endAngle={-270}
            paddingAngle={2}
            stroke="transparent"
            isAnimationActive={false}
          >
            {data.map((d, i) => <Cell key={i} fill={d.color} />)}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <span className="text-3xl font-black tabular-nums" style={{ color }}>
          {Math.round(s)}
        </span>
        <span className="text-[9px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          / 100
        </span>
      </div>
    </div>
  );
};

const DeltaPill = ({ icon: Icon, label, before, after, suffix = "%", improved = true }) => {
  // Skip when there is no delta worth showing
  if (before === undefined || after === undefined) return null;
  const noChange = Math.abs((after || 0) - (before || 0)) < 0.5;
  const color = noChange
    ? "text-slate-400 bg-slate-50 border-slate-200"
    : improved
    ? "text-emerald-700 bg-emerald-50 border-emerald-200"
    : "text-red-700 bg-red-50 border-red-200";
  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${color}`}>
      <Icon className="w-3.5 h-3.5 flex-shrink-0" strokeWidth={2} />
      <div className="flex flex-col">
        <span className="text-[9px] font-bold uppercase tracking-wider opacity-75">{label}</span>
        <span className="text-xs font-semibold tabular-nums">
          {Number(before).toFixed(0)}{suffix}
          <span className="mx-1 opacity-60">→</span>
          {Number(after).toFixed(0)}{suffix}
        </span>
      </div>
    </div>
  );
};

const PlanHeroCard = ({ plan }) => {
  if (!plan) return null;
  const score = Number(plan.portfolio_score || 0);
  const confScore = Number(plan.confidence_score || 0);
  const confLabel = plan.confidence_breakdown?.label || "—";
  const summary = plan.plan_summary || "";
  const improvements = plan.improvements || {};
  const tti = plan.total_tax_impact || plan.tax_impact || {};
  const totalTax = tti.total_tax_liability || tti.total_tax || 0;
  const cost = improvements.annual_cost_saving_rs || 0;

  const actionCount = plan.total_actions ?? (plan.actions?.length || 0);
  const doNothing = !!plan.do_nothing;
  const degraded = !!plan.degraded;

  return (
    <div
      data-testid="plan-hero-card"
      className={`relative rounded-2xl border-2 ${
        doNothing
          ? "border-emerald-200 dark:border-emerald-900/60 bg-gradient-to-br from-emerald-50 via-white to-emerald-50 dark:from-emerald-950/20 dark:via-slate-900 dark:to-emerald-950/10"
          : "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
      } shadow-sm p-5 mb-6 overflow-hidden`}
    >
      {/* Degraded banner */}
      {degraded && (
        <div
          data-testid="plan-degraded-banner"
          className="flex items-start gap-2 mb-4 -mx-5 -mt-5 px-5 py-2.5 bg-amber-50 dark:bg-amber-950/30 border-b border-amber-200 dark:border-amber-900/60"
        >
          <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" strokeWidth={2} />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-bold text-amber-900 dark:text-amber-200">
              V2 running in degraded mode
            </p>
            <p className="text-[11px] text-amber-700 dark:text-amber-300/80 line-clamp-2">
              {plan.degraded_reason || "Some analytics are unavailable. Plan is ~70% quality until datastore recovers."}
            </p>
          </div>
        </div>
      )}

      <div className="flex flex-col lg:flex-row gap-5">
        {/* LEFT — Score + Labels */}
        <div className="flex flex-row lg:flex-col items-center lg:items-start gap-4 lg:w-[200px] flex-shrink-0">
          <ScoreDonut score={score} />
          <div className="flex flex-col gap-1.5 flex-1 min-w-0">
            <span
              className="text-[10px] font-bold uppercase tracking-widest"
              style={{ color: SCORE_COLOR(score) }}
            >
              Portfolio · {SCORE_LABEL(score)}
            </span>
            <div
              data-testid="plan-confidence-badge"
              className={`inline-flex items-center gap-1 self-start px-2 py-1 rounded-full border text-[10px] font-bold ${CONF_COLOR[confLabel] || CONF_COLOR.Medium}`}
              title={`System health ${plan.confidence_breakdown?.system_health || 0}% · Data ${plan.confidence_breakdown?.data_completeness || 0}% · Tax ${plan.confidence_breakdown?.tax_certainty || 0}%`}
            >
              <ShieldCheck className="w-3 h-3" />
              Confidence {Math.round(confScore)}% · {confLabel}
            </div>
          </div>
        </div>

        {/* RIGHT — Summary + Improvements */}
        <div className="flex-1 min-w-0">
          {doNothing ? (
            /* ── Do-Nothing celebratory state ──────────────────────── */
            <div
              data-testid="plan-do-nothing-card"
              className="flex items-start gap-3 py-2"
            >
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center flex-shrink-0 shadow-sm">
                <CheckCircle2 className="w-5 h-5 text-white" strokeWidth={2} />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-black text-emerald-900 dark:text-emerald-200 leading-tight">
                  Nothing to fix right now
                </h3>
                <p className="text-sm text-emerald-700 dark:text-emerald-300/80 mt-1 leading-relaxed">
                  {summary}
                </p>
                <p className="text-[11px] text-emerald-600/80 dark:text-emerald-400/70 mt-3 italic flex items-center gap-1">
                  <Info className="w-3 h-3" />
                  Sticking with your plan usually beats trading. Review next quarter.
                </p>
              </div>
            </div>
          ) : (
            /* ── Active-plan state ────────────────────────────────── */
            <>
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center flex-shrink-0 shadow-sm">
                  <Sparkles className="w-5 h-5 text-white" strokeWidth={2} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-base font-bold text-slate-900 dark:text-white leading-tight">
                      {actionCount} recommended action{actionCount !== 1 ? "s" : ""}
                    </h3>
                    {plan.metadata?.engine_version && (
                      <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        V2 engine
                      </span>
                    )}
                  </div>
                  <p
                    data-testid="plan-summary-text"
                    className="text-[13px] leading-relaxed text-slate-600 dark:text-slate-300 mt-1.5"
                  >
                    {summary || "Your action plan is ready."}
                  </p>
                </div>
              </div>

              {/* Improvements grid (before → after) */}
              {(improvements.overlap_pct || improvements.top_amc_pct || improvements.debt_pct || totalTax > 0 || cost > 0) && (
                <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2">
                  <DeltaPill
                    icon={Layers}
                    label="Overlap"
                    before={improvements.overlap_pct?.before}
                    after={improvements.overlap_pct?.after}
                    improved={(improvements.overlap_pct?.before || 0) > (improvements.overlap_pct?.after || 0)}
                  />
                  <DeltaPill
                    icon={TrendingDown}
                    label="Top AMC"
                    before={improvements.top_amc_pct?.before}
                    after={improvements.top_amc_pct?.after}
                    improved={(improvements.top_amc_pct?.before || 0) > (improvements.top_amc_pct?.after || 0)}
                  />
                  <DeltaPill
                    icon={Droplets}
                    label="Debt"
                    before={improvements.debt_pct?.before}
                    after={improvements.debt_pct?.after}
                    improved={(improvements.debt_pct?.after || 0) > (improvements.debt_pct?.before || 0)}
                  />
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:border-emerald-900/60 dark:text-emerald-300">
                    {cost > 0 ? (
                      <>
                        <Wallet className="w-3.5 h-3.5 flex-shrink-0" strokeWidth={2} />
                        <div className="flex flex-col">
                          <span className="text-[9px] font-bold uppercase tracking-wider opacity-75">Save/yr</span>
                          <span className="text-xs font-semibold tabular-nums">
                            ₹{cost >= 1000 ? `${(cost / 1000).toFixed(1)}k` : Math.round(cost)}
                          </span>
                        </div>
                      </>
                    ) : (
                      <>
                        <Wrench className="w-3.5 h-3.5 flex-shrink-0" strokeWidth={2} />
                        <div className="flex flex-col">
                          <span className="text-[9px] font-bold uppercase tracking-wider opacity-75">Est. tax</span>
                          <span className="text-xs font-semibold tabular-nums">
                            {totalTax > 0 ? `₹${totalTax >= 1000 ? `${(totalTax / 1000).toFixed(1)}k` : Math.round(totalTax)}` : "—"}
                          </span>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default PlanHeroCard;
