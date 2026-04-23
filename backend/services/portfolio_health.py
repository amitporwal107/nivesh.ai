"""Portfolio Health & Risk Scoring Engine.

Implements the Nivesh production-grade Health model:

    Health = 0.30·D + 0.25·R + 0.20·C + 0.25·P

Where each sub-score is 0-100 (higher = better):

    D (Diversification)  = 0.5·D_concentration + 0.3·D_allocation + 0.2·D_overlap
    R (Risk)             = 100 - (0.6·VolScore + 0.4·DrawdownScore)
    C (Cost)             = 0.7·ExpenseScore + 0.3·TaxEfficiencyScore
    P (Performance)      = 0.5·SharpeScore + 0.3·AlphaScore + 0.2·ConsistencyScore

Risk Drivers (the "why is this high?" feature) — each Impact_i = Weight_i × Deviation_i,
so we can show users exactly what's pulling their score down.

Inputs: a stock-level look-through of the portfolio (output of
`portfolio_intelligence.compute_portfolio_intelligence()`) + asset-class
weights + MF primitives. Pure-Python; callers feed data, no DB access here.

NOTE: When detailed stock primitives (beta, vol, sector) are missing we fall
back to market-cap-based heuristics (`stock_primitives_fallback`), and mark
the relevant sub-scores as `low_confidence=True` so the UI can show a
'heuristic' badge.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Calibration constants ──────────────────────────────────────────────
RISK_BANDS = {   # PRD §Step 3: India-context bands
    "vol_low_pct":    8.0,
    "vol_high_pct":   30.0,
    "dd_low_pct":     5.0,
    "dd_high_pct":    50.0,
}

IDEAL_ALLOCATIONS = {   # risk-profile + horizon driven
    "conservative": {"equity": 30, "debt": 60, "hybrid": 10},
    "moderate":     {"equity": 60, "debt": 30, "hybrid": 10},
    "aggressive":   {"equity": 80, "debt": 10, "hybrid": 10},
}
# If horizon < 5y, cap equity at 40% (same guardrail as goal_engine)
SHORT_HORIZON_CAP_EQUITY = 40.0

# Effective-N target for stock diversification
IDEAL_EFFECTIVE_N = 40

EXPENSE_SCORE_BANDS = {
    "good": 0.50,    # ≤ 0.5% expense ratio → 100
    "poor": 2.0,     # ≥ 2.0% expense ratio → 0
}

TAX_DRAG_BANDS = {
    "good": 0.5,     # ≤ 0.5% effective tax drag → 100
    "poor": 4.0,
}

CONCENTRATION_FACTOR = 1.0
OVERLAP_FACTOR = 1.0


# ── Dataclasses ────────────────────────────────────────────────────────
@dataclass
class ComponentScore:
    name: str
    score: float                               # 0-100
    weight: float                              # contribution weight inside parent
    sub_scores: Dict[str, float] = field(default_factory=dict)
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    low_confidence: bool = False
    note: Optional[str] = None


@dataclass
class HealthResult:
    health_score: float
    components: Dict[str, ComponentScore]
    risk_drivers: List[Dict[str, Any]]         # headline "why is this high?" list
    low_confidence: bool                       # true if any sub was heuristic
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "health_score": self.health_score,
            "low_confidence": self.low_confidence,
            "summary": self.summary,
            "components": {
                k: {
                    "name": c.name, "score": c.score, "weight": c.weight,
                    "sub_scores": c.sub_scores, "drivers": c.drivers,
                    "low_confidence": c.low_confidence, "note": c.note,
                } for k, c in self.components.items()
            },
            "risk_drivers": self.risk_drivers,
        }


# ── Small helpers ──────────────────────────────────────────────────────
def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _linear_band(value: float, low_band: float, high_band: float,
                 *, good_is_high: bool = True) -> float:
    """Map `value` linearly into 0-100 given a `low_band`→100 and `high_band`→0
    (if good_is_high=False: low_band→0, high_band→100)."""
    if value is None:
        return 50.0
    if good_is_high:
        if value <= low_band:  return 100.0
        if value >= high_band: return 0.0
        pct = (value - low_band) / (high_band - low_band)
        return _clamp(100.0 - pct * 100.0)
    else:
        if value <= low_band:  return 0.0
        if value >= high_band: return 100.0
        return _clamp(((value - low_band) / (high_band - low_band)) * 100.0)


# ── 1. Diversification (concentration + allocation + overlap) ──────────
def _hhi(weights: List[float]) -> float:
    """HHI across normalised weights (sum should be ~1.0). 0 → perfectly
    diversified, 1 → single-stock. Safe against empty/zero inputs."""
    total = sum(weights) or 0.0
    if total <= 0:
        return 1.0
    return sum((w / total) ** 2 for w in weights)


def _diversification_concentration(stock_level_weights: List[float]) -> Dict[str, float]:
    """PRD: D_concentration = (EffectiveN / IdealN) × 100, clipped to 0-100."""
    if not stock_level_weights:
        return {"score": 0.0, "effective_n": 0.0, "hhi": 1.0}
    hhi = _hhi(stock_level_weights)
    effective_n = 1.0 / hhi if hhi > 0 else 0.0
    score = _clamp((effective_n / IDEAL_EFFECTIVE_N) * 100.0)
    return {"score": round(score, 2), "effective_n": round(effective_n, 2), "hhi": round(hhi, 4)}


def _diversification_allocation(
    actual: Dict[str, float], ideal: Dict[str, float],
) -> Dict[str, Any]:
    """Score = 100 − sum of absolute deviations; 0 deviation → 100."""
    all_keys = set(actual) | set(ideal)
    deviation = sum(abs(actual.get(k, 0.0) - ideal.get(k, 0.0)) for k in all_keys)
    # Each percentage-point away counts — 100% maxes at 50 (half gap in one,
    # half in the other). Scale factor makes "20pp total drift" → score 60.
    score = _clamp(100.0 - deviation * 2.0)
    return {
        "score": round(score, 2),
        "deviation_pp": round(deviation, 2),
        "actual": {k: round(actual.get(k, 0.0), 2) for k in all_keys},
        "ideal": ideal,
    }


def _diversification_overlap(total_overlap_pct: Optional[float]) -> Dict[str, Any]:
    """total_overlap_pct — 0 = no duplicate exposure, 100 = perfectly duplicated.
    Score inverts it: 100 - overlap."""
    ov = max(0.0, min(100.0, float(total_overlap_pct or 0.0)))
    return {"score": round(100.0 - ov, 2), "overlap_pct": round(ov, 2)}


def compute_diversification(
    *,
    stock_weights: List[float],
    asset_allocation_actual: Dict[str, float],
    asset_allocation_ideal: Dict[str, float],
    portfolio_overlap_pct: Optional[float],
) -> ComponentScore:
    d_conc = _diversification_concentration(stock_weights)
    d_alloc = _diversification_allocation(asset_allocation_actual, asset_allocation_ideal)
    d_over = _diversification_overlap(portfolio_overlap_pct)
    score = (0.5 * d_conc["score"] + 0.3 * d_alloc["score"] + 0.2 * d_over["score"])
    drivers: List[Dict[str, Any]] = []
    if d_conc["effective_n"] < 15:
        drivers.append({
            "label": "Too few effective stocks",
            "detail": f"Only {d_conc['effective_n']:.1f} distinct names (target ≥ {IDEAL_EFFECTIVE_N})",
            "impact_points": round((1 - d_conc["score"] / 100) * 50, 1),
        })
    if d_alloc["deviation_pp"] > 20:
        drivers.append({
            "label": "Asset allocation drifted from target",
            "detail": f"{d_alloc['deviation_pp']:.0f}pp off target profile",
            "impact_points": round((1 - d_alloc["score"] / 100) * 30, 1),
        })
    if d_over["overlap_pct"] > 30:
        drivers.append({
            "label": "Overlap between MF & direct equity",
            "detail": f"{d_over['overlap_pct']:.0f}% duplicate exposure",
            "impact_points": round((d_over["overlap_pct"] / 100) * 20, 1),
        })
    return ComponentScore(
        name="Diversification", score=round(_clamp(score), 2), weight=0.30,
        sub_scores={
            "concentration": d_conc["score"], "allocation": d_alloc["score"], "overlap": d_over["score"],
            "effective_n": d_conc["effective_n"], "hhi": d_conc["hhi"],
            "allocation_deviation_pp": d_alloc["deviation_pp"],
            "overlap_pct": d_over["overlap_pct"],
        },
        drivers=drivers,
    )


# ── 2. Risk Score (portfolio variance + drawdown bands) ────────────────
def compute_risk(
    *,
    instruments: List[Dict[str, Any]],
    portfolio_drawdown_pct: Optional[float] = None,
    correlation: float = 0.5,     # blanket simplification (PRD says Cov matrix
                                  # not needed at MVP; use a single number)
) -> ComponentScore:
    """Approximates portfolio variance using a shared correlation assumption
    (0.5 by default — reasonable for an Indian-equity-heavy mix). Each
    instrument must provide {weight, vol_annual_pct}; instruments missing
    vol fall back to the market-cap heuristic.

    Score = 100 - (0.6·VolScore + 0.4·DrawdownScore) → high risk → low score.
    """
    if not instruments:
        return ComponentScore(name="Risk", score=50.0, weight=0.25,
                              sub_scores={}, drivers=[], low_confidence=True,
                              note="No holdings to evaluate")

    # Normalise weights to fractions
    total_w = sum(i.get("weight_pct", 0) for i in instruments) or 100.0
    weights = [i.get("weight_pct", 0) / total_w for i in instruments]
    vols = []
    heuristic_used = False
    for i in instruments:
        v = i.get("vol_annual_pct")
        if v is None:
            v = i.get("fallback_vol_annual_pct")
            heuristic_used = True
        vols.append((v or 20.0) / 100.0)    # decimals

    # Portfolio variance with a blanket correlation ρ
    n = len(weights)
    variance = 0.0
    for i in range(n):
        variance += (weights[i] * vols[i]) ** 2
    for i in range(n):
        for j in range(i + 1, n):
            variance += 2 * weights[i] * weights[j] * vols[i] * vols[j] * correlation
    port_vol_pct = math.sqrt(max(variance, 0.0)) * 100.0

    # Drawdown score (lower DD = better)
    dd_pct = portfolio_drawdown_pct if portfolio_drawdown_pct is not None else min(port_vol_pct * 1.5, 50.0)
    if portfolio_drawdown_pct is None:
        heuristic_used = True
    vol_score   = _linear_band(port_vol_pct, RISK_BANDS["vol_low_pct"], RISK_BANDS["vol_high_pct"])
    dd_score    = _linear_band(dd_pct,       RISK_BANDS["dd_low_pct"],  RISK_BANDS["dd_high_pct"])
    risk_score_raw = 0.6 * vol_score + 0.4 * dd_score    # higher = less risky

    drivers: List[Dict[str, Any]] = []
    if port_vol_pct > 20:
        drivers.append({
            "label": "Portfolio volatility is high",
            "detail": f"Estimated {port_vol_pct:.1f}% annual volatility (comfort ≤ 15%)",
            "impact_points": round((1 - vol_score / 100) * 60, 1),
        })
    if dd_pct > 25:
        drivers.append({
            "label": "Heavy drawdown risk",
            "detail": f"Portfolio could fall ~{dd_pct:.0f}% in a market correction",
            "impact_points": round((1 - dd_score / 100) * 40, 1),
        })

    return ComponentScore(
        name="Risk", score=round(_clamp(risk_score_raw), 2), weight=0.25,
        sub_scores={
            "portfolio_vol_pct": round(port_vol_pct, 2),
            "vol_score": round(vol_score, 2),
            "drawdown_pct": round(dd_pct, 2),
            "drawdown_score": round(dd_score, 2),
            "correlation_used": correlation,
        },
        drivers=drivers, low_confidence=heuristic_used,
        note="Used market-cap-heuristic vols — source real primitives for precision."
             if heuristic_used else None,
    )


# ── 3. Cost Score ───────────────────────────────────────────────────────
def compute_cost(
    *,
    weighted_expense_ratio_pct: float,
    tax_drag_pct: Optional[float] = None,
    regular_plan_weight_pct: float = 0.0,
) -> ComponentScore:
    """Expense score maps 0.5% → 100, 2.0% → 0 (linear). Tax drag uses a
    similar band. Regular-plan weight applies a separate driver."""
    exp_score = _linear_band(weighted_expense_ratio_pct,
                             EXPENSE_SCORE_BANDS["good"], EXPENSE_SCORE_BANDS["poor"])
    tax_score = _linear_band(tax_drag_pct if tax_drag_pct is not None else 1.0,
                             TAX_DRAG_BANDS["good"], TAX_DRAG_BANDS["poor"])
    score = 0.7 * exp_score + 0.3 * tax_score

    drivers: List[Dict[str, Any]] = []
    if weighted_expense_ratio_pct > 1.2:
        drivers.append({
            "label": "Weighted expense ratio is elevated",
            "detail": f"{weighted_expense_ratio_pct:.2f}% (good ≤ 0.50%)",
            "impact_points": round((1 - exp_score / 100) * 30, 1),
        })
    if regular_plan_weight_pct > 5:
        drivers.append({
            "label": "Regular-plan mutual funds detected",
            "detail": f"{regular_plan_weight_pct:.1f}% of portfolio — switching to Direct saves ~0.7–1% p.a.",
            "impact_points": round(regular_plan_weight_pct * 0.3, 1),
        })
    if tax_drag_pct is not None and tax_drag_pct > 2:
        drivers.append({
            "label": "Tax drag from short-term holdings",
            "detail": f"{tax_drag_pct:.1f}% effective drag",
            "impact_points": round((1 - tax_score / 100) * 30, 1),
        })
    return ComponentScore(
        name="Cost", score=round(_clamp(score), 2), weight=0.20,
        sub_scores={
            "expense_score": round(exp_score, 2),
            "tax_score": round(tax_score, 2),
            "weighted_expense_ratio_pct": round(weighted_expense_ratio_pct, 3),
            "tax_drag_pct": tax_drag_pct,
            "regular_plan_weight_pct": round(regular_plan_weight_pct, 2),
        },
        drivers=drivers,
        low_confidence=tax_drag_pct is None,
    )


# ── 4. Performance Score ────────────────────────────────────────────────
def compute_performance(
    *,
    portfolio_return_1y_pct: Optional[float],
    benchmark_return_1y_pct: Optional[float],
    sharpe: Optional[float] = None,
    consistency_score: Optional[float] = None,
) -> ComponentScore:
    """Sharpe mapped via band (0 → 0, 1.5 → 100), alpha mapped on ±10% band,
    consistency passed as-is (already 0-100 from V3 engine).
    """
    heuristic = False
    # Sharpe
    if sharpe is not None:
        sharpe_score = _clamp(sharpe / 1.5 * 100.0)
    elif portfolio_return_1y_pct is not None:
        # Fallback: assume 7% risk-free, 15% vol
        sharpe_score = _clamp((portfolio_return_1y_pct - 7) / 8 * 100.0)
        heuristic = True
    else:
        sharpe_score = 50.0
        heuristic = True
    # Alpha vs benchmark
    if portfolio_return_1y_pct is not None and benchmark_return_1y_pct is not None:
        alpha = portfolio_return_1y_pct - benchmark_return_1y_pct
        alpha_score = _clamp(50 + alpha * 5)   # 10% alpha → 100, -10% → 0
    else:
        alpha_score = 50.0
        alpha = None
        heuristic = True
    # Consistency
    c_score = consistency_score if consistency_score is not None else 50.0
    if consistency_score is None:
        heuristic = True
    score = 0.5 * sharpe_score + 0.3 * alpha_score + 0.2 * c_score

    drivers: List[Dict[str, Any]] = []
    if alpha is not None and alpha < -2:
        drivers.append({
            "label": f"Underperforming benchmark by {abs(alpha):.1f}%",
            "detail": f"Portfolio {portfolio_return_1y_pct:.1f}% vs benchmark {benchmark_return_1y_pct:.1f}% (1y)",
            "impact_points": round(min(abs(alpha) * 3, 30), 1),
        })
    if sharpe is not None and sharpe < 0.5:
        drivers.append({
            "label": "Low risk-adjusted return",
            "detail": f"Sharpe {sharpe:.2f} (comfort ≥ 1.0)",
            "impact_points": round((1 - sharpe_score / 100) * 50, 1),
        })

    return ComponentScore(
        name="Performance", score=round(_clamp(score), 2), weight=0.25,
        sub_scores={
            "sharpe": sharpe, "sharpe_score": round(sharpe_score, 2),
            "alpha_pct": alpha, "alpha_score": round(alpha_score, 2),
            "consistency_score": c_score,
            "portfolio_return_1y_pct": portfolio_return_1y_pct,
            "benchmark_return_1y_pct": benchmark_return_1y_pct,
        },
        drivers=drivers, low_confidence=heuristic,
        note="Limited primitives — returns/sharpe partly inferred." if heuristic else None,
    )


# ── 5. Composite Health Score ──────────────────────────────────────────
def compute_portfolio_health(
    *,
    diversification: ComponentScore,
    risk: ComponentScore,
    cost: ComponentScore,
    performance: ComponentScore,
) -> HealthResult:
    # Weights from PRD: 30 / 25 / 20 / 25
    total = (
        0.30 * diversification.score
        + 0.25 * risk.score
        + 0.20 * cost.score
        + 0.25 * performance.score
    )
    # Headline risk drivers = the highest-impact items across all components,
    # sorted desc. Cap at 5.
    all_drivers: List[Dict[str, Any]] = []
    for c in (diversification, risk, cost, performance):
        for d in c.drivers:
            all_drivers.append({**d, "component": c.name})
    all_drivers.sort(key=lambda d: d.get("impact_points", 0), reverse=True)
    top_drivers = all_drivers[:5]

    # Narrative
    rank_map = [
        (85, "Excellent"), (70, "Strong"), (55, "Fair"), (40, "Weak"), (0, "Poor"),
    ]
    label = next(name for threshold, name in rank_map if total >= threshold)
    summary = (
        f"{label} portfolio — overall Health {round(total):d}/100 "
        f"(D {diversification.score:.0f} · R {risk.score:.0f} · "
        f"C {cost.score:.0f} · P {performance.score:.0f})."
    )

    low_conf = any(c.low_confidence for c in (diversification, risk, cost, performance))

    return HealthResult(
        health_score=round(_clamp(total), 2),
        components={
            "diversification": diversification, "risk": risk,
            "cost": cost, "performance": performance,
        },
        risk_drivers=top_drivers,
        low_confidence=low_conf,
        summary=summary,
    )
