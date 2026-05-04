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
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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


# Stock cost proxy (PRD §4): stocks incur brokerage/slippage ~0.1–0.3% p.a.
STOCK_COST_PROXY_PCT = 0.2

# Market-cap → benchmark mapping (PRD §9E)
CAP_BENCHMARK_RETURN_1Y_PCT = {
    "large":   12.0,   # NIFTY 50 long-run
    "mid":     14.0,   # NIFTY Midcap 150
    "small":   16.0,   # NIFTY Smallcap 250
    "unknown": 12.0,
}

# Letter grade cutoffs (Dashboard UI contract)
GRADE_THRESHOLDS = [
    (90, "A+"), (80, "A"), (70, "B+"),
    (60, "B"),  (50, "C"), (40, "D"),
    (0,  "F"),
]


def score_to_grade(score: Optional[float]) -> str:
    if score is None:
        return "N/A"
    for threshold, label in GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "F"


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
    grade: str                                  # A+/A/B+/B/C/D/F
    components: Dict[str, ComponentScore]
    risk_drivers: List[Dict[str, Any]]         # headline "why is this high?" list
    low_confidence: bool                       # true if any sub was heuristic
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "health_score": self.health_score,
            "grade": self.grade,
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

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HealthResult":
        comps = {}
        for k, c in (d.get("components") or {}).items():
            comps[k] = ComponentScore(
                name=c.get("name", k),
                score=float(c.get("score") or 0),
                weight=float(c.get("weight") or 0),
                sub_scores=c.get("sub_scores") or {},
                drivers=c.get("drivers") or [],
                low_confidence=bool(c.get("low_confidence")),
                note=c.get("note"),
            )
        return cls(
            health_score=float(d.get("health_score") or 0),
            grade=d.get("grade") or "F",
            components=comps,
            risk_drivers=d.get("risk_drivers") or [],
            low_confidence=bool(d.get("low_confidence")),
            summary=d.get("summary") or "",
        )


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

    # Narrative — plain English so non-technical users understand what
    # "Health 48 / Grade D" actually means and which component is dragging it.
    rank_map = [
        (85, "Excellent"), (70, "Strong"), (55, "Fair"), (40, "Weak"), (0, "Poor"),
    ]
    label = next(name for threshold, name in rank_map if total >= threshold)
    grade = score_to_grade(total)

    def _band(score: float) -> str:
        if score >= 85: return "excellent"
        if score >= 70: return "good"
        if score >= 55: return "fair"
        if score >= 40: return "weak"
        return "poor"

    summary = (
        f"{label} portfolio — Health {round(total):d}/100 (Grade {grade}). "
        f"Diversification is {_band(diversification.score)} ({diversification.score:.0f}), "
        f"Risk is {_band(risk.score)} ({risk.score:.0f}), "
        f"Cost is {_band(cost.score)} ({cost.score:.0f}), "
        f"Performance is {_band(performance.score)} ({performance.score:.0f})."
    )

    low_conf = any(c.low_confidence for c in (diversification, risk, cost, performance))

    return HealthResult(
        health_score=round(_clamp(total), 2),
        grade=grade,
        components={
            "diversification": diversification, "risk": risk,
            "cost": cost, "performance": performance,
        },
        risk_drivers=top_drivers,
        low_confidence=low_conf,
        summary=summary,
    )



# ── 6. Orchestrator (ties it all together) ─────────────────────────────
# Maps a MongoDB user_id to the full HealthResult. Gathers:
#   - MF holdings + V3 primitives (from the same pipeline as
#     `/api/insights/v3-portfolio`)
#   - Equity holdings + market-cap classification + β/σ heuristic
#     (via `stock_enricher`)
#   - Pairwise MF overlap (value-weighted) from `portfolio_intelligence`
#   - User risk profile + horizon for ideal allocation

# Profile → risk_profile mapping (DB is free-form, normalise here)
_RISK_PROFILE_ALIASES = {
    "conservative": "conservative", "low": "conservative", "safe": "conservative",
    "moderate": "moderate", "medium": "moderate", "balanced": "moderate",
    "aggressive": "aggressive", "high": "aggressive", "growth": "aggressive",
}


def _normalise_risk(raw: Optional[str]) -> str:
    return _RISK_PROFILE_ALIASES.get(
        (raw or "moderate").strip().lower(), "moderate"
    )


def _ideal_allocation(risk_profile: str, horizon_years: float) -> Dict[str, float]:
    base = dict(IDEAL_ALLOCATIONS.get(risk_profile, IDEAL_ALLOCATIONS["moderate"]))
    if horizon_years and horizon_years < 5 and base.get("equity", 0) > SHORT_HORIZON_CAP_EQUITY:
        gap = base["equity"] - SHORT_HORIZON_CAP_EQUITY
        base["equity"] = SHORT_HORIZON_CAP_EQUITY
        base["debt"] = base.get("debt", 0) + gap
    return base


def _classify_asset(holding: Dict[str, Any]) -> str:
    """Simple asset-class bucket for allocation calc (mirrors
    portfolio_intelligence._compute_holistic_allocation)."""
    at = (holding.get("asset_type") or "").lower()
    name = (holding.get("name") or "").lower()
    if at == "gold" or "gold" in name or "sgb" in name or "sovereign gold" in name:
        return "gold"
    is_debt_mf_or_etf = at in ("mutual_fund", "etf") and any(
        k in name for k in [
            "liquid", "gilt", "bond", "corporate bond", "short term",
            "overnight", "banking & psu", "low duration", "ultra short",
            "medium duration", "long duration", "credit risk",
            "floater", "dynamic bond", "debt",
        ]
    )
    if at in ("bond", "debt", "fd", "deposit") or is_debt_mf_or_etf:
        return "debt"
    if at in ("mutual_fund", "etf"):
        name_l = name
        if "hybrid" in name_l or "balanced" in name_l or "multi asset" in name_l:
            return "hybrid"
        return "equity"
    if at in ("equity", "stock"):
        return "equity"
    return "other"


def _stock_weights_for_concentration(
    equity_holdings: List[Dict[str, Any]],
    mf_top_stocks: List[Dict[str, Any]],
) -> List[float]:
    """Build a stock-level weight vector combining direct equity + MF
    look-through. Weights are absolute (rupees); HHI normalises internally."""
    weights: List[float] = []
    # Direct equity exposure
    for h in equity_holdings:
        val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        if val > 0:
            weights.append(val)
    # MF look-through: portfolio_intelligence returns `top_stocks` sorted desc
    # with `value_rs` fields. Use those as proxy stock-level weights.
    for s in mf_top_stocks:
        val = float(s.get("value_rs") or s.get("value") or 0)
        if val > 0:
            weights.append(val)
    return weights


def _weighted_mf_expense(
    mf_investments: List[Dict[str, Any]],
    v3_by_id: Dict[str, Any],
    *,
    equity_value_rs: float = 0.0,
) -> Dict[str, float]:
    """Value-weighted expense ratio across MF holdings + stock cost proxy.
    Also returns the % of portfolio in Regular plans (expense-ratio >> Direct).

    Stocks contribute `STOCK_COST_PROXY_PCT` (0.2%) for brokerage/slippage.
    """
    total = equity_value_rs   # stocks always count toward denominator
    weighted_exp = equity_value_rs * STOCK_COST_PROXY_PCT
    regular_val = 0.0
    for m in mf_investments:
        val = float(m.get("value") or m.get("amount_rs") or 0)
        if val <= 0:
            continue
        total += val
        iid = m.get("instrument_id")
        v3 = v3_by_id.get(iid) if iid else None
        exp = None
        if v3:
            prim = v3.get("v3_primitives") or v3
            exp = prim.get("expense_ratio_direct") or prim.get("expense_ratio")
        exp = exp if exp is not None else 1.0  # safe default (median India MF)
        weighted_exp += float(exp) * val
        name_l = (m.get("scheme_name") or "").lower()
        if "regular" in name_l and "direct" not in name_l:
            regular_val += val
    if total <= 0:
        return {"expense_pct": 1.0, "regular_plan_weight_pct": 0.0}
    return {
        "expense_pct": weighted_exp / total,
        "regular_plan_weight_pct": (regular_val / total) * 100.0,
    }


def _portfolio_avg_health_from_v3(
    mf_investments: List[Dict[str, Any]],
    v3_by_id: Dict[str, Any],
) -> Dict[str, Optional[float]]:
    """Value-weighted Health + Quality + consistency across scored MFs."""
    total = sum(float(m.get("value") or 0) for m in mf_investments) or 0.0
    if total <= 0:
        return {"avg_health": None, "avg_quality": None, "avg_consistency": None}
    w_h = w_q = w_c = 0.0
    cov_h = cov_q = cov_c = 0.0
    for m in mf_investments:
        val = float(m.get("value") or 0)
        if val <= 0:
            continue
        iid = m.get("instrument_id")
        v3 = v3_by_id.get(iid) if iid else None
        if not v3:
            continue
        if v3.get("health_score") is not None:
            w_h += float(v3["health_score"]) * val
            cov_h += val
        if v3.get("quality_score") is not None:
            w_q += float(v3["quality_score"]) * val
            cov_q += val
        cons = (v3.get("health_components") or {}).get("consistency_score")
        if cons is not None:
            w_c += float(cons) * val
            cov_c += val
    return {
        "avg_health":      (w_h / cov_h) if cov_h else None,
        "avg_quality":     (w_q / cov_q) if cov_q else None,
        "avg_consistency": (w_c / cov_c) if cov_c else None,
    }


HEALTH_CACHE_TTL_S = 24 * 3600  # 24h — long enough that activate-snapshot returns instantly


async def _active_snapshot_date(user_id: str) -> Optional[str]:
    from deps import db as _db
    u = await _db.users.find_one(
        {"user_id": user_id}, {"_id": 0, "cas_view_state": 1},
    )
    return ((u or {}).get("cas_view_state") or {}).get("current_snapshot_date")


def _health_cache_key(user_id: str, snapshot_date: Optional[str]) -> Optional[str]:
    """Stable Redis key for a user's health when viewing a specific snapshot.
    Returns None when no snapshot is mounted (then we don't cache — the live
    holdings table can be in any transient state)."""
    if not snapshot_date:
        return None
    return f"health:{user_id}:{snapshot_date}"


async def cache_health_for_snapshot(
    user_id: str, snapshot_date: str, result: HealthResult,
) -> bool:
    """Persist a computed health result for one snapshot — TWO backing
    stores so a Redis-less environment still gets a fast path:
      - Redis under `health:{user_id}:{snapshot_date}` (24h TTL)
      - Mongo `portfolio_snapshots.health_full` (durable, no TTL)

    Called from `cas_snapshot_engine.create_cas_snapshot` so timeline-
    scrubbing is instant — the next `build_portfolio_health(user_id)`
    that resolves to this snapshot returns from Mongo without re-running
    the Groww/V3/intelligence pipeline.
    """
    from services import redis_client
    from deps import db as _db
    payload = result.to_dict()
    key = _health_cache_key(user_id, snapshot_date)
    redis_ok = False
    if key:
        try:
            redis_ok = await redis_client.cache_set(key, payload, ttl_s=HEALTH_CACHE_TTL_S)
        except Exception:  # noqa: BLE001
            logger.warning("cache_health_for_snapshot redis write failed", exc_info=True)
    try:
        await _db.portfolio_snapshots.update_one(
            {"user_id": user_id, "snapshot_date": snapshot_date},
            {"$set": {"health_full": payload}},
        )
    except Exception:  # noqa: BLE001
        logger.warning("cache_health_for_snapshot mongo write failed", exc_info=True)
    return redis_ok


async def _snapshot_fast_path(user_id: str, snap_date: Optional[str]) -> Optional[HealthResult]:
    """Mongo fast-path: read a previously-computed HealthResult off the
    active snapshot doc. Returns None if no snapshot is mounted, no
    score is stored, or the doc shape is unrecognised.

    This makes the common case (user already has a CAS-derived snapshot
    mounted) instantaneous — `cas_snapshot_engine.create_cas_snapshot`
    populates `health_full` at create time.
    """
    if not snap_date:
        return None
    from deps import db as _db
    snap = await _db.portfolio_snapshots.find_one(
        {"user_id": user_id, "snapshot_date": snap_date},
        {"_id": 0, "health_full": 1, "health_score": 1, "grade": 1, "scores": 1, "summary": 1},
    )
    if not snap:
        return None
    # Best case — the full payload was stashed at create time.
    if isinstance(snap.get("health_full"), dict) and snap["health_full"].get("health_score") is not None:
        try:
            return HealthResult.from_dict(snap["health_full"])
        except Exception:  # noqa: BLE001
            logger.warning("snapshot health_full deserialise failed for %s", user_id, exc_info=True)
    # Older snapshots only have flat scores. Reconstruct a minimal
    # HealthResult so the UI shows the score+grade without the full
    # component drilldown (which the page can fetch lazily on click).
    hs = snap.get("health_score")
    if hs is None:
        return None
    flat = snap.get("scores") or {}
    comps: Dict[str, ComponentScore] = {}
    for k, v in flat.items():
        if k == "health":
            continue
        try:
            comps[k] = ComponentScore(name=k, score=float(v), weight=0.0)
        except (TypeError, ValueError):
            pass
    # Synthesise the human-readable summary from the flat scores when the
    # snapshot doesn't carry one (older snapshots predate the summary field).
    # Mirrors the labelling in compute_portfolio_health so the Insights UI
    # reads the same plain-English explainer regardless of which path served it.
    stored_summary = snap.get("summary")
    if not stored_summary:
        rank_map = [
            (85, "Excellent"), (70, "Strong"), (55, "Fair"), (40, "Weak"), (0, "Poor"),
        ]
        score_for_label = float(hs)
        label = next(name for threshold, name in rank_map if score_for_label >= threshold)

        def _band(s: float) -> str:
            if s >= 85: return "excellent"
            if s >= 70: return "good"
            if s >= 55: return "fair"
            if s >= 40: return "weak"
            return "poor"

        # Component scores live under varied keys depending on snapshot vintage
        # ("Diversification" vs "diversification"); normalise on lookup.
        def _score_of(name: str) -> Optional[float]:
            for k in (name, name.lower(), name.capitalize(), name.upper()):
                if k in flat:
                    try:
                        return float(flat[k])
                    except (TypeError, ValueError):
                        return None
            return None

        ds = _score_of("diversification")
        rs = _score_of("risk")
        cs = _score_of("cost")
        ps = _score_of("performance")

        if all(v is not None for v in (ds, rs, cs, ps)):
            stored_summary = (
                f"{label} portfolio — Health {round(score_for_label):d}/100 "
                f"(Grade {snap.get('grade') or _grade_from_score(score_for_label)}). "
                f"Diversification is {_band(ds)} ({ds:.0f}), "
                f"Risk is {_band(rs)} ({rs:.0f}), "
                f"Cost is {_band(cs)} ({cs:.0f}), "
                f"Performance is {_band(ps)} ({ps:.0f})."
            )
        else:
            stored_summary = (
                f"{label} portfolio — Health {round(score_for_label):d}/100 "
                f"(Grade {snap.get('grade') or _grade_from_score(score_for_label)})."
            )

    return HealthResult(
        health_score=float(hs),
        grade=snap.get("grade") or _grade_from_score(float(hs)),
        components=comps,
        risk_drivers=[],
        low_confidence=False,
        summary=stored_summary,
    )


def _grade_from_score(s: float) -> str:
    if s >= 90: return "A+"
    if s >= 80: return "A"
    if s >= 70: return "B+"
    if s >= 60: return "B"
    if s >= 50: return "C"
    if s >= 40: return "D"
    return "F"


async def build_portfolio_health(
    user_id: str,
    *,
    force_refresh_stocks: bool = False,
) -> HealthResult:
    """Compute Portfolio Health end-to-end for a user.

    Pulls MF holdings + V3 scores, equity holdings + Groww fundamentals
    (cached 24h), MF overlap from portfolio_intelligence, and the user's
    risk profile. Calls the 4 component scorers and returns the full
    HealthResult (ready to serialise via `.to_dict()`).

    Result is memoised in Redis under `health:{user_id}:{snapshot_date}`
    for 24h so activating an older snapshot doesn't re-run the full
    enrichment pipeline (Groww/V3/intelligence) unless the holdings
    underneath actually changed.
    """
    # Lazy imports so unit tests can import portfolio_health without the
    # whole FastAPI graph.
    from deps import db as _db                               # noqa: WPS433
    from services import portfolio_intelligence as _pintel    # noqa: WPS433
    from services import v3_integration as _v3i               # noqa: WPS433
    from services import stock_enricher as _enricher          # noqa: WPS433
    from services import redis_client as _redis               # noqa: WPS433

    # ── Cache lookup ────────────────────────────────────────────────────
    snap_date = await _active_snapshot_date(user_id)
    cache_key = _health_cache_key(user_id, snap_date)
    if not force_refresh_stocks:
        # 1. Redis (instant)
        if cache_key:
            try:
                cached = await _redis.cache_get(cache_key)
                if cached:
                    logger.info("portfolio_health redis cache hit %s", cache_key)
                    return HealthResult.from_dict(cached)
            except Exception:  # noqa: BLE001
                logger.warning("portfolio_health redis read failed", exc_info=True)
        # 2. Mongo snapshot doc (durable fallback for Redis-less envs)
        snap_health = await _snapshot_fast_path(user_id, snap_date)
        if snap_health is not None:
            logger.info("portfolio_health snapshot fast-path hit %s/%s", user_id, snap_date)
            # Backfill Redis so subsequent reads stay fast
            if cache_key:
                try:
                    await _redis.cache_set(cache_key, snap_health.to_dict(), ttl_s=HEALTH_CACHE_TTL_S)
                except Exception:  # noqa: BLE001
                    pass
            return snap_health

    # 1. Load all holdings (MF + equity + ETF)
    all_holdings: List[Dict[str, Any]] = await _db.holdings.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(1000)
    mf_holdings = [h for h in all_holdings if (h.get("asset_type") or "").lower() in ("mutual_fund", "etf")]
    equity_holdings = [h for h in all_holdings if (h.get("asset_type") or "").lower() in ("equity", "stock")]

    if not all_holdings:
        return HealthResult(
            health_score=0.0, grade="F", components={}, risk_drivers=[],
            low_confidence=True, summary="No holdings on file — upload a CAS to compute Health.",
        )

    # 2. Asset allocation (actual) + ideal from risk profile
    alloc_actual: Dict[str, float] = {}
    total_val = 0.0
    for h in all_holdings:
        val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        if val <= 0:
            continue
        total_val += val
        bucket = _classify_asset(h)
        # Roll ETF into debt or equity already; map gold → hybrid-like
        if bucket == "gold":
            alloc_actual["hybrid"] = alloc_actual.get("hybrid", 0.0) + val
        elif bucket == "hybrid":
            alloc_actual["hybrid"] = alloc_actual.get("hybrid", 0.0) + val
        elif bucket == "debt":
            alloc_actual["debt"] = alloc_actual.get("debt", 0.0) + val
        elif bucket == "equity":
            alloc_actual["equity"] = alloc_actual.get("equity", 0.0) + val
        else:
            alloc_actual["other"] = alloc_actual.get("other", 0.0) + val
    if total_val > 0:
        alloc_actual = {k: (v / total_val) * 100.0 for k, v in alloc_actual.items()}

    user_doc = await _db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    raw_rp = (
        user_doc.get("risk_profile")
        or (user_doc.get("profile") or {}).get("risk_profile")
    )
    risk_profile = _normalise_risk(raw_rp)
    ideal_alloc = _ideal_allocation(risk_profile, horizon_years=10.0)

    # 3. Enrich equities (Groww cap → heuristic β/σ)
    try:
        stock_funda = await _enricher.enrich_stocks_for_user(
            user_id, force_refresh=force_refresh_stocks,
        )
    except Exception as e:  # noqa: BLE001
        import logging as _log
        _log.getLogger(__name__).warning(f"stock enrichment failed: {e}")
        stock_funda = {}

    # 4. MF V3 enrichment + portfolio_intelligence for overlap/look-through
    mf_investments = [
        {
            "scheme_name": h.get("name"),
            "instrument_id": h.get("instrument_id"),
            "value": float(h.get("quantity") or 0) * float(h.get("current_price") or 0),
        }
        for h in mf_holdings
        if (float(h.get("quantity") or 0) * float(h.get("current_price") or 0)) > 0
    ]
    v3_by_id: Dict[str, Any] = {}
    if mf_investments:
        try:
            v3_map = await _v3i.enrich_candidates_with_v3(
                mf_investments=mf_investments,
                exit_candidates=[],
                mf_holdings=mf_holdings,
                portfolio_intelligence={},
            )
            # v3_map is keyed by (iid, name); normalise to by-id
            for m in mf_investments:
                iid = m.get("instrument_id")
                v3 = _v3i.lookup_v3(iid, m.get("scheme_name", ""), v3_map)
                if iid and v3:
                    v3_by_id[iid] = v3
        except Exception as e:  # noqa: BLE001
            import logging as _log
            _log.getLogger(__name__).warning(f"V3 enrichment failed: {e}")

    pi: Dict[str, Any] = {}
    try:
        pi = await _pintel.compute_portfolio_intelligence(user_id)
    except Exception as e:  # noqa: BLE001
        import logging as _log
        _log.getLogger(__name__).warning(f"portfolio_intelligence failed: {e}")

    # Value-weighted avg pairwise overlap
    avg_overlap_pct: Optional[float] = None
    if pi and pi.get("pairwise_overlap") and pi.get("mf_investments"):
        val_by_iid = {m["instrument_id"]: m.get("amount_rs", 0)
                      for m in pi["mf_investments"] if m.get("instrument_id")}
        total_pair_w = 0.0
        weighted_ov = 0.0
        for pair in pi["pairwise_overlap"]:
            a_val = val_by_iid.get(pair["a"], 0.0)
            b_val = val_by_iid.get(pair["b"], 0.0)
            w = min(a_val, b_val)
            if w > 0:
                weighted_ov += float(pair.get("overlap_pct") or 0) * w
                total_pair_w += w
        if total_pair_w > 0:
            avg_overlap_pct = weighted_ov / total_pair_w

    # 5. Build stock-level weights for concentration (equity + MF look-through)
    mf_top_stocks = pi.get("top_stocks", []) if pi else []
    stock_weights = _stock_weights_for_concentration(equity_holdings, mf_top_stocks)

    # 6. Component: Diversification
    divers = compute_diversification(
        stock_weights=stock_weights,
        asset_allocation_actual=alloc_actual,
        asset_allocation_ideal=ideal_alloc,
        portfolio_overlap_pct=avg_overlap_pct,
    )

    # 7. Component: Risk
    # Build instruments with (weight_pct, vol_annual_pct) per holding.
    instruments: List[Dict[str, Any]] = []
    if total_val > 0:
        for h in equity_holdings:
            val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
            if val <= 0:
                continue
            sym = (h.get("nse_symbol") or "").upper()
            ent = stock_funda.get(sym, {})
            vol = ent.get("vol_annual_pct")
            instruments.append({
                "weight_pct": (val / total_val) * 100.0,
                "vol_annual_pct": vol,
                "fallback_vol_annual_pct": _enricher.CAP_HEURISTICS["unknown"]["vol_annual_pct"],
            })
        # MF vol proxy: Equity MF ~20%, Debt MF ~3%, Hybrid ~10%
        for h in mf_holdings:
            val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
            if val <= 0:
                continue
            bucket = _classify_asset(h)
            mf_vol = {"equity": 20.0, "debt": 3.0, "hybrid": 10.0}.get(bucket, 18.0)
            instruments.append({
                "weight_pct": (val / total_val) * 100.0,
                "vol_annual_pct": mf_vol,
                "fallback_vol_annual_pct": mf_vol,
            })
    # Drawdown proxy: max per-fund max_drawdown from V3 weighted (if any)
    dd_sum = 0.0
    dd_w = 0.0
    for m in mf_investments:
        iid = m.get("instrument_id")
        v3 = v3_by_id.get(iid) if iid else None
        if not v3:
            continue
        prim = v3.get("v3_primitives") or {}
        dd = prim.get("max_drawdown_pct")
        if dd is not None:
            dd_sum += abs(float(dd)) * float(m.get("value", 0))
            dd_w += float(m.get("value", 0))
    portfolio_dd = (dd_sum / dd_w) if dd_w > 0 else None

    risk = compute_risk(
        instruments=instruments,
        portfolio_drawdown_pct=portfolio_dd,
        correlation=0.5,
    )

    # 8. Component: Cost (includes stock brokerage proxy 0.2%)
    equity_value_rs = sum(
        float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        for h in equity_holdings
    )
    cost_bundle = _weighted_mf_expense(
        mf_investments, v3_by_id, equity_value_rs=equity_value_rs,
    )
    # Tax drag: skip real calc for MVP (complex FIFO). Leave None → heuristic.
    cost = compute_cost(
        weighted_expense_ratio_pct=cost_bundle["expense_pct"],
        tax_drag_pct=None,
        regular_plan_weight_pct=cost_bundle["regular_plan_weight_pct"],
    )

    # 9. Component: Performance — cap-weighted benchmark from stock enrichment
    mf_avg = _portfolio_avg_health_from_v3(mf_investments, v3_by_id)
    total_inv = sum(float(h.get("quantity") or 0) * float(h.get("buy_price") or 0) for h in all_holdings)
    total_cur = sum(float(h.get("quantity") or 0) * float(h.get("current_price") or 0) for h in all_holdings)
    port_return_1y = ((total_cur - total_inv) / total_inv * 100.0) if total_inv > 0 else None

    # Cap-weighted benchmark: blend NIFTY 50 / Midcap 150 / Smallcap 250 per equity mix
    benchmark_return_1y: Optional[float] = None
    if port_return_1y is not None:
        bench_w = 0.0
        bench_sum = 0.0
        for h in equity_holdings:
            val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
            if val <= 0:
                continue
            sym = (h.get("nse_symbol") or "").upper()
            ent = stock_funda.get(sym, {})
            bucket = ent.get("cap_bucket", "unknown")
            bench_sum += CAP_BENCHMARK_RETURN_1Y_PCT.get(bucket, 12.0) * val
            bench_w += val
        # MF gets a flat 12% (NIFTY 50 proxy); stocks get per-cap-bucket
        for m in mf_investments:
            val = float(m.get("value") or 0)
            if val <= 0:
                continue
            bench_sum += 12.0 * val
            bench_w += val
        benchmark_return_1y = (bench_sum / bench_w) if bench_w > 0 else 12.0

    perf = compute_performance(
        portfolio_return_1y_pct=port_return_1y,
        benchmark_return_1y_pct=benchmark_return_1y,
        sharpe=None,
        consistency_score=mf_avg.get("avg_consistency"),
    )

    # 10. Composite
    result = compute_portfolio_health(
        diversification=divers, risk=risk, cost=cost, performance=perf,
    )
    # Persist to BOTH Redis (TTL'd) and the snapshot doc (durable) so
    # subsequent reads short-circuit the slow path even when Redis is
    # unconfigured or has been flushed.
    if snap_date and result and result.health_score is not None:
        try:
            await cache_health_for_snapshot(user_id, snap_date, result)
        except Exception:  # noqa: BLE001
            logger.warning("portfolio_health write-back failed", exc_info=True)
    return result
