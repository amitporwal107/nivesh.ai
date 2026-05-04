import React from "react";
import { CheckCircle2, XCircle, Hourglass, Info, ArrowRight, Calendar } from "lucide-react";

/**
 * Decision Card — the unified per-holding card.
 *
 * Replaces the prior split layout (DecisionVerdict + SwitchCostPanel) with a
 * single card that always answers four questions in order:
 *
 *   1. What should I do?      → action pill + headline
 *   2. Why?                   → 2-3 plain-English bullets
 *   3. What will it cost me?  → tax + other costs in ₹, with the worked example
 *   4. Is it worth it?        → footer verdict (yes/no + payback months)
 *
 * Designed for the holdings expanded row. Pure read-only — all data comes
 * from the enriched holding payload, no API calls.
 *
 * Props:
 *   action            — "ADD" | "SWITCH" | "EXIT" | "HOLD" | "REVIEW"
 *   subAction         — sub-type from action_badge (e.g. "To Direct", "To Peer", "Reduce")
 *   scores            — { quality, health, exit, add }
 *   switchCost        — { switch_cost_pct, tax_impact_pct, exit_load_pct, slippage_pct,
 *                         tax_cost, exit_cost, slippage_cost, alpha_pct_annual,
 *                         net_benefit, cost_saving, alpha_gain }
 *   investedRs        — buy-side cost basis in ₹ (h.invested_rs)
 *   valueRs           — current value in ₹ (h.value_rs)
 *   pnlRs             — gain/loss in ₹ (h.value_rs − h.invested_rs)
 *   buyDate           — earliest holding date (drives <1yr STCG flag)
 *   isEquity          — true for equity MFs, false for debt
 *   recommendationReason — engine-supplied "why" string from action_plan_manager
 *   allocationCurrent / allocationTarget — % of portfolio (drives ADD reasoning)
 *   categoryRank / categoryRankTotal / categoryLabel — peer ranking
 *   benchmarkLabel / benchmarkReturn / fundReturn — benchmark context for SWITCH
 *   alphaAnnual       — expected forward alpha % per year
 *   toFund            — concrete redirect target name (when engine supplied one)
 *   toAllocationPct   — how much of this holding to move (0-100)
 */
export default function DecisionCard({
  action,
  subAction,
  scores,
  switchCost,
  investedRs,
  valueRs,
  pnlRs,
  buyDate,
  isEquity = true,
  recommendationReason,
  allocationCurrent,
  allocationTarget,
  categoryRank,
  categoryRankTotal,
  categoryLabel,
  benchmarkLabel,
  benchmarkReturn,
  fundReturn,
  alphaAnnual,
  toFund,
  toAllocationPct,
}) {
  const cost = Number(switchCost?.switch_cost_pct ?? 0);
  const alpha = Number(alphaAnnual ?? switchCost?.alpha_pct_annual ?? 0);
  const taxRs = Number(switchCost?.tax_cost ?? 0);
  const exitRs = Number(switchCost?.exit_cost ?? 0);
  const slipRs = Number(switchCost?.slippage_cost ?? 0);
  const totalCostRs = taxRs + exitRs + slipRs;
  const netBenefitRs = Number(switchCost?.net_benefit ?? 0);
  const q = scores?.quality;
  const h = scores?.health;

  // Allocation gap (used as the primary ADD justification).
  const gapPP = (allocationCurrent != null && allocationTarget != null)
    ? Number(allocationTarget) - Number(allocationCurrent)
    : null;
  const isUnderallocated = gapPP != null && gapPP >= 0.5;
  const isOverallocated = gapPP != null && gapPP <= -0.5;

  // Category rank → percentile band.
  const rankPct = (categoryRank && categoryRankTotal && categoryRankTotal > 0)
    ? (categoryRank / categoryRankTotal) * 100
    : null;
  const rankBand = rankPct == null
    ? null
    : rankPct <= 25 ? "Top 25%"
    : rankPct <= 50 ? "Top 50%"
    : rankPct <= 75 ? "Bottom 50%"
    : "Bottom 25%";
  const isTopHalf = rankPct != null && rankPct <= 50;

  // STCG detection — for equity, sub-1y holding period bumps tax to 15%.
  const heldDays = (() => {
    if (!buyDate) return null;
    try {
      const bd = new Date(buyDate);
      if (isNaN(bd.getTime())) return null;
      return Math.floor((Date.now() - bd.getTime()) / (1000 * 60 * 60 * 24));
    } catch {
      return null;
    }
  })();
  const isShortTerm = isEquity && heldDays != null && heldDays < 365;

  // Payback months (only when alpha > 0).
  const paybackMonths = alpha > 0 ? Math.round((cost / alpha) * 12) : null;

  // ── Build the four sections by action ──────────────────────────────
  const decision = buildDecision({
    action, subAction, gapPP, isUnderallocated, isOverallocated,
    rankBand, isTopHalf, categoryRank, categoryRankTotal, categoryLabel,
    allocationCurrent, allocationTarget, q, h,
    cost, alpha, paybackMonths, netBenefitRs, recommendationReason,
    benchmarkLabel, benchmarkReturn, fundReturn,
    toFund, toAllocationPct, valueRs, totalCostRs,
  });

  const t = TONES[decision.tone];
  const Icon = t.Icon;

  return (
    <div
      className={`rounded-xl border-2 ${t.panel} px-5 py-4 mb-4`}
      data-testid="decision-card"
    >
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-lg ${t.icon} flex items-center justify-center flex-shrink-0`}>
          <Icon className="w-5 h-5" strokeWidth={2} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${t.pill}`}
              data-testid="decision-card-badge"
            >
              {decision.verdict.replace(/_/g, " ")}
            </span>
            {benchmarkLabel && (
              <span className="text-[10px] text-slate-500">vs {benchmarkLabel}</span>
            )}
          </div>
          <h3 className={`text-base font-bold mt-1 ${t.head}`} data-testid="decision-card-headline">
            {decision.headline}
          </h3>
        </div>
      </div>

      {/* Section 1: Why */}
      {decision.reasons.length > 0 && (
        <Section title="Why">
          <ul className="space-y-1">
            {decision.reasons.map((r, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[12.5px] text-slate-700">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-slate-400 flex-shrink-0" />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Section 2: What to do */}
      {decision.todo && (
        <Section title="What to do" testid="decision-card-todo">
          <div className="flex items-center gap-2 text-[12.5px] text-slate-800">
            <ArrowRight className="w-4 h-4 text-slate-500 flex-shrink-0" />
            <span>{decision.todo}</span>
          </div>
        </Section>
      )}

      {/* Section 3: Cost & Tax (only when there's a real cost to talk about) */}
      {decision.showCost && (totalCostRs > 0 || investedRs != null) && (
        <Section title="Cost & Tax" testid="decision-card-cost">
          <CostBlock
            invested={investedRs}
            value={valueRs}
            pnl={pnlRs}
            taxRs={taxRs}
            exitRs={exitRs}
            slipRs={slipRs}
            totalCostRs={totalCostRs}
            isEquity={isEquity}
            isShortTerm={isShortTerm}
          />
        </Section>
      )}

      {/* Section 4: Worth it? footer */}
      {decision.worthIt && (
        <div className={`mt-4 pt-3 border-t ${t.divider} flex items-center gap-2 flex-wrap`} data-testid="decision-card-worth">
          <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">Is it worth it?</span>
          <span className={`text-[12.5px] font-semibold ${decision.worthIt.tone}`}>
            {decision.worthIt.text}
          </span>
          {/* Only show numeric payback when cost actually recovers in a
              reasonable horizon (≤36 months). Beyond that the math is
              technically right but the framing ("938 months") trashes
              user trust — the worthIt text already says "not practical". */}
          {paybackMonths != null && paybackMonths <= 36 && decision.showCost && (
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-slate-600">
              <Calendar className="w-3 h-3" />
              Payback ~{paybackMonths} {paybackMonths === 1 ? "month" : "months"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Decision builder: pure function from inputs → card content ──────────
function buildDecision({
  action, subAction, gapPP, isUnderallocated, isOverallocated,
  rankBand, isTopHalf, categoryRank, categoryRankTotal, categoryLabel,
  allocationCurrent, allocationTarget, q, h,
  cost, alpha, paybackMonths, netBenefitRs, recommendationReason,
  benchmarkLabel, benchmarkReturn, fundReturn,
  toFund, toAllocationPct, valueRs, totalCostRs,
}) {
  const strongScoreLine = [
    q != null ? `Q=${Math.round(q)}` : null,
    h != null ? `H=${Math.round(h)}` : null,
  ].filter(Boolean).join(", ");

  // Concrete ₹ amount + target for "What to do" line.
  const moveRs = (toAllocationPct != null && valueRs != null)
    ? Math.round(Number(valueRs) * Number(toAllocationPct) / 100)
    : null;
  const fmtRs = (n) => `₹${Math.round(Number(n)).toLocaleString("en-IN")}`;
  const redirectLine = (() => {
    if (!toFund) return null;
    if (moveRs != null) return `Move ${fmtRs(moveRs)} to ${toFund}`;
    return `Redirect to ${toFund}`;
  })();

  const benchmarkLine = (fundReturn != null && benchmarkReturn != null && benchmarkLabel)
    ? `Fund ${Number(fundReturn).toFixed(2)}% vs ${benchmarkLabel} ${Number(benchmarkReturn).toFixed(2)}% — ${
        fundReturn >= benchmarkReturn
          ? `outperformed by +${(fundReturn - benchmarkReturn).toFixed(2)}pp`
          : `underperformed by ${(fundReturn - benchmarkReturn).toFixed(2)}pp`}`
    : null;

  // ── ₹+% framing helpers (SWITCH section) ──────────────────────────
  // Always show both forms — % builds the ratio intuition, ₹ makes it
  // tangible. "₹5,100 (0.95% of value)" beats "0.95%" alone.
  const costLineWithRs = (() => {
    if (!(cost > 0)) return null;
    if (totalCostRs > 0) return `Switch cost ₹${Math.round(totalCostRs).toLocaleString("en-IN")} (${cost.toFixed(2)}% of value)`;
    return `Switch cost ${cost.toFixed(2)}%`;
  })();
  // 3-year cumulative benefit = annual alpha % × 3 × current value.
  const benefit3yRs = (alpha > 0 && valueRs != null)
    ? Math.round(Number(valueRs) * (Number(alpha) / 100) * 3)
    : null;
  const benefitLine = (() => {
    if (!(alpha > 0)) return null;
    const cum3y = (alpha * 3).toFixed(2);
    const annual = alpha.toFixed(2);
    if (benefit3yRs != null) {
      return `Expected benefit ~₹${benefit3yRs.toLocaleString("en-IN")} over 3 years (${cum3y}% total · ~${annual}%/yr)`;
    }
    return `Expected benefit ${cum3y}% over 3 years (~${annual}%/yr)`;
  })();

  // ── EXIT ──────────────────────────────────────────────────────────
  if (action === "EXIT") {
    return {
      verdict: "EXIT",
      headline: "Recommendation: Exit this fund",
      tone: "rose",
      reasons: [
        recommendationReason || "Engine flagged this for exit (overlap, AMC concentration, or quality drop)",
      ].filter(Boolean),
      todo: redirectLine || (toAllocationPct === 100 ? "Redeem fully and redirect to a debt/liquid fund" : "Redeem and redirect to a debt or liquid fund"),
      showCost: true,
      worthIt: netBenefitRs > 0
        ? { tone: "text-emerald-700", text: `Yes — net benefit ${fmtRs(netBenefitRs)} over a 3-year hold` }
        : netBenefitRs < 0
          ? { tone: "text-rose-700", text: `Cost ${fmtRs(Math.abs(netBenefitRs))} exceeds expected benefit — consider staggered exit` }
          : null,
    };
  }

  // ── HOLD / REVIEW ─────────────────────────────────────────────────
  if (action === "HOLD" || action === "REVIEW") {
    return {
      verdict: "HOLD",
      headline: "Recommendation: Hold for now",
      tone: "slate",
      reasons: [
        recommendationReason || "No action signal at current scores",
      ].filter(Boolean),
      todo: null,
      showCost: false,
      worthIt: null,
    };
  }

  // ── ADD — gap + rank, no alpha gating ─────────────────────────────
  if (action === "ADD") {
    if (isUnderallocated && (rankBand == null || isTopHalf)) {
      const reasons = [
        categoryLabel
          ? `${categoryLabel} allocation ${allocationCurrent.toFixed(1)}% vs target ${allocationTarget.toFixed(1)}% — under by ${gapPP.toFixed(1)}pp`
          : `Allocation ${allocationCurrent.toFixed(1)}% vs target ${allocationTarget.toFixed(1)}% — under by ${gapPP.toFixed(1)}pp`,
      ];
      if (rankBand) reasons.push(`${rankBand} in category (#${categoryRank} of ${categoryRankTotal})`);
      if (strongScoreLine) reasons.push(`Strong fund (${strongScoreLine})`);
      return {
        verdict: "ADD",
        headline: "Recommendation: Add to this fund",
        tone: "emerald",
        reasons,
        todo: "Top up via SIP increase or one-time investment to close the allocation gap",
        showCost: false,
        worthIt: null,
      };
    }
    if (isOverallocated) {
      return {
        verdict: "HOLD",
        headline: "Recommendation: Hold — already at target",
        tone: "slate",
        reasons: [
          categoryLabel
            ? `${categoryLabel} allocation ${allocationCurrent.toFixed(1)}% vs target ${allocationTarget.toFixed(1)}% — over by ${(-gapPP).toFixed(1)}pp`
            : `Allocation ${allocationCurrent.toFixed(1)}% vs target ${allocationTarget.toFixed(1)}% — over by ${(-gapPP).toFixed(1)}pp`,
          "Direct fresh capital to under-allocated buckets first",
        ],
        todo: null,
        showCost: false,
        worthIt: null,
      };
    }
    if (rankBand && !isTopHalf) {
      const reasons = [
        `${rankBand} in category (#${categoryRank} of ${categoryRankTotal}) — better-ranked alternatives exist`,
      ];
      if (strongScoreLine) reasons.push(`Fund scores: ${strongScoreLine}`);
      return {
        verdict: "REVIEW",
        headline: "Recommendation: Review before adding",
        tone: "amber",
        reasons,
        todo: "Compare against top-ranked peers in the same sub-category",
        showCost: false,
        worthIt: null,
      };
    }
    return {
      verdict: "ADD",
      headline: "Recommendation: Add to this fund",
      tone: "emerald",
      reasons: strongScoreLine
        ? [`Strong fund (${strongScoreLine})`, "Allocation context unavailable — confirm portfolio fit"]
        : ["Score signal supports adding — confirm against your target allocation"],
      todo: null,
      showCost: false,
      worthIt: null,
    };
  }

  // ── SWITCH — alpha-gated cost-vs-benefit ──────────────────────────
  if (action === "SWITCH") {
    const cumulativeAlpha3y = alpha * 3;
    const ratio = alpha > 0 ? cost / Math.max(cumulativeAlpha3y, 0.01) : (cost > 0 ? Infinity : 0);
    const costGtBenefitLine = (() => {
      if (totalCostRs > 0 && benefit3yRs != null) {
        return `Cost ${fmtRs(totalCostRs)} > 3-year benefit ${fmtRs(benefit3yRs)}`;
      }
      return `Cost ${cost.toFixed(2)}% > 3-year benefit ${cumulativeAlpha3y.toFixed(2)}%`;
    })();

    if (cost > 0 && alpha === 0) {
      return {
        verdict: "DO_NOT_ACT",
        headline: "Recommendation: Do NOT switch",
        tone: "rose",
        reasons: [
          costLineWithRs,
          "Expected benefit vs benchmark is 0%/yr — no upside to justify the cost",
          benchmarkLine,
        ].filter(Boolean),
        todo: "Continue holding · revisit if the fund's quality scores drop further",
        showCost: true,
        worthIt: { tone: "text-rose-700", text: "No — cost > benefit" },
      };
    }
    if (cost > 0 && ratio > 1.0) {
      return {
        verdict: "DO_NOT_ACT",
        headline: "Recommendation: Do NOT switch",
        tone: "rose",
        reasons: [
          costLineWithRs,
          benefitLine,
          costGtBenefitLine,
          benchmarkLine,
        ].filter(Boolean),
        todo: "Continue holding · or stagger over multiple tax years (₹1L LTCG exemption per year) to cut friction",
        showCost: true,
        worthIt: { tone: "text-rose-700", text: "No — cost recovery would take 3+ years (not practical)" },
      };
    }
    if (cost > 0 && ratio > 0.5) {
      const recoverMonths = Math.round(cost / Math.max(alpha, 0.01) * 12);
      return {
        verdict: "WAIT",
        headline: "Recommendation: Switch later",
        tone: "amber",
        reasons: [
          costLineWithRs,
          benefitLine,
          recoverMonths <= 36
            ? `Cost recovery takes ~${recoverMonths} months — borderline`
            : "Cost recovery would take several years — wait for friction to drop",
        ].filter(Boolean),
        todo: redirectLine || "Stagger the switch across financial years to use the ₹1L LTCG exemption each year",
        showCost: true,
        worthIt: { tone: "text-amber-700", text: "Marginal — wait for better entry" },
      };
    }
    return {
      verdict: subAction === "To Direct" ? "SWITCH TO DIRECT" : "SWITCH",
      headline: subAction === "To Direct"
        ? "Recommendation: Switch to Direct plan"
        : "Recommendation: Switch this fund",
      tone: "emerald",
      reasons: [
        costLineWithRs || "No meaningful cost barrier",
        benefitLine || (alpha === 0 ? null : `Expected alpha ~${alpha.toFixed(2)}%/yr`),
        recommendationReason,
      ].filter(Boolean),
      todo: redirectLine || (subAction === "To Direct" ? "Switch to the Direct variant of the same fund" : "Move to a higher-ranked peer in the same category"),
      showCost: true,
      worthIt: (paybackMonths != null && paybackMonths <= 36)
        ? { tone: "text-emerald-700", text: `Yes — recover cost in ~${paybackMonths} ${paybackMonths === 1 ? "month" : "months"}` }
        : netBenefitRs > 0
          ? { tone: "text-emerald-700", text: `Yes — net benefit ${fmtRs(netBenefitRs)}` }
          : null,
    };
  }

  // ── Fallback ──────────────────────────────────────────────────────
  return {
    verdict: "REVIEW",
    headline: "Recommendation: Review with advisor",
    tone: "slate",
    reasons: ["Score signal exists but cost-benefit isn't clear-cut"],
    todo: null,
    showCost: false,
    worthIt: null,
  };
}

// ── Sub-components ──────────────────────────────────────────────────────
const Section = ({ title, children, testid }) => (
  <div className="mt-3" data-testid={testid}>
    <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-1.5">{title}</div>
    {children}
  </div>
);

const CostBlock = ({ invested, value, pnl, taxRs, exitRs, slipRs, totalCostRs, isEquity, isShortTerm }) => {
  const fmtRs = (n) => `₹${Math.round(Number(n) || 0).toLocaleString("en-IN")}`;
  const gainPositive = pnl != null && pnl > 0;
  const taxRule = (() => {
    if (!isEquity) return "Debt fund — taxed at slab rate on gains";
    if (isShortTerm) return "Held <1 year → 15% STCG on gains";
    return "Held >1 year → 10% LTCG on gains above ₹1L exemption";
  })();

  return (
    <div className="space-y-2">
      {/* Worked example: invested → value → gain → tax */}
      {invested != null && value != null && (
        <div className="text-[12px] text-slate-700 bg-white/60 rounded-md p-2.5 space-y-0.5">
          <div className="flex justify-between">
            <span className="text-slate-500">You invested</span>
            <span className="font-mono tabular-nums">{fmtRs(invested)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Current value</span>
            <span className="font-mono tabular-nums">{fmtRs(value)}</span>
          </div>
          {pnl != null && (
            <div className="flex justify-between border-t border-slate-200 pt-0.5 mt-0.5">
              <span className="text-slate-500">Gain</span>
              <span className={`font-mono tabular-nums font-semibold ${gainPositive ? "text-emerald-700" : "text-rose-700"}`}>
                {pnl >= 0 ? "+" : ""}{fmtRs(pnl)}
              </span>
            </div>
          )}
          <div className="text-[10.5px] text-slate-500 italic pt-1">{taxRule}</div>
        </div>
      )}

      {/* Cost line items in ₹ */}
      <div className="text-[12px] text-slate-700 space-y-0.5">
        <CostLine label="Exit tax" value={taxRs} fmt={fmtRs} />
        {exitRs > 0 && <CostLine label="Exit load" value={exitRs} fmt={fmtRs} />}
        {slipRs > 0 && <CostLine label="Slippage / spread" value={slipRs} fmt={fmtRs} />}
        <div className="flex justify-between pt-1 border-t border-slate-200 font-semibold">
          <span className="text-slate-700">Total cost</span>
          <span className="font-mono tabular-nums">{fmtRs(totalCostRs)}</span>
        </div>
      </div>
    </div>
  );
};

const CostLine = ({ label, value, fmt }) => (
  <div className="flex justify-between">
    <span className="text-slate-500">{label}</span>
    <span className="font-mono tabular-nums">{fmt(value)}</span>
  </div>
);

// ── Tone presets (matches DecisionVerdict for visual continuity) ────────
const TONES = {
  rose:    { panel: "bg-gradient-to-br from-rose-50 to-rose-100/50 border-rose-200",
             head:  "text-rose-900",
             icon:  "text-rose-600 bg-rose-100",
             pill:  "bg-rose-600 text-white",
             divider: "border-rose-200",
             Icon:  XCircle },
  amber:   { panel: "bg-gradient-to-br from-amber-50 to-amber-100/50 border-amber-200",
             head:  "text-amber-900",
             icon:  "text-amber-600 bg-amber-100",
             pill:  "bg-amber-500 text-white",
             divider: "border-amber-200",
             Icon:  Hourglass },
  emerald: { panel: "bg-gradient-to-br from-emerald-50 to-emerald-100/50 border-emerald-200",
             head:  "text-emerald-900",
             icon:  "text-emerald-600 bg-emerald-100",
             pill:  "bg-emerald-600 text-white",
             divider: "border-emerald-200",
             Icon:  CheckCircle2 },
  slate:   { panel: "bg-gradient-to-br from-slate-50 to-slate-100/50 border-slate-200",
             head:  "text-slate-900",
             icon:  "text-slate-600 bg-slate-100",
             pill:  "bg-slate-600 text-white",
             divider: "border-slate-200",
             Icon:  Info },
};

