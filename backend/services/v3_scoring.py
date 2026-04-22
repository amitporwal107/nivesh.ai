"""V3 Engine Phase 1b: composite scoring layer.

Implements the 5 composite scores from the Excel spec (Quality / Health /
Exit / Add / Portfolio-Fit), plus the Switch formula and Guardrails.

Design principles:
  • Pure functions. No I/O. Inputs are plain dicts from the caller.
  • Weight redistribution: if a component's primitive is missing (None),
    its weight is proportionally redistributed across the remaining
    components so the final score always sums to 100%. `missing_primitives`
    is returned so the UI can badge the confidence.
  • Returns in [0, 100] — the composite score is on the standard 0-100
    scale. Per-component contributions are returned in `components` as
    raw 0-10 normalised scores (matching the Excel "Computation" column).

Excel weight tables (from Quality_Score / Health_Score / etc. sheets):

Quality:  Performance 25 + Risk-Adj 20 + Consistency 20 + Drawdown 15 + Cost 10 + AUM/Age 10
Health:   Manager 25 + AUM-Stab 20 + Turnover 15 + Concentration 15 + Downside 15 + Expense-Trend 10
Exit:     Overlap 25 + Tax 25 + Quality 25 + Cost 15 + Portfolio-Fit 10
Add:      Gap-Fit 30 + Low-Overlap 25 + Quality 20 + Need 15 + Cost 10
Portfolio: Diversification 25 + Overlap 25 + AMC 20 + Cost 15 + Asset-Alloc 15
Switch (formula, not weighted):
          (Quality_new − Quality_old) + Overlap_reduction + Cost_saving − Tax_cost
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Normalisers (each returns a 0-10 score) ─────────────────────────────
def _norm_returns(ret_1y: Optional[float], ret_3y: Optional[float],
                  ret_5y: Optional[float], cat_1y: Optional[float],
                  cat_3y: Optional[float], cat_5y: Optional[float]) -> Optional[float]:
    """Weighted excess return over category — 1Y:3Y:5Y = 20:40:40.

    Each horizon contributes an excess-return score: 5 + excess_pct / 2
    clamped to 0-10 (so +10% over category = 10, -10% = 0).
    """
    parts, weights = [], []
    for w, r, c in ((0.2, ret_1y, cat_1y), (0.4, ret_3y, cat_3y), (0.4, ret_5y, cat_5y)):
        if r is None or c is None:
            continue
        excess = r - c
        s = max(0.0, min(10.0, 5.0 + excess / 2.0))
        parts.append(s * w); weights.append(w)  # noqa: E702
    if not weights:
        return None
    return round(sum(parts) / sum(weights), 2)


def _norm_risk_adjusted(sharpe: Optional[float], sortino: Optional[float]) -> Optional[float]:
    """Sharpe 1.5 → 10, 0.5 → 5, 0 → 0. Equal-weight Sharpe + Sortino when both available."""
    parts = []
    for v in (sharpe, sortino):
        if v is None:
            continue
        s = max(0.0, min(10.0, v * 6.67))  # 1.5 → 10
        parts.append(s)
    if not parts:
        return None
    return round(sum(parts) / len(parts), 2)


def _norm_consistency(consistency_score: Optional[float]) -> Optional[float]:
    """Already 0-10 from nav_analytics."""
    if consistency_score is None:
        return None
    return round(max(0.0, min(10.0, consistency_score)), 2)


def _norm_drawdown(max_drawdown_pct: Optional[float]) -> Optional[float]:
    """Lower drawdown → higher score. 0% → 10, 50%+ → 0 (linear)."""
    if max_drawdown_pct is None:
        return None
    return round(max(0.0, min(10.0, 10.0 - max_drawdown_pct / 5.0)), 2)


def _norm_cost(expense_ratio: Optional[float]) -> Optional[float]:
    """Lower expense → higher score. 0.5% → 10, 2.5% → 0 (linear)."""
    if expense_ratio is None:
        return None
    return round(max(0.0, min(10.0, 10.0 - (expense_ratio - 0.5) * 5.0)), 2)


def _norm_aum_age(aum_cr: Optional[float], age_years: Optional[float]) -> Optional[float]:
    """Larger + older = more mature. AUM ₹5000Cr+ and age 7y+ → 10."""
    parts = []
    if aum_cr is not None:
        parts.append(max(0.0, min(10.0, (aum_cr / 500.0) ** 0.5)))  # ₹5000Cr → 10
    if age_years is not None:
        parts.append(max(0.0, min(10.0, age_years / 0.7)))  # 7y → 10
    if not parts:
        return None
    return round(sum(parts) / len(parts), 2)


def _norm_manager_tenure(tenure_years: Optional[float]) -> Optional[float]:
    """Per Excel: >=5 yrs = high score. Piecewise: 0→0, 3→6, 5→8, 7+→10."""
    if tenure_years is None:
        return None
    if tenure_years >= 7:
        return 10.0
    if tenure_years >= 5:
        return round(8.0 + (tenure_years - 5) / 2 * 2.0, 2)
    if tenure_years >= 3:
        return round(6.0 + (tenure_years - 3) / 2 * 2.0, 2)
    return round(max(0.0, tenure_years * 2.0), 2)


def _norm_aum_trend(score_0_10: Optional[float]) -> Optional[float]:
    if score_0_10 is None:
        return None
    return round(max(0.0, min(10.0, score_0_10)), 2)


def _norm_turnover(ratio: Optional[float]) -> Optional[float]:
    """Per Excel: moderate is best. <10% → stale, 30-100% → moderate peak,
    >200% → churn. Bell-ish curve peaking at 60%."""
    if ratio is None:
        return None
    if ratio <= 60:
        s = (ratio / 60) * 10.0
    else:
        s = max(0.0, 10.0 - (ratio - 60) / 25.0)
    return round(max(0.0, min(10.0, s)), 2)


def _norm_top10(pct: Optional[float]) -> Optional[float]:
    """Inverse concentration. 30% top10 → 10 (well-diversified), 70% → 0."""
    if pct is None:
        return None
    return round(max(0.0, min(10.0, 10.0 - (pct - 30) / 4.0)), 2)


def _norm_downside_capture(dc_pct: Optional[float]) -> Optional[float]:
    """Lower downside-capture is better. 50% → 10, 100% → 5, 150% → 0."""
    if dc_pct is None:
        return None
    return round(max(0.0, min(10.0, 10.0 - (dc_pct - 50) / 10.0)), 2)


def _norm_expense_trend(delta: Optional[float]) -> Optional[float]:
    """Declining expense → 10. Delta < 0 → 10, 0 → 5, +0.5 → 0."""
    if delta is None:
        return None
    return round(max(0.0, min(10.0, 5.0 - delta * 10.0)), 2)


# ── Weighted composite helper ────────────────────────────────────────────
def _weighted_composite(
    components: Dict[str, tuple],  # name → (value_0_10, weight_pct)
) -> Dict[str, Any]:
    """Combine components into a 0-100 score with weight redistribution.

    Returns { score, components, missing_primitives, effective_weights }.
    """
    available = {k: v for k, v in components.items() if v[0] is not None}
    missing = [k for k, v in components.items() if v[0] is None]

    if not available:
        return {"score": None, "components": {k: None for k in components},
                "missing_primitives": missing, "effective_weights": {}}

    total_w = sum(w for _, w in available.values())
    if total_w == 0:
        return {"score": None, "components": {k: None for k in components},
                "missing_primitives": missing, "effective_weights": {}}

    # Renormalise weights to sum to 100
    eff_weights = {k: (w / total_w) * 100 for k, (_, w) in available.items()}
    score_10 = sum(v * eff_weights[k] for k, (v, _) in available.items()) / 100.0
    score_100 = round(score_10 * 10.0, 2)

    comp_out = {k: (None if v[0] is None else round(v[0], 2))
                for k, v in components.items()}
    return {
        "score": score_100,
        "components": comp_out,
        "missing_primitives": missing,
        "effective_weights": {k: round(w, 1) for k, w in eff_weights.items()},
    }


# ── 5 Composite Scores ───────────────────────────────────────────────────
def compute_quality_score(f: Dict[str, Any]) -> Dict[str, Any]:
    """Quality score — category-aware per V3.1 PRD.

    Classifies fund → picks category-specific weight profile → computes composite.
    Components that need primitives the fund doesn't have (e.g., credit_quality
    for equity funds) are marked as None and weights renormalise over what's
    available (graceful degradation).
    """
    # Lazy import to avoid circular on startup
    from services import v3_weights  # noqa: WPS433
    category = v3_weights.classify_fund_category(f)
    weights = v3_weights.get_weights(category, "quality")

    # Fold category-avg aliases so both key variants work
    cat_1y = f.get("cat_avg_1y") if f.get("cat_avg_1y") is not None else f.get("category_avg_1y")
    cat_3y = f.get("cat_avg_3y") if f.get("cat_avg_3y") is not None else f.get("category_avg_3y")
    cat_5y = f.get("cat_avg_5y") if f.get("cat_avg_5y") is not None else f.get("category_avg_5y")

    # Compute every possible component value (None if primitive is missing).
    # This lets any weight profile pick-and-choose.
    comp_values = {
        "performance":          _norm_returns(f.get("ret_1y"), f.get("ret_3y"), f.get("ret_5y"), cat_1y, cat_3y, cat_5y),
        "risk_adjusted":        _norm_risk_adjusted(f.get("sharpe"), f.get("sortino")),
        "consistency":          _norm_consistency(f.get("consistency_score")),
        "drawdown":             _norm_drawdown(f.get("max_drawdown_pct")),
        "cost":                 _norm_cost(f.get("expense_ratio_direct") or f.get("expense_ratio")),
        "aum_age":              _norm_aum_age(f.get("aum_cr"), f.get("fund_age_years")),
        "downside_capture":     _norm_downside_capture(f.get("downside_capture_pct")),
        "allocation_stability": _norm_allocation_stability(f.get("allocation_stability_score")),
        # Debt-specific primitives (populated by VR scraper when available)
        "credit_quality":       _norm_credit_quality(f.get("credit_quality_score")),
        "yield_vs_category":    _norm_yield_vs_cat(f.get("ytm"), f.get("cat_avg_ytm")),
        # Prefer pre-normalised duration_risk_score (0-10 from Moneycontrol
        # investment-style parsing); fall back to raw modified_duration years.
        "duration_risk":        _norm_duration_risk_flex(f.get("duration_risk_score"), f.get("modified_duration")),
    }
    comps = {name: (comp_values.get(name), w) for name, w in weights.items()}
    result = _weighted_composite(comps)
    result["category"] = category
    result["weight_profile"] = weights
    return result


def compute_health_score(f: Dict[str, Any]) -> Dict[str, Any]:
    """Health score — category-aware per V3.1 PRD."""
    from services import v3_weights  # noqa: WPS433
    category = v3_weights.classify_fund_category(f)
    weights = v3_weights.get_weights(category, "health")

    comp_values = {
        "manager_tenure":        _norm_manager_tenure(f.get("manager_tenure_years")),
        "aum_stability":         _norm_aum_trend(f.get("aum_trend_score")),
        "turnover":              _norm_turnover(f.get("turnover_ratio")),
        "concentration":         _norm_top10(f.get("top10_concentration_pct")),
        "downside_protection":   _norm_downside_capture(f.get("downside_capture_pct")),
        "expense_trend":         _norm_expense_trend(f.get("expense_trend_delta")),
        "allocation_consistency": _norm_allocation_stability(f.get("allocation_consistency_score")),
        # Debt-specific primitives
        "credit_concentration":  _norm_credit_concentration(f.get("credit_concentration_pct")),
        "liquidity":             _norm_liquidity(f.get("liquidity_score")),
    }
    comps = {name: (comp_values.get(name), w) for name, w in weights.items()}
    result = _weighted_composite(comps)
    result["category"] = category
    result["weight_profile"] = weights
    return result


# ── New normalisation helpers (debt + hybrid) ───────────────────────────
def _norm_credit_quality(score: Optional[float]) -> Optional[float]:
    """score is 0-10 where 10 = 100% AAA, 0 = below-investment-grade."""
    if score is None:
        return None
    return round(max(0.0, min(10.0, float(score))), 2)


def _norm_yield_vs_cat(ytm: Optional[float], cat_avg_ytm: Optional[float]) -> Optional[float]:
    """Higher YTM vs category → higher score. Each +0.5% premium → +1 point above 5."""
    if ytm is None or cat_avg_ytm is None:
        return None
    delta = ytm - cat_avg_ytm
    return round(max(0.0, min(10.0, 5.0 + delta * 2.0)), 2)


def _norm_duration_risk(mod_dur: Optional[float]) -> Optional[float]:
    """Shorter modified duration = lower interest-rate risk = higher score.
    0y → 10, 3y → 7, 5y → 5, 8y → 2, 10+y → 0."""
    if mod_dur is None:
        return None
    return round(max(0.0, min(10.0, 10.0 - float(mod_dur))), 2)


def _norm_duration_risk_flex(direct_score: Optional[float], mod_dur: Optional[float]) -> Optional[float]:
    """Prefer a pre-normalised 0-10 duration_risk_score (from Moneycontrol
    investment-style parsing: Limited=9, Moderate=6, Extensive=3). Fall back
    to deriving from modified_duration years."""
    if direct_score is not None:
        return round(max(0.0, min(10.0, float(direct_score))), 2)
    return _norm_duration_risk(mod_dur)


def _norm_credit_concentration(top5_pct: Optional[float]) -> Optional[float]:
    """Top 5 issuer concentration. <20% → 10, 50% → 5, 80%+ → 0."""
    if top5_pct is None:
        return None
    return round(max(0.0, min(10.0, 10.0 - (float(top5_pct) - 20) / 6.0)), 2)


def _norm_liquidity(liquidity_score: Optional[float]) -> Optional[float]:
    """0-10 liquidity score (fraction of portfolio in Tier-1 liquid securities)."""
    if liquidity_score is None:
        return None
    return round(max(0.0, min(10.0, float(liquidity_score))), 2)


def _norm_allocation_stability(score: Optional[float]) -> Optional[float]:
    """0-10 score of hybrid-fund equity/debt mix stability over time."""
    if score is None:
        return None
    return round(max(0.0, min(10.0, float(score))), 2)


def compute_exit_score(f: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Exit = Overlap 25 + Tax 25 + Quality-inverse 25 + Cost 15 + Portfolio-Fit 10.

    ctx keys: overlap_pct, tax_liability_rs, tax_benefit_rs, portfolio_fit_score, quality_score.
    """
    quality_0_10 = (ctx.get("quality_score") or 0) / 10.0 if ctx.get("quality_score") else None
    inv_quality = (10.0 - quality_0_10) if quality_0_10 is not None else None
    tax_score = _score_tax_impact(ctx.get("tax_liability_rs"), ctx.get("tax_benefit_rs"))
    overlap = ctx.get("overlap_pct")
    pf_score = (ctx.get("portfolio_fit_score") or 0) / 10.0 if ctx.get("portfolio_fit_score") else None
    comps = {
        "overlap":        (round(min(10.0, (overlap or 0) / 10.0), 2) if overlap is not None else None, 25),
        "tax_impact":     (tax_score, 25),
        "quality_inverse": (round(inv_quality, 2) if inv_quality is not None else None, 25),
        "cost":           (_norm_cost(f.get("expense_ratio_regular") or f.get("expense_ratio")), 15),
        "portfolio_fit":  (round(10.0 - pf_score, 2) if pf_score is not None else None, 10),
    }
    return _weighted_composite(comps)


def _score_tax_impact(liability: Optional[float], benefit: Optional[float]) -> Optional[float]:
    """Higher tax relative to benefit → lower exit desirability (score decreases)."""
    if liability is None:
        return None
    if not benefit or benefit <= 0:
        # Tax exists but no clear benefit → exit is unattractive
        return round(max(0.0, 5.0 - liability / 20000.0), 2)
    ratio = liability / benefit
    # ratio < 0.3 = tax tiny vs benefit → 9-10; ratio > 1.5 → 0-2
    if ratio <= 0.3:
        return 10.0
    if ratio >= 2.0:
        return 0.0
    return round(10.0 - (ratio - 0.3) / 1.7 * 10.0, 2)


def compute_add_score(f: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Add = Gap-Fit 30 + Low-Overlap 25 + Quality 20 + Need 15 + Cost 10.

    ctx keys: gap_fit_0_10, avg_overlap_pct_with_portfolio, need_score_0_10.
    """
    quality_0_10 = (ctx.get("quality_score") or 0) / 10.0 if ctx.get("quality_score") else None
    overlap_with_portfolio = ctx.get("avg_overlap_pct_with_portfolio")
    low_overlap = (10.0 - min(10.0, (overlap_with_portfolio or 0) / 10.0)) if overlap_with_portfolio is not None else None
    comps = {
        "gap_fit":    (ctx.get("gap_fit_0_10"), 30),
        "low_overlap": (round(low_overlap, 2) if low_overlap is not None else None, 25),
        "quality":    (round(quality_0_10, 2) if quality_0_10 is not None else None, 20),
        "need":       (ctx.get("need_score_0_10"), 15),
        "cost":       (_norm_cost(f.get("expense_ratio_direct") or f.get("expense_ratio")), 10),
    }
    return _weighted_composite(comps)


def compute_portfolio_fit_score(p: Dict[str, Any]) -> Dict[str, Any]:
    """Portfolio = Diversification 25 + Overlap 25 + AMC-Conc 20 + Cost 15 + Asset-Alloc 15.

    Input `p` is a portfolio-level dict:
        diversification_0_10, avg_overlap_pct, top_amc_pct,
        avg_expense_ratio, asset_alloc_fit_0_10
    """
    overlap = p.get("avg_overlap_pct")
    overlap_inv = (10.0 - min(10.0, (overlap or 0) / 10.0)) if overlap is not None else None
    amc = p.get("top_amc_pct")
    # <20% top AMC → 10; 40%+ → 0
    amc_score = (10.0 - max(0.0, (amc - 20) / 2.0)) if amc is not None else None
    comps = {
        "diversification":   (p.get("diversification_0_10"), 25),
        "overlap":           (round(overlap_inv, 2) if overlap_inv is not None else None, 25),
        "amc_concentration": (round(amc_score, 2) if amc_score is not None else None, 20),
        "cost":              (_norm_cost(p.get("avg_expense_ratio")), 15),
        "asset_allocation":  (p.get("asset_alloc_fit_0_10"), 15),
    }
    return _weighted_composite(comps)


# ── Switch formula (Excel Switch_Score) ─────────────────────────────────
def compute_switch_score(
    quality_new: Optional[float], quality_old: Optional[float],
    overlap_reduction_pct: Optional[float], cost_saving_rs_per_yr: Optional[float],
    tax_cost_rs: Optional[float],
) -> Dict[str, Any]:
    """(Quality_new − Quality_old) + Overlap_reduction + Cost_saving − Tax_cost.

    Quality is on the 0-100 scale, so we scale it down to match the ₹ terms.
    Cost-saving and tax are normalised per ₹10K. Overlap reduction is in pp.
    Returns {score, recommended, components}.
    """
    parts = {}
    total = 0.0
    if quality_new is not None and quality_old is not None:
        parts["quality_improvement"] = round((quality_new - quality_old) / 10.0, 2)
        total += parts["quality_improvement"]
    if overlap_reduction_pct is not None:
        parts["overlap_reduction"] = round(overlap_reduction_pct / 10.0, 2)
        total += parts["overlap_reduction"]
    if cost_saving_rs_per_yr is not None:
        parts["cost_saving"] = round(cost_saving_rs_per_yr / 10000.0, 2)
        total += parts["cost_saving"]
    if tax_cost_rs is not None:
        parts["tax_cost"] = round(-tax_cost_rs / 10000.0, 2)
        total += parts["tax_cost"]
    return {
        "score": round(total, 2),
        "recommended": total >= 2.0,
        "components": parts,
    }


# ── Guardrails (Excel sheet Guardrails) ─────────────────────────────────
@dataclass
class GuardrailResult:
    blocked: bool = False
    reasons: List[str] = field(default_factory=list)
    confidence_penalty: float = 0.0


def check_guardrails(
    *, quality_score: Optional[float], health_score: Optional[float],
    overlap_pct: Optional[float],
    tax_liability_rs: Optional[float], tax_benefit_rs: Optional[float],
    holding_age_months: Optional[float], confidence_score: Optional[float],
) -> GuardrailResult:
    """Apply the 4 Excel guardrails.

    Rule 1: High Quality Protection — Quality>=75 AND Health>=70, block exit
            UNLESS overlap > 80% (which overrides).
    Rule 2: Tax Protection — tax > benefit, block exit.
    Rule 3: Recent Investment — holding < 6 months, block exit.
    Rule 4: Low Confidence — confidence < 50, reduce actions (flag, not block).
    """
    r = GuardrailResult()
    # Rule 1
    if (quality_score or 0) >= 75 and (health_score or 0) >= 70:
        if (overlap_pct or 0) <= 80:
            r.blocked = True
            r.reasons.append("high_quality_protection")
    # Rule 2
    if tax_liability_rs is not None and tax_benefit_rs is not None and tax_liability_rs > tax_benefit_rs:
        r.blocked = True
        r.reasons.append("tax_exceeds_benefit")
    # Rule 3
    if holding_age_months is not None and holding_age_months < 6:
        r.blocked = True
        r.reasons.append("recent_investment_lockout")
    # Rule 4 (not blocking, just penalises)
    if confidence_score is not None and confidence_score < 50:
        r.confidence_penalty = (50 - confidence_score) / 10.0
        r.reasons.append("low_confidence")
    return r


ENGINE_VERSION = "v3.0-phase1"
