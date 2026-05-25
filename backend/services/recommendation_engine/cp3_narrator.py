"""
CP-3 Narrator — structures a single action into the 5-question format
the Copilot prompt requires (rule book §10.13 CP-3).

Produces a compact text block that _active_plan_context() injects
per-action into the LLM context. The LLM uses CP3-* tags as ground-truth
when the user asks "explain this recommendation".

Five questions (§10.13):
  1. WHY is this recommended?
  2. WHAT IMPROVES?
  3. WHAT ARE THE TRADE-OFFS?
  4. HOW CONFIDENT IS THE SYSTEM?
  5. WHAT IS THE TAX IMPACT?
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Human-readable label for each machine reason code.
_CODE_LABELS: Dict[str, str] = {
    "OVERLAP_CONSOLIDATION":       "two funds hold >70% of the same stocks",
    "OVERLAP_MODERATE":            "two funds share 50–70% of their stock holdings",
    "CROSS_CATEGORY_REPLACEMENT":  "adding a complementary category to fill the gap",
    "AMC_CONCENTRATION":           "over 40% of portfolio with a single AMC",
    "CATEGORY_CONCENTRATION":      "over 35% in one fund category",
    "UNDERPERFORMER":              "fund consistently trails its benchmark",
    "EXIT_CANDIDATE":              "scoring engine flagged this as a weak holding",
    "ALLOCATION_GAP":              "target allocation not met — missing asset class",
    "REGULAR_PLAN":                "regular plan costs ~1% more than the direct equivalent",
    "DIRECT_SWITCH":               "switching to direct plan to save on expense ratio",
    "GOAL_ALIGNMENT":              "portfolio allocation misaligned with goal horizon",
    "GA2_SMALLCAP_SHORT_HORIZON":  "small-cap exposure too high for a short investment horizon",
    "GA3_RETIREMENT_GLIDE_PATH":   "retirement approaching — reduce equity to protect corpus",
    "GA4_SHORTFALL":               "goal is critical/at-risk — needs immediate rebalance",
    "EQUITY_CEILING_BREACH":       "equity % exceeds the safe ceiling for this goal horizon",
    "RA1_SMALLCAP_CAP":            "small-cap exceeds risk-profile limit",
    "RA1_SECTORAL_CAP":            "sector fund exceeds risk-profile limit",
    "RA2_HIGH_VOLATILITY":         "portfolio volatility above risk-profile ceiling",
    "RA3_HIGH_DRAWDOWN":           "portfolio drawdown risk exceeds allowed threshold",
    "PA1_FUND_COUNT":              "too many funds — redundancy dilutes focus",
    "PA2_EFFECTIVE_HOLDINGS":      "portfolio has low effective stock count — poorly diversified",
    "DV1_COVERAGE_LOW":            "price data coverage below 90% — some valuations may be stale",
    "CR1_BEHAVIOURAL_REDUNDANCY":  "two funds behave nearly identically (correlation > 0.85)",
    "STOCK_EXIT_HIGH":             "exit score ≥ 75 — fundamental/valuation flags triggered",
    "STOCK_TRIM_HIGH":             "exit score 60–75 — consider reducing position",
    "STOCK_QUALITY_LOW":           "quality score < 45 — fundamentals need review",
    "INTERNATIONAL_EXPOSURE":      "international allocation below target — diversification opportunity",
    "PORTFOLIO_HEALTHY":           "portfolio scores ≥ 75 — no action needed right now",
}

_CONFIDENCE_TEXT: Dict[str, str] = {
    "HIGH":   (
        "Multiple independent signals align and underlying data quality is good. "
        "Strong grounds to act."
    ),
    "MEDIUM": (
        "Signal is valid but one or more inputs carry uncertainty "
        "(e.g. stale NAV, partial fundamentals, or borderline threshold). "
        "Review before acting."
    ),
    "LOW": (
        "Treat this as a flag to investigate — do NOT act solely on this signal. "
        "Confidence is below the threshold for a firm recommendation."
    ),
}

# Qualitative fallbacks when simulation block is absent.
_IMPROVE_FALLBACK: Dict[str, str] = {
    "EXIT":   "Reduces concentration, removes an underperforming holding, or resolves a rule violation.",
    "ADD":    "Fills a target allocation gap; improves diversification.",
    "TRIM":   "Rebalances allocation closer to target; lowers excess risk.",
    "SWITCH": "Maintains exposure while improving fund quality or reducing cost.",
    "HOLD":   "No action — portfolio quality is adequate at this level.",
}


def _decode_codes(codes: List[str]) -> str:
    if not codes:
        return ""
    return "; ".join(_CODE_LABELS.get(c, c) for c in codes)


def narrate_action(
    action: Dict[str, Any],
    simulation: Optional[Dict[str, Any]] = None,
) -> str:
    """Return a CP3-* tagged text block for a single action dict.

    The block is injected verbatim into the LLM's portfolio context.
    Each tag maps to one of the five CP-3 questions.
    """
    action_type  = (action.get("type") or "ACTION").upper()
    reason_text  = (action.get("reason_text") or "").strip()
    reason_codes: List[str] = action.get("reason_codes") or []
    confidence   = (action.get("confidence") or "MEDIUM").upper()
    ti           = action.get("tax_impact") or {}
    amt          = float(
        action.get("amount") or action.get("exit_amount_rs") or action.get("amount_rs") or 0
    )

    # ── Q1: WHY ──────────────────────────────────────────────────────────────
    code_labels = _decode_codes(reason_codes)
    if reason_text:
        why = reason_text
        # Append code labels if they add information not already in reason_text
        if code_labels and not any(c.lower() in reason_text.lower() for c in reason_codes[:1]):
            why += f" [Signals: {code_labels}]"
    else:
        why = f"Signals: {code_labels}" if code_labels else "No reason text recorded."

    # ── Q2: WHAT IMPROVES ────────────────────────────────────────────────────
    improvements: List[str] = []
    if simulation:
        delta = simulation.get("delta") or {}
        if delta.get("overlap_reduction_pp"):
            improvements.append(f"overlap ↓ {delta['overlap_reduction_pp']:.0f}pp")
        if delta.get("volatility_reduction_pp"):
            improvements.append(f"volatility ↓ {delta['volatility_reduction_pp']:.1f}pp")
        if delta.get("weighted_er_reduction_bps"):
            improvements.append(f"expense ratio ↓ {delta['weighted_er_reduction_bps']:.0f}bps/yr")
        if delta.get("projected_10y_gain_rs"):
            improvements.append(f"projected 10Y wealth ↑ ₹{delta['projected_10y_gain_rs']:,.0f}")
        if delta.get("goal_probability_gain_pct"):
            improvements.append(f"goal probability ↑ {delta['goal_probability_gain_pct']:.0f}pp")
        if delta.get("mf_count_delta") and int(delta["mf_count_delta"]) < 0:
            improvements.append(f"fund count ↓ {abs(int(delta['mf_count_delta']))}")

    what_improves = (
        ", ".join(improvements)
        if improvements
        else _IMPROVE_FALLBACK.get(action_type, "Improves portfolio quality.")
    )

    # ── Q3: TRADE-OFFS ───────────────────────────────────────────────────────
    tradeoffs: List[str] = []
    tax_liability = float(ti.get("tax_liability") or 0)

    if ti.get("tax_impact_pending"):
        tradeoffs.append("tax impact unknown — purchase records / cost basis missing")
    elif tax_liability > 0:
        tradeoffs.append(
            f"₹{tax_liability:,.0f} tax on exit (regime: {ti.get('tax_regime', 'equity')})"
        )

    if action_type in ("EXIT", "SWITCH"):
        tradeoffs.append("settlement takes T+1 to T+3 working days")
    if action_type == "ADD":
        tradeoffs.append("requires fresh capital; verify liquidity before investing")
    if action_type == "TRIM":
        tradeoffs.append("confirm fund allows partial redemption without exit load")
    if any(c in reason_codes for c in ("GOAL_ALIGNMENT", "GA4_SHORTFALL")):
        tradeoffs.append("rebalancing in a down market may crystallise unrealised losses")

    if not tradeoffs:
        tradeoffs = ["no material trade-offs identified"]

    # ── Q4: CONFIDENCE ───────────────────────────────────────────────────────
    conf_text = _CONFIDENCE_TEXT.get(confidence, f"Confidence level: {confidence}.")

    # ── Q5: TAX IMPACT ───────────────────────────────────────────────────────
    if ti.get("tax_impact_pending"):
        tax_text = (
            "Cannot compute — buy date / cost basis missing. "
            "Obtain purchase records before acting to avoid a surprise tax bill."
        )
    elif tax_liability > 0:
        ltcg = float(ti.get("ltcg_tax") or ti.get("equity_ltcg") or 0)
        stcg = float(ti.get("stcg_tax") or ti.get("equity_stcg") or 0)
        tax_text = (
            f"Est. ₹{tax_liability:,.0f} total — "
            f"LTCG ₹{ltcg:,.0f} @ 12.5% + STCG ₹{stcg:,.0f} @ 20% "
            f"on ₹{amt:,.0f} exit value "
            f"(regime: {ti.get('tax_regime', 'equity')})"
        )
    elif action_type == "ADD":
        tax_text = "No immediate tax — this is an investment action."
    else:
        tax_text = "No tax liability estimated (no gains, or within the ₹1.25L LTCG exempt threshold)."

    return (
        f"    CP3-WHY: {why}\n"
        f"    CP3-IMPROVES: {what_improves}\n"
        f"    CP3-TRADEOFFS: {'; '.join(tradeoffs)}\n"
        f"    CP3-CONFIDENCE: {confidence} — {conf_text}\n"
        f"    CP3-TAX: {tax_text}"
    )
