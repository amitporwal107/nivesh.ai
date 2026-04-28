import React, { useState } from "react";
import { Info, X, IndianRupee, TrendingUp, AlertTriangle, Target, Scissors, Clock } from "lucide-react";

/**
 * TaxSnapshotInfo — small ⓘ button that opens a modal explaining how
 * STCG / LTCG / debt slab tax is computed and how each harvest pick is
 * generated. Mirrors the post-Jul-2024 / post-Apr-2023 Indian MF tax
 * regime codified in `routes/mfd.py:tax_summary` and the user-approved
 * "10 golden harvest rules" spec.
 */
export default function TaxSnapshotInfo({ testId = "tax-info-btn" }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid={testId}
        className="ml-1 text-slate-400 hover:text-violet-600 transition-colors"
        title="How is this calculated?"
        aria-label="How is the tax snapshot calculated?"
      >
        <Info className="w-3.5 h-3.5" />
      </button>
      {open && <TaxSnapshotModal onClose={() => setOpen(false)} />}
    </>
  );
}

function TaxSnapshotModal({ onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
      data-testid="tax-info-modal"
    >
      <div
        className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-5 border-b border-slate-200 dark:border-slate-800">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-violet-600 font-bold mb-0.5">
              How we calculate tax
            </div>
            <div className="text-lg font-bold text-slate-900 dark:text-slate-100">
              Tax snapshot · methodology
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
            data-testid="tax-info-close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="overflow-auto p-5 space-y-5">
          {/* Regime headline */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-1.5">
              Regime — post-Jul-2024 / post-Apr-2023
            </h3>
            <div className="bg-violet-50 dark:bg-violet-900/20 rounded-lg p-3 text-xs text-violet-900 dark:text-violet-200 space-y-0.5">
              <div>• <strong>Tax applies only on sale / redemption / switch</strong> — not on holdings.</div>
              <div>• <strong>Switching = sale + buy</strong>; holding period resets, tax payable now.</div>
              <div>• Cess + 4% surcharge on top of tax.</div>
            </div>
          </section>

          {/* Bucket table */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-2">
              Tax buckets
            </h3>
            <div className="space-y-2.5">
              <Bucket
                icon={<TrendingUp className="w-4 h-4 text-emerald-500" />}
                color="emerald"
                title="Equity (≥ 65% equity exposure)"
                rules={[
                  ["< 12 months", "STCG · 20% (was 15% pre-Jul 2024)"],
                  ["≥ 12 months", "LTCG · 12.5% on gains beyond ₹1.25 L / FY"],
                ]}
                note="No indexation. Includes equity MFs, hybrid funds with ≥65% equity, ETFs, direct stocks."
              />
              <Bucket
                icon={<IndianRupee className="w-4 h-4 text-rose-500" />}
                color="rose"
                title="Debt / specified MFs (post-Apr-2023)"
                rules={[
                  ["Any holding period", "Slab rate · default 30% (UI may override)"],
                ]}
                note="No LTCG benefit, no indexation. Includes funds with <65% equity exposure."
              />
              <Bucket
                icon={<TrendingUp className="w-4 h-4 text-amber-500" />}
                color="amber"
                title="Debt LTCG legacy (pre-Apr-2023 lots)"
                rules={[
                  ["≥ 36 months", "LTCG · 12.5% (no indexation)"],
                  ["< 36 months", "Slab rate"],
                ]}
                note="Applies only to debt lots purchased BEFORE 1 Apr 2023."
              />
              <Bucket
                icon={<TrendingUp className="w-4 h-4 text-violet-500" />}
                color="violet"
                title="Hybrid / Gold / International"
                rules={[
                  ["≥ 65% equity", "Equity rules above"],
                  ["< 65% equity", "Debt rules above"],
                ]}
                note="Equity exposure read from fund metadata (`equity_exposure_pct`)."
              />
            </div>
          </section>

          {/* The big numbers */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-1.5">
              The 4 big numbers
            </h3>
            <ul className="text-xs text-slate-600 dark:text-slate-400 space-y-1.5">
              <li><strong>Unrealized gain</strong> = Σ (current_value − invested) across all holdings.</li>
              <li><strong>STCG exposure</strong> = Σ gains in equity STCG + debt slab buckets (capped at 0; losses excluded).</li>
              <li><strong>LTCG exposure</strong> = Σ gains in equity LTCG + debt LTCG legacy buckets.</li>
              <li><strong>If realised today</strong> = Σ (bucket gain × bucket rate) + 4% cess. Equity LTCG applies the ₹1.25L exemption first.</li>
            </ul>
          </section>

          {/* Harvest opportunities */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-2">
              Harvest opportunities — how we pick them
            </h3>
            <div className="space-y-2.5">
              <Pick
                icon={<Target className="w-4 h-4 text-emerald-600" />}
                title="Realize tax-free (Rule 1)"
                rule="Equity LTCG winners — sell up to ₹1.25 L gain this FY → ₹0 tax."
                formula="bucket = equity_ltcg AND gain > 0"
                action="Sell + immediately re-buy → resets cost basis at no tax cost."
              />
              <Pick
                icon={<Scissors className="w-4 h-4 text-rose-600" />}
                title="Loss-harvest candidates (Rule 4)"
                rule="Losers ≥ ₹1,000 in any bucket. Offset against STCG (any asset) or LTCG (same category). Carry forward 8 years."
                formula="gain < 0 AND |gain| ≥ ₹1,000"
                action="Book the loss; reinvest in a similar fund (not identical — avoid wash-sale ambiguity)."
              />
              <Pick
                icon={<Clock className="w-4 h-4 text-indigo-600" />}
                title="Wait it out (Rule 10)"
                rule="Equity STCG winners within 30 days of crossing the 12-month LT line."
                formula="bucket = equity_stcg AND gain > 0 AND days_held ∈ [336, 365]"
                action="Hold → save (20% − 12.5%) = 7.5% on the gain. Surfaced as ‘+Nd · save ₹X'."
              />
            </div>
          </section>

          {/* What we don't show automatically */}
          <section>
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-1.5">
              Out of scope (advisor judgement)
            </h3>
            <ul className="text-xs text-slate-600 dark:text-slate-400 space-y-1 list-disc list-inside">
              <li>
                <strong>Rule 3 — harvest in low-income years.</strong> Combine basic exemption + LTCG
                exemption to pay zero tax. Surfaced via AI advisor recommendations, not auto-flagged.
              </li>
              <li>
                <strong>Rule 8 — family member arbitrage.</strong> Spread investments across spouse /
                parents in lower brackets to multiply ₹1.25 L exemption.
              </li>
              <li>
                <strong>Rule 9 — ELSS deduction</strong> available only in the old tax regime; no
                action shown in the new regime.
              </li>
              <li>
                <strong>Rule 7 — SIP lot-level harvesting.</strong> Each SIP installment has its own
                holding period. Lot-level harvest scoring is enabled once we have the structured
                CAS transactions (in progress — see the "View parsed statement" link on snapshots).
              </li>
            </ul>
          </section>

          {/* Caveats */}
          <section className="bg-amber-50 dark:bg-amber-900/20 rounded-lg p-3 border border-amber-200 dark:border-amber-800">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
              <div className="text-xs text-amber-800 dark:text-amber-300 space-y-1">
                <div><strong>Indicative only.</strong> Actual tax depends on your full income, deductions, and basis adjustments your CA may apply.</div>
                <div><strong>Holdings without buy date</strong> are routed to ‘Undated' and are not included in STCG/LTCG buckets. Re-import the CAS to fix.</div>
                <div><strong>STT</strong> (0.001% on equity-fund redemptions) is not deducted from the indicative tax — it's applied at source by the AMC.</div>
              </div>
            </div>
          </section>

          {/* Engine reference */}
          <section className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3">
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              <strong>Engine:</strong> <code>routes/mfd.py → tax_summary</code> +
              <code> services/tax_calculator.py</code>. Constants
              (<code>EQUITY_STCG_RATE</code>, <code>EQUITY_LTCG_RATE</code>,
              <code> LTCG_EXEMPTION_INR</code>, <code>DEBT_SLAB_RATE</code>, <code>CESS_PCT</code>)
              live at the top of the route handler.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

function Bucket({ icon, color, title, rules, note }) {
  const ring = {
    emerald: "border-emerald-200 dark:border-emerald-800",
    rose:    "border-rose-200 dark:border-rose-800",
    amber:   "border-amber-200 dark:border-amber-800",
    violet:  "border-violet-200 dark:border-violet-800",
  }[color] || "border-slate-200 dark:border-slate-700";
  return (
    <div className={`rounded-lg border ${ring} p-3`}>
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-sm font-bold text-slate-800 dark:text-slate-200">{title}</span>
      </div>
      <table className="w-full text-[11px] mb-1.5">
        <tbody>
          {rules.map(([k, v]) => (
            <tr key={k}>
              <td className="text-slate-500 dark:text-slate-400 py-0.5 pr-3">{k}</td>
              <td className="text-slate-800 dark:text-slate-200 font-semibold py-0.5">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="text-[10px] text-slate-500 dark:text-slate-400 italic">{note}</div>
    </div>
  );
}

function Pick({ icon, title, rule, formula, action }) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 space-y-1.5">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm font-bold text-slate-800 dark:text-slate-200">{title}</span>
      </div>
      <div className="text-xs text-slate-600 dark:text-slate-400">{rule}</div>
      <div className="bg-slate-50 dark:bg-slate-800/50 rounded font-mono text-[10px] text-slate-700 dark:text-slate-300 px-2 py-1">
        {formula}
      </div>
      <div className="text-[11px] text-emerald-700 dark:text-emerald-400">→ {action}</div>
    </div>
  );
}
