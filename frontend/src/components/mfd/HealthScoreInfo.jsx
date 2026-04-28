import React, { useState } from "react";
import { Info, X, Shield, Layers, Coins, TrendingUp } from "lucide-react";

/**
 * HealthScoreInfo — a small ⓘ button that opens a modal explaining
 * exactly how Diversification, Risk, Cost, and Performance scores roll
 * up into the overall Portfolio Health. Mirrors `services/portfolio_health.py`
 * so any change to the engine should be reflected here too.
 *
 * Usage:
 *   <HealthScoreInfo />
 *
 * The button is purposely small (h-4 w-4, ghost) so it sits next to a
 * section title without grabbing attention until the user wants help.
 */
export default function HealthScoreInfo({ testId = "health-info-btn" }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid={testId}
        className="ml-1 text-slate-400 hover:text-indigo-600 transition-colors"
        title="How is this calculated?"
        aria-label="How is the Portfolio Health calculated?"
      >
        <Info className="w-3.5 h-3.5" />
      </button>
      {open && <HealthScoreModal onClose={() => setOpen(false)} />}
    </>
  );
}

function HealthScoreModal({ onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
      data-testid="health-info-modal"
    >
      <div
        className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-200 dark:border-slate-800">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-indigo-600 font-bold mb-0.5">
              How we score
            </div>
            <div className="text-lg font-bold text-slate-900 dark:text-slate-100">
              Portfolio Health · breakdown
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
            data-testid="health-info-close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-auto p-5 space-y-5">
          {/* Top-level formula */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-1.5">
              The headline number
            </h3>
            <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-lg p-3 font-mono text-xs text-indigo-900 dark:text-indigo-200">
              Health = 0.30 × <strong>D</strong> + 0.25 × <strong>R</strong> + 0.20 × <strong>C</strong> + 0.25 × <strong>P</strong>
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-400 mt-2">
              Each sub-score is on a 0–100 scale. Weights are chosen so a single weak area
              cannot tank the whole grade — diversification has the largest single weight
              because it's the one factor an investor controls directly.
            </p>
          </section>

          {/* Grade ladder */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-2">
              Grade ladder
            </h3>
            <div className="grid grid-cols-7 gap-1 text-[10px] font-bold text-center">
              {[
                ["≥ 90", "A+", "bg-emerald-100 text-emerald-700"],
                ["80–89", "A", "bg-emerald-50 text-emerald-700"],
                ["70–79", "B+", "bg-lime-50 text-lime-700"],
                ["60–69", "B", "bg-amber-50 text-amber-700"],
                ["50–59", "C", "bg-orange-50 text-orange-700"],
                ["40–49", "D", "bg-rose-50 text-rose-700"],
                ["< 40", "F", "bg-rose-100 text-rose-800"],
              ].map(([range, grade, cls]) => (
                <div key={grade} className={`rounded-md py-1.5 ${cls}`}>
                  <div className="text-sm">{grade}</div>
                  <div className="text-[9px] opacity-80 font-normal">{range}</div>
                </div>
              ))}
            </div>
          </section>

          {/* Components */}
          <section className="space-y-3">
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200">
              How each component is calculated
            </h3>

            <Component
              icon={<Layers className="w-4 h-4 text-indigo-500" />}
              code="D"
              title="Diversification"
              weight="30%"
              tone="indigo"
            >
              <Formula>0.5·Concentration + 0.3·Allocation + 0.2·Overlap</Formula>
              <ul className="text-xs text-slate-600 dark:text-slate-400 list-disc list-inside space-y-0.5">
                <li>
                  <strong>Concentration</strong> — top-1 holding, top-5 holdings, sector concentration,
                  effective-N (target ≥ 40 distinct exposures).
                </li>
                <li>
                  <strong>Allocation</strong> — distance from the target equity / debt / gold mix
                  for the client's risk profile (Conservative 30/60/10 · Moderate 60/30/10 · Aggressive 80/10/10).
                  Horizon &lt; 5 years caps equity at 40%.
                </li>
                <li>
                  <strong>Overlap</strong> — fund-vs-fund holdings overlap. Two large-cap funds with
                  60%+ shared stocks score poorly here.
                </li>
              </ul>
            </Component>

            <Component
              icon={<Shield className="w-4 h-4 text-emerald-500" />}
              code="R"
              title="Risk"
              weight="25%"
              tone="emerald"
            >
              <Formula>100 − (0.6 × VolScore + 0.4 × DrawdownScore)</Formula>
              <ul className="text-xs text-slate-600 dark:text-slate-400 list-disc list-inside space-y-0.5">
                <li>
                  <strong>Volatility band</strong> — 8% (low) → 30% (high). Below 8% scores 100,
                  above 30% scores 0.
                </li>
                <li>
                  <strong>Drawdown band</strong> — 5% (low) → 50% (high). Worst rolling drawdown over
                  the available history.
                </li>
                <li>
                  Score is INVERTED in the formula so "more risk" = lower R sub-score, which then
                  feeds into the overall health where higher = better.
                </li>
              </ul>
            </Component>

            <Component
              icon={<Coins className="w-4 h-4 text-amber-500" />}
              code="C"
              title="Cost"
              weight="20%"
              tone="amber"
            >
              <Formula>0.7·ExpenseScore + 0.3·TaxEfficiencyScore</Formula>
              <ul className="text-xs text-slate-600 dark:text-slate-400 list-disc list-inside space-y-0.5">
                <li>
                  <strong>Expense ratio</strong> — TER ≤ 0.5% scores 100; TER ≥ 2% scores 0
                  (linear interpolation between).
                </li>
                <li>
                  <strong>Tax efficiency</strong> — annualised tax drag from churn / IDCW / debt
                  short-term gains. ≤ 0.5% drag scores 100; ≥ 4% scores 0.
                </li>
                <li>
                  Direct stocks use a flat 0.2% p.a. brokerage / slippage proxy.
                </li>
              </ul>
            </Component>

            <Component
              icon={<TrendingUp className="w-4 h-4 text-rose-500" />}
              code="P"
              title="Performance"
              weight="25%"
              tone="rose"
            >
              <Formula>0.5·SharpeScore + 0.3·AlphaScore + 0.2·ConsistencyScore</Formula>
              <ul className="text-xs text-slate-600 dark:text-slate-400 list-disc list-inside space-y-0.5">
                <li>
                  <strong>Sharpe</strong> — return-per-unit-of-risk vs the risk-free rate (G-Sec yield).
                </li>
                <li>
                  <strong>Alpha</strong> — excess return over the benchmark (NIFTY 500 for large/mid,
                  category index for sector / debt / gold funds).
                </li>
                <li>
                  <strong>Consistency</strong> — how often the rolling 1-year return beats the
                  benchmark over the last 36 months.
                </li>
              </ul>
            </Component>
          </section>

          {/* Risk vs Profile chip */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-1.5">
              "Risk vs profile" chip
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-400">
              Compares the portfolio's actual equity allocation to the band allowed by the client's
              risk profile (Conservative 0–40% / Moderate 30–80% / Aggressive 50–100%).
              <strong> "Well within profile"</strong> = portfolio is at or below the band ceiling.
              <strong> "Over-risk"</strong> = exceeded the ceiling. <strong>"Under-allocated"</strong> = below the floor.
            </p>
          </section>

          {/* Top issues */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-1.5">
              Top issues hurting health · "+9.0" potential gain
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-400">
              Each issue carries an estimated <strong>health-point uplift</strong> if fully resolved.
              Numbers are computed by re-running the Health formula with that single defect fixed,
              everything else unchanged. The "Fix all → 63 → 75" pill is the sum of those uplifts,
              capped at 100.
            </p>
          </section>

          {/* Footer note */}
          <section className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3">
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              <strong>Engine:</strong> <code>services/portfolio_health.py</code> (v3 production).
              Calibration constants and formulae are documented in section 7A.1 of <code>README.md</code>.
              Component scores are recomputed on every <em>Refresh</em> — there is no cache, so latest
              CAS / NAV data is always reflected.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────
function Component({ icon, code, title, weight, tone, children }) {
  const toneRing = {
    indigo: "border-indigo-200 dark:border-indigo-800",
    emerald: "border-emerald-200 dark:border-emerald-800",
    amber: "border-amber-200 dark:border-amber-800",
    rose: "border-rose-200 dark:border-rose-800",
  }[tone] || "border-slate-200 dark:border-slate-700";

  return (
    <div className={`rounded-lg border ${toneRing} p-3 space-y-2`}>
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm font-bold text-slate-800 dark:text-slate-200">
          {code} — {title}
        </span>
        <span className="ml-auto text-[10px] uppercase tracking-wider font-bold text-slate-500 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
          weight {weight}
        </span>
      </div>
      {children}
    </div>
  );
}

function Formula({ children }) {
  return (
    <div className="bg-slate-50 dark:bg-slate-800/50 rounded-md p-2 font-mono text-[11px] text-slate-700 dark:text-slate-300">
      {children}
    </div>
  );
}
