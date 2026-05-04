import React from "react";
import { CheckCircle2, AlertTriangle, XCircle, Hourglass, Info } from "lucide-react";

/**
 * Decision Verdict — the "hero" recommendation banner that sits at
 * the top of the holdings expanded row.
 *
 * Implements the Cost-vs-Benefit override layer the user asked for:
 *
 *   IF cost > expected_alpha_3y  → DO NOT ADD / DO NOT SWITCH
 *   IF cost ≈ expected_alpha     → ADD LATER (wait for better entry)
 *   IF cost < expected_alpha     → ADD / SWITCH (worth it)
 *   IF action="HOLD"             → HOLD (no change required)
 *   IF action="EXIT" + harvestable loss → EXIT (tax-loss harvest)
 *
 * Visual hierarchy: this is the LARGEST element in the expanded row.
 * Everything else (score breakdown, cost panel, returns) is supporting
 * detail that backs the decision.
 *
 * Props:
 *   action       — engine recommendation: "ADD" | "SWITCH" | "EXIT" | "HOLD" | "REVIEW"
 *   scores       — { quality, health, exit, add } (0-100)
 *   switchCost   — % cost of executing the action (post-tax/exit/slippage)
 *   alphaAnnual  — expected forward alpha %/year (CAGR vs benchmark, or
 *                  fallback to historical alpha when forward isn't computed).
 *                  Used for SWITCH decisions only — ADD reasons about gap+rank.
 *   benchmarkLabel — e.g. "Nifty 500" — what alpha is computed against
 *   benchmarkReturn — benchmark CAGR % over the same window
 *   fundReturn      — fund CAGR % over the same window
 *   allocationCurrent — current % of portfolio (optional)
 *   allocationTarget  — target % per Decision Engine (optional)
 *   categoryRank      — fund's rank within its sub_category (1 = best)
 *   categoryRankTotal — total funds in that sub_category
 *   categoryLabel     — sub_category display name (e.g. "Flexi Cap")
 *   netBenefitRs      — ₹ value of the net (alpha gain − cost) over hold period
 */
export default function DecisionVerdict({
  action,
  scores,
  switchCost,
  alphaAnnual,
  benchmarkLabel,
  benchmarkReturn,
  fundReturn,
  allocationCurrent,
  allocationTarget,
  categoryRank,
  categoryRankTotal,
  categoryLabel,
  netBenefitRs,
}) {
  const cost = Number(switchCost ?? 0);
  const alpha = Number(alphaAnnual ?? 0);
  const q = scores?.quality;
  const h = scores?.health;

  // Cost-vs-benefit override (SWITCH only). We compare cost (one-off) to
  // 3y of alpha (cumulative benefit) — a 1.5% switch cost recouped in 18
  // months by 1%/yr alpha is a fine trade; same cost vs 0.3%/yr is wasteful.
  // Default holding window = 3y (industry rule of thumb).
  const cumulativeAlpha3y = alpha * 3;
  const ratio = alpha > 0 ? cost / Math.max(cumulativeAlpha3y, 0.01) : (cost > 0 ? Infinity : 0);

  // Allocation gap (used as the primary ADD justification).
  const gapPP = (allocationCurrent != null && allocationTarget != null)
    ? Number(allocationTarget) - Number(allocationCurrent)
    : null;
  const isUnderallocated = gapPP != null && gapPP >= 0.5;

  // Category rank → percentile band ("Top X%").
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

  // Compact "Strong fund" line — only show the scores we actually have.
  const strongScoreLine = [
    q != null ? `Q=${Math.round(q)}` : null,
    h != null ? `H=${Math.round(h)}` : null,
  ].filter(Boolean).join(", ");

  let verdict, headline, reasons, bodyTone;

  if (action === "EXIT") {
    verdict = "EXIT";
    headline = "Recommendation: Exit this fund";
    reasons = ["Engine flagged this for exit (overlap, AMC concentration, or quality drop)"];
    bodyTone = "rose";
  } else if (action === "HOLD" || action === "REVIEW") {
    verdict = "HOLD";
    headline = "Recommendation: Hold for now";
    reasons = ["No action signal at current scores"];
    bodyTone = "slate";
  } else if (action === "ADD") {
    // ADD has no switch cost — alpha vs benchmark is the wrong gate.
    // Drive the verdict from allocation gap + category rank instead.
    if (isUnderallocated && (rankBand == null || isTopHalf)) {
      verdict = "ADD";
      headline = "Recommendation: Add to this fund";
      reasons = [
        categoryLabel
          ? `${categoryLabel} allocation ${allocationCurrent.toFixed(1)}% vs target ${allocationTarget.toFixed(1)}% — under by ${gapPP.toFixed(1)}pp`
          : `Allocation ${allocationCurrent.toFixed(1)}% vs target ${allocationTarget.toFixed(1)}% — under by ${gapPP.toFixed(1)}pp`,
      ];
      if (rankBand) {
        reasons.push(`${rankBand} in category (#${categoryRank} of ${categoryRankTotal})`);
      }
      if (strongScoreLine) {
        reasons.push(`Strong fund (${strongScoreLine})`);
      }
      bodyTone = "emerald";
    } else if (gapPP != null && gapPP < -0.5) {
      // Already over target — direct the user away from adding more.
      verdict = "HOLD";
      headline = "Recommendation: Hold — already at target";
      reasons = [
        categoryLabel
          ? `${categoryLabel} allocation ${allocationCurrent.toFixed(1)}% vs target ${allocationTarget.toFixed(1)}% — over by ${(-gapPP).toFixed(1)}pp`
          : `Allocation ${allocationCurrent.toFixed(1)}% vs target ${allocationTarget.toFixed(1)}% — over by ${(-gapPP).toFixed(1)}pp`,
        "Direct fresh capital to under-allocated buckets first",
      ];
      bodyTone = "slate";
    } else if (rankPct != null && !isTopHalf) {
      // Gap unclear or at-target, and this fund isn't a category leader.
      verdict = "REVIEW";
      headline = "Recommendation: Review before adding";
      reasons = [
        `${rankBand} in category (#${categoryRank} of ${categoryRankTotal}) — better-ranked alternatives exist`,
      ];
      if (strongScoreLine) reasons.push(`Fund scores: ${strongScoreLine}`);
      bodyTone = "amber";
    } else {
      // No gap data and no rank data — defer to score-only positive frame.
      verdict = "ADD";
      headline = "Recommendation: Add to this fund";
      reasons = strongScoreLine
        ? [`Strong fund (${strongScoreLine})`, "Allocation context unavailable — consider portfolio fit"]
        : ["Score signal supports adding — confirm against your target allocation"];
      bodyTone = "emerald";
    }
  } else if (action === "SWITCH" && cost > 0 && alpha === 0) {
    verdict = "DO_NOT_ACT";
    headline = "Recommendation: Do NOT switch";
    reasons = [
      `Switch cost is ${cost.toFixed(2)}%`,
      "Expected alpha vs benchmark is 0%/yr — no upside to justify the cost",
      "Cost > Benefit",
    ];
    bodyTone = "rose";
  } else if (action === "SWITCH" && cost > 0 && ratio > 1.0) {
    // Cost greater than 3y cumulative alpha → not worth it
    verdict = "DO_NOT_ACT";
    headline = "Recommendation: Do NOT switch";
    reasons = [
      `Switch cost ${cost.toFixed(2)}% vs 3y expected alpha ${cumulativeAlpha3y.toFixed(2)}%`,
      "Cost > Benefit even over a 3-year hold",
    ];
    bodyTone = "rose";
  } else if (action === "SWITCH" && cost > 0 && ratio > 0.5) {
    verdict = "WAIT";
    headline = "Recommendation: Switch later";
    reasons = [
      `Switch cost ${cost.toFixed(2)}% takes ${Math.round(cost / Math.max(alpha, 0.01) * 12)} months to recover`,
      "Wait for a better entry (lower cost or higher expected alpha)",
    ];
    bodyTone = "amber";
  } else if (action === "SWITCH") {
    verdict = "SWITCH";
    headline = "Recommendation: Switch this fund";
    const benefitYrs = alpha > 0 ? `+${alpha.toFixed(2)}%/yr expected alpha` : "favourable score with low cost";
    reasons = [
      cost > 0 ? `Switch cost ${cost.toFixed(2)}% is well below expected benefit` : "No meaningful cost barrier",
      benefitYrs,
    ];
    bodyTone = "emerald";
  } else {
    verdict = "REVIEW";
    headline = "Recommendation: Review with advisor";
    reasons = ["Score signal exists but cost-benefit isn't clear-cut"];
    bodyTone = "slate";
  }

  // Tone presets
  const TONES = {
    rose:    { panel: "bg-gradient-to-br from-rose-50 to-rose-100/50 border-rose-200",
               head:  "text-rose-900",
               icon:  "text-rose-600 bg-rose-100",
               Icon:  XCircle,
               pill:  "bg-rose-600 text-white" },
    amber:   { panel: "bg-gradient-to-br from-amber-50 to-amber-100/50 border-amber-200",
               head:  "text-amber-900",
               icon:  "text-amber-600 bg-amber-100",
               Icon:  Hourglass,
               pill:  "bg-amber-500 text-white" },
    emerald: { panel: "bg-gradient-to-br from-emerald-50 to-emerald-100/50 border-emerald-200",
               head:  "text-emerald-900",
               icon:  "text-emerald-600 bg-emerald-100",
               Icon:  CheckCircle2,
               pill:  "bg-emerald-600 text-white" },
    slate:   { panel: "bg-gradient-to-br from-slate-50 to-slate-100/50 border-slate-200",
               head:  "text-slate-900",
               icon:  "text-slate-600 bg-slate-100",
               Icon:  Info,
               pill:  "bg-slate-600 text-white" },
  };
  const t = TONES[bodyTone];
  const Icon = t.Icon;

  // Allocation context (Critique #3). Skipped for ADD — that branch
  // already places the allocation gap in its primary reason list, and
  // we don't want a second copy as a footnote.
  const allocationLine = (() => {
    if (action === "ADD") return null;
    if (allocationCurrent == null || allocationTarget == null) return null;
    const gap = allocationTarget - allocationCurrent;
    if (Math.abs(gap) < 0.5) return `Currently at target allocation (${allocationCurrent.toFixed(1)}%)`;
    if (gap > 0) return `Currently ${allocationCurrent.toFixed(1)}% — add to reach target ${allocationTarget.toFixed(1)}%`;
    return `Currently ${allocationCurrent.toFixed(1)}% — already above target ${allocationTarget.toFixed(1)}%`;
  })();

  // Benchmark context (Critique #6)
  const benchmarkLine = (() => {
    if (fundReturn == null || benchmarkReturn == null || !benchmarkLabel) return null;
    const diff = fundReturn - benchmarkReturn;
    const sign = diff >= 0 ? "+" : "";
    return `Fund ${fundReturn.toFixed(2)}% vs ${benchmarkLabel} ${benchmarkReturn.toFixed(2)}% — ${diff >= 0 ? "outperformed" : "underperformed"} by ${sign}${diff.toFixed(2)}pp`;
  })();

  return (
    <div
      className={`rounded-xl border-2 ${t.panel} px-5 py-4 mb-4`}
      data-testid="decision-verdict"
    >
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-lg ${t.icon} flex items-center justify-center flex-shrink-0`}>
          <Icon className="w-5 h-5" strokeWidth={2} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${t.pill}`} data-testid="verdict-badge">
              {verdict.replace(/_/g, " ")}
            </span>
            {benchmarkLabel && (
              <span className="text-[10px] text-slate-500">vs {benchmarkLabel}</span>
            )}
          </div>
          <h3 className={`text-base font-bold mt-1 ${t.head}`} data-testid="verdict-headline">
            {headline}
          </h3>
          <ul className="mt-2 space-y-1">
            {reasons.map((r, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[12.5px] text-slate-700">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-slate-400 flex-shrink-0" />
                <span>{r}</span>
              </li>
            ))}
            {allocationLine && (
              <li className="flex items-start gap-1.5 text-[12.5px] text-slate-700">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-slate-400 flex-shrink-0" />
                <span><strong>Allocation:</strong> {allocationLine}</span>
              </li>
            )}
            {benchmarkLine && (
              <li className="flex items-start gap-1.5 text-[12.5px] text-slate-700">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-slate-400 flex-shrink-0" />
                <span><strong>Benchmark:</strong> {benchmarkLine}</span>
              </li>
            )}
            {netBenefitRs != null && Number(netBenefitRs) !== 0 && (
              <li className="flex items-start gap-1.5 text-[12.5px] text-slate-700">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-slate-400 flex-shrink-0" />
                <span>
                  <strong>Net impact:</strong>{" "}
                  <span className={Number(netBenefitRs) >= 0 ? "text-emerald-700" : "text-rose-700"}>
                    {Number(netBenefitRs) >= 0 ? "+" : ""}₹{Number(netBenefitRs).toLocaleString("en-IN")}
                  </span>{" "}
                  over a 3-year hold
                </span>
              </li>
            )}
          </ul>
        </div>
      </div>
    </div>
  );
}
