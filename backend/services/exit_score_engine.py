"""Exit / Review Scoring Engine — per-holding deterministic 0-100 score.

User spec (2026-05-20):

  8 weighted factors, sum to 100%:
    Portfolio Fit          25%   investment thesis still valid; allocation aligned
    Performance            20%   relative return over 1Y/3Y vs category benchmark
    Risk-Adjusted Returns  10%   Sharpe / Sortino / max drawdown
    Fundamentals            15%   stocks: PE, ROE, D/E, Piotroski, Altman
                                  MFs: look-through quality of underlying stocks
    Valuation               10%   stocks: PE vs sector; MFs: TER
    Better Alternatives     10%   superior same-category substitute available?
    Concentration / Overlap  5%   weight too high or overlap too duplicative?
    Governance              5%   promoter pledge / FII trend / red flags

  Recommendation bands:
    85–100   Strong Hold
    70–84    Hold
    55–69    Review
    40–54    Consider Switch / Trim
    < 40     Exit Recommended

  Confidence:
    HIGH    score < 35 or > 85  (extreme — decision is clear)
    MEDIUM  score 35–55 or 70–85
    LOW     score 55–69          (middling — genuine "unsure" zone)

  Trigger overrides — regardless of score:
    Exit Recommended:
      - governance red flag (fraud / auditor change / regulatory action)
      - persistent bottom-quartile for 3+ years
      - investment thesis clearly broken
    Strong Hold:
      - top-quartile performer + thesis intact + valuation attractive + fits allocation

Design tenets:
  - PURE function. No DB access, no network — caller assembles signals.
  - HONEST framing. Missing signals return None and redistribute weight
    across the remaining factors (V3 pattern, see services/v3_scoring.py:151).
    Never fake a score; the breakdown exposes which factors were absent.
  - DETERMINISTIC. Same input → same output. No LLM, no randomness.
  - COMPOSABLE. The 8 factor scorers are individually exported so tests
    and callers can probe a single dimension.

Output shape matches the user's JSON spec:
  {
    "score": 55,
    "recommendation": "Review",
    "confidence": "MEDIUM",
    "top_reasons": [...],
    "factor_breakdown": [...],     # for the drilldown UI
    "missing_signals": [...],
    "override_triggered": null | "...",
  }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Weights ──────────────────────────────────────────────────────────
# Names match the spec. Must sum to 100.
WEIGHTS: Dict[str, float] = {
    "portfolio_fit":  25.0,
    "performance":    20.0,
    "risk_adj":       10.0,
    "fundamentals":   15.0,
    "valuation":      10.0,
    "alternatives":   10.0,
    "concentration":   5.0,
    "governance":      5.0,
}
assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-9, "WEIGHTS must sum to 100"


# ── Recommendation bands ─────────────────────────────────────────────
RECOMMENDATION_BANDS = [
    (85.0, "Strong Hold"),
    (70.0, "Hold"),
    (55.0, "Review"),
    (40.0, "Consider Switch / Trim"),
    (0.0,  "Exit Recommended"),
]


# ── Dataclasses ──────────────────────────────────────────────────────
@dataclass
class ExitScoreInput:
    """All signals the engine needs. Caller (analytics route) assembles
    these from NIDP feeds + copilot_tools + user profile. Every Optional
    field gets weight-redistributed when absent — never imputed.
    """
    # ── Identity (required) ──
    holding_id: str
    name: str
    asset_type: str                # "stock" | "mutual_fund" | "etf" | "gold" | "debt" | ...

    # ── Position economics (required) ──
    invested_rs: float
    current_rs: float
    weight_pct: float              # this holding's % of user portfolio
    pct_return: float              # total return since purchase

    # ── Performance (factor 2) ──
    return_1y: Optional[float] = None
    return_3y: Optional[float] = None
    benchmark_return_1y: Optional[float] = None
    alpha_1y: Optional[float] = None        # return_1y − benchmark_return_1y

    # ── Risk-Adjusted (factor 3) ──
    sharpe_1y: Optional[float] = None
    sortino_1y: Optional[float] = None
    max_drawdown_1y_pct: Optional[float] = None

    # ── Fundamentals (factor 4) ──
    # For asset_type == "stock"
    pe_ttm: Optional[float] = None
    roe_pct: Optional[float] = None
    debt_to_equity: Optional[float] = None
    piotroski_score: Optional[float] = None    # 0-9
    altman_z_score: Optional[float] = None
    # For asset_type == "mutual_fund" / "etf" (look-through via v_mf_lookthrough_quality)
    lookthrough_piotroski: Optional[float] = None
    lookthrough_roe_pct: Optional[float] = None
    lookthrough_coverage_pct: Optional[float] = None   # 0-100; treat <60 as missing

    # ── Valuation (factor 5) ──
    ter_pct: Optional[float] = None              # mutual fund TER
    pe_vs_sector_pct: Optional[float] = None     # stock PE vs sector median (already derived)

    # ── Alternatives (factor 6) ──
    has_better_alternative: bool = False
    alternative_alpha_pp: Optional[float] = None

    # ── Concentration (factor 7) ──
    overlap_pct_max: Optional[float] = None      # highest pairwise overlap with another holding

    # ── Governance (factor 8) ──
    promoter_pledge_pct: Optional[float] = None
    fii_pct_change_qoq: Optional[float] = None

    # ── Portfolio Fit (factor 1) — derived from target_allocator + user goals ──
    target_weight_pct: Optional[float] = None    # target % for this asset class
    actual_weight_pct: Optional[float] = None    # current % for this asset class
    thesis_still_valid: Optional[bool] = None    # ops/user feedback flag

    # ── Trigger override flags (always-Exit conditions) ──
    has_governance_red_flag: bool = False        # fraud / auditor change / regulatory action
    persistent_bottom_quartile_3y: bool = False
    thesis_clearly_broken: bool = False

    # ── Trigger override flags (always-Hold conditions) ──
    top_quartile_long_term: bool = False         # >=3y top-quartile rank


@dataclass
class FactorContribution:
    """Per-factor breakdown — surfaced in the drilldown UI."""
    name: str
    raw_score_0_10: Optional[float]
    effective_weight: float       # weight after redistribution (sums to 100 across present factors)
    contribution: float           # raw_score × effective_weight / 10   (0..effective_weight)
    reason: str


@dataclass
class ExitScoreResult:
    holding_id: str
    name: str
    score: Optional[float]                        # 0-100, None when no signals at all
    recommendation: str                           # one of the 5 bands or "INSUFFICIENT_DATA"
    confidence: str                               # HIGH / MEDIUM / LOW
    factor_breakdown: List[FactorContribution]
    top_reasons: List[str]
    missing_signals: List[str]
    override_triggered: Optional[str] = None      # set when trigger forces a decision

    def to_dict(self) -> Dict[str, Any]:
        return {
            "holding_id":         self.holding_id,
            "name":               self.name,
            "score":              None if self.score is None else round(self.score, 1),
            "recommendation":     self.recommendation,
            "confidence":         self.confidence,
            "top_reasons":        list(self.top_reasons),
            "missing_signals":    list(self.missing_signals),
            "override_triggered": self.override_triggered,
            "factor_breakdown": [
                {
                    "name":             f.name,
                    "raw_score_0_10":   None if f.raw_score_0_10 is None else round(f.raw_score_0_10, 2),
                    "effective_weight": round(f.effective_weight, 1),
                    "contribution":     round(f.contribution, 2),
                    "reason":           f.reason,
                }
                for f in self.factor_breakdown
            ],
        }


# ── Helpers ──────────────────────────────────────────────────────────
def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


# ── Factor scorers ───────────────────────────────────────────────────
# Each returns (score_0_10 or None, human-readable reason).
# Returning None means "data unavailable" — caller redistributes weight.

def _score_portfolio_fit(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    """Factor 1 — 25%. Allocation drift from target asset-class weight."""
    if inp.target_weight_pct is None or inp.actual_weight_pct is None:
        return None, "no target allocation set"
    gap = abs(inp.actual_weight_pct - inp.target_weight_pct)
    if gap <= 2:
        return 10.0, f"well-aligned (gap {gap:.1f}pp)"
    if gap <= 5:
        return 7.0,  f"close to target (gap {gap:.1f}pp)"
    if gap <= 10:
        return 4.0,  f"drifted from target (gap {gap:.1f}pp)"
    return 1.0, f"far from target (gap {gap:.1f}pp)"


def _score_performance(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    """Factor 2 — 20%. Return vs category benchmark."""
    # Prefer alpha_1y when available (already-derived)
    if inp.alpha_1y is not None:
        a = inp.alpha_1y
        if a >= 5:    return 10.0, f"+{a:.1f}pp vs peers (strong)"
        if a >= 2:    return 8.0,  f"+{a:.1f}pp vs peers"
        if a >= 0:    return 6.0,  f"+{a:.1f}pp vs peers (meeting)"
        if a >= -3:   return 4.0,  f"{a:.1f}pp vs peers (lagging)"
        if a >= -5:   return 2.0,  f"{a:.1f}pp vs peers (underperforming)"
        return 1.0,                f"{a:.1f}pp vs peers (deeply underperforming)"

    # Fall back to absolute return_1y if no benchmark available
    if inp.return_1y is not None:
        r = inp.return_1y
        if r >= 20:   return 8.0,  f"+{r:.1f}% 1Y (no benchmark)"
        if r >= 10:   return 6.0,  f"+{r:.1f}% 1Y (no benchmark)"
        if r >= 0:    return 4.0,  f"+{r:.1f}% 1Y (no benchmark)"
        return 2.0,                f"{r:.1f}% 1Y (no benchmark)"

    return None, "no return_1y data"


def _score_risk_adj(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    """Factor 3 — 10%. Sharpe primary; max drawdown as secondary penalty."""
    if inp.sharpe_1y is None:
        return None, "no Sharpe ratio"

    s = inp.sharpe_1y
    if s >= 1.5:   base, msg = 10.0, f"Sharpe {s:.2f} (excellent)"
    elif s >= 1.0: base, msg = 8.0,  f"Sharpe {s:.2f} (good)"
    elif s >= 0.5: base, msg = 5.0,  f"Sharpe {s:.2f} (modest)"
    elif s >= 0:   base, msg = 3.0,  f"Sharpe {s:.2f} (weak)"
    else:          base, msg = 1.0,  f"Sharpe {s:.2f} (negative)"

    # Penalise severe drawdowns
    if inp.max_drawdown_1y_pct is not None and inp.max_drawdown_1y_pct < -30:
        base = _clamp(base - 2.0)
        msg += f"; drawdown {inp.max_drawdown_1y_pct:.1f}%"

    return base, msg


def _score_fundamentals(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    """Factor 4 — 15%. Stocks: PE/ROE/D-E/Piotroski/Altman composite.
    MFs: look-through quality (only when coverage >= 60%)."""
    asset = (inp.asset_type or "").lower()

    if asset == "stock" or asset == "equity":
        return _score_stock_fundamentals(inp)
    if asset in ("mutual_fund", "mf", "etf"):
        return _score_mf_fundamentals(inp)
    return None, f"no fundamental signals for {asset!r}"


def _score_stock_fundamentals(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    parts: List[float] = []
    reasons: List[str] = []

    if inp.piotroski_score is not None:
        # 0-9 scale → normalize to 0-10
        parts.append(_clamp(inp.piotroski_score * (10.0 / 9.0)))
        label = "strong" if inp.piotroski_score >= 7 else "ok" if inp.piotroski_score >= 5 else "weak"
        reasons.append(f"Piotroski {int(inp.piotroski_score)}/9 ({label})")

    if inp.roe_pct is not None:
        roe = inp.roe_pct
        if roe >= 20:   parts.append(9.0)
        elif roe >= 12: parts.append(7.0)
        elif roe >= 5:  parts.append(5.0)
        elif roe >= 0:  parts.append(3.0)
        else:           parts.append(1.0)
        reasons.append(f"ROE {roe:.1f}%")

    if inp.debt_to_equity is not None:
        de = inp.debt_to_equity
        if de <= 0.3:   parts.append(10.0)
        elif de <= 1:   parts.append(7.0)
        elif de <= 2:   parts.append(4.0)
        else:           parts.append(1.0)
        reasons.append(f"D/E {de:.2f}")

    if inp.altman_z_score is not None:
        z = inp.altman_z_score
        if z > 2.99:    parts.append(9.0)
        elif z > 1.81:  parts.append(5.0)
        else:           parts.append(2.0)
        reasons.append(f"Altman Z {z:.2f}")

    if not parts:
        return None, "no stock fundamentals"

    return sum(parts) / len(parts), " · ".join(reasons)


def _score_mf_fundamentals(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    # Look-through is only meaningful when we covered enough of the fund's NAV
    if inp.lookthrough_coverage_pct is None or inp.lookthrough_coverage_pct < 60:
        return None, "look-through coverage < 60% — not surfacing fund fundamentals"

    parts: List[float] = []
    reasons: List[str] = []

    if inp.lookthrough_piotroski is not None:
        parts.append(_clamp(inp.lookthrough_piotroski * (10.0 / 9.0)))
        reasons.append(f"weighted Piotroski {inp.lookthrough_piotroski:.1f}/9")

    if inp.lookthrough_roe_pct is not None:
        roe = inp.lookthrough_roe_pct
        if roe >= 20:   parts.append(9.0)
        elif roe >= 12: parts.append(7.0)
        elif roe >= 5:  parts.append(5.0)
        else:           parts.append(3.0)
        reasons.append(f"weighted ROE {roe:.1f}%")

    if not parts:
        return None, "no look-through data"

    reasons.append(f"coverage {inp.lookthrough_coverage_pct:.0f}%")
    return sum(parts) / len(parts), " · ".join(reasons)


def _score_valuation(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    """Factor 5 — 10%. Stocks: PE vs sector median. MFs: TER."""
    asset = (inp.asset_type or "").lower()

    if asset in ("mutual_fund", "mf", "etf"):
        if inp.ter_pct is None:
            return None, "no TER"
        ter = inp.ter_pct
        if ter < 0.5:   return 10.0, f"TER {ter:.2f}% (very low)"
        if ter < 1.0:   return 8.0,  f"TER {ter:.2f}%"
        if ter < 1.5:   return 5.0,  f"TER {ter:.2f}%"
        if ter < 2.0:   return 3.0,  f"TER {ter:.2f}% (high)"
        return 1.0,                  f"TER {ter:.2f}% (very high)"

    if asset in ("stock", "equity"):
        if inp.pe_vs_sector_pct is None:
            return None, "no sector median PE"
        rel = inp.pe_vs_sector_pct
        if rel <= -30:  return 9.0, f"PE {rel:+.0f}% vs sector (undervalued)"
        if rel <= -10:  return 7.0, f"PE {rel:+.0f}% vs sector (cheap)"
        if rel <=  10:  return 5.0, f"PE {rel:+.0f}% vs sector (fair)"
        if rel <=  30:  return 3.0, f"PE {rel:+.0f}% vs sector (rich)"
        return 1.0,                 f"PE {rel:+.0f}% vs sector (very expensive)"

    return None, f"no valuation signal for {asset!r}"


def _score_alternatives(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    """Factor 6 — 10%. Presence of a clearly-better peer is a SELL signal.
    Inverts standard 'higher = better' — higher alpha_pp for alternative
    means LOWER keep-score (more reason to switch)."""
    if not inp.has_better_alternative:
        return 8.0, "no clearly better peer in same category"

    if inp.alternative_alpha_pp is None:
        return 5.0, "better peer present (alpha unknown)"

    a = inp.alternative_alpha_pp
    if a >= 5:    return 1.0, f"strong alternative +{a:.1f}pp better — switch"
    if a >= 3:    return 3.0, f"alternative +{a:.1f}pp better"
    if a >= 1.5:  return 5.0, f"alternative +{a:.1f}pp better (marginal)"
    return 7.0,               f"alternative +{a:.1f}pp better (sub-noise)"


def _score_concentration(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    """Factor 7 — 5%. Weight + pairwise overlap. Penalises duplicated
    exposure AND single-holding concentration."""
    w = inp.weight_pct
    ov = inp.overlap_pct_max or 0.0

    # Penalty for high overlap
    if ov >= 70:
        return 2.0, f"{ov:.0f}% overlap with another holding — duplicate exposure"
    if ov >= 50:
        return 4.0, f"{ov:.0f}% overlap — partial duplication"

    # Concentration scoring on weight
    if w >= 15:
        return 3.0, f"{w:.1f}% weight (very concentrated)"
    if w >= 8:
        return 6.0, f"{w:.1f}% weight (concentrated)"
    if w >= 2:
        return 9.0, f"{w:.1f}% weight (right-sized)"
    if w >= 0.5:
        return 7.0, f"{w:.1f}% weight (small)"
    return 5.0,    f"{w:.2f}% weight (negligible — clutter)"


def _score_governance(inp: ExitScoreInput) -> Tuple[Optional[float], str]:
    """Factor 8 — 5%. Promoter pledge + FII trend. Stocks only."""
    asset = (inp.asset_type or "").lower()
    if asset not in ("stock", "equity"):
        return None, f"no governance signal for {asset!r}"

    if inp.promoter_pledge_pct is None and inp.fii_pct_change_qoq is None:
        return None, "no shareholding signals"

    parts: List[float] = []
    reasons: List[str] = []

    if inp.promoter_pledge_pct is not None:
        p = inp.promoter_pledge_pct
        if p < 5:    parts.append(9.0); reasons.append(f"promoter pledge {p:.1f}% (low)")
        elif p < 15: parts.append(6.0); reasons.append(f"promoter pledge {p:.1f}%")
        elif p < 30: parts.append(3.0); reasons.append(f"promoter pledge {p:.1f}% (high)")
        else:        parts.append(1.0); reasons.append(f"promoter pledge {p:.1f}% (alarming)")

    if inp.fii_pct_change_qoq is not None:
        d = inp.fii_pct_change_qoq
        if d >= 1:    parts.append(8.0); reasons.append(f"FII +{d:.1f}pp QoQ")
        elif d >= 0:  parts.append(6.0); reasons.append(f"FII {d:+.1f}pp QoQ")
        elif d >= -1: parts.append(4.0); reasons.append(f"FII {d:+.1f}pp QoQ")
        else:         parts.append(2.0); reasons.append(f"FII {d:+.1f}pp QoQ (exiting)")

    return sum(parts) / len(parts), " · ".join(reasons)


# ── Composite ────────────────────────────────────────────────────────
def _weighted_composite(
    scores: Dict[str, Optional[float]],
) -> Tuple[Optional[float], Dict[str, float]]:
    """Combine the 8 factor scores into a 0-100 with weight redistribution.

    Reuses the V3 weighting pattern (services/v3_scoring.py:151):
      - Present factors keep their base weight in proportion;
      - Missing factors' weight is split across the rest.

    Returns (score_0_100, effective_weights_dict).
    """
    present = {k: v for k, v in scores.items() if v is not None}
    if not present:
        return None, {}

    total_base = sum(WEIGHTS[k] for k in present)
    if total_base == 0:
        return None, {}

    effective = {k: (WEIGHTS[k] / total_base) * 100.0 for k in present}
    score_0_10 = sum(scores[k] * effective[k] for k in present) / 100.0
    return round(score_0_10 * 10.0, 2), {k: round(w, 1) for k, w in effective.items()}


def _band_recommendation(score_100: float) -> str:
    for cutoff, label in RECOMMENDATION_BANDS:
        if score_100 >= cutoff:
            return label
    return "Exit Recommended"  # unreachable; last band covers 0


def _confidence(score_100: Optional[float]) -> str:
    """Per user spec:
      HIGH    score < 35 or > 85
      MEDIUM  35–55 or 70–85
      LOW     55–69
    """
    if score_100 is None:
        return "LOW"
    s = score_100
    if s > 85 or s < 35:    return "HIGH"
    if (35 <= s <= 55) or (70 <= s <= 85):  return "MEDIUM"
    return "LOW"


# ── Trigger overrides ────────────────────────────────────────────────
def _check_overrides(inp: ExitScoreInput) -> Optional[Tuple[str, str]]:
    """Return (recommendation, override_reason) if a trigger fires, else None.

    Order matters — Exit overrides win over Strong Hold to avoid a
    'top-quartile AND fraud-flag' contradiction landing on Strong Hold.
    """
    if inp.has_governance_red_flag:
        return "Exit Recommended", "governance red flag (fraud / auditor / regulatory)"
    if inp.thesis_clearly_broken:
        return "Exit Recommended", "investment thesis clearly broken"
    if inp.persistent_bottom_quartile_3y:
        return "Exit Recommended", "persistent bottom-quartile performance for 3+ years"

    if inp.top_quartile_long_term and inp.thesis_still_valid is not False:
        return "Strong Hold", "top-quartile performer with intact thesis"

    return None


# ── Top reasons surfacer ─────────────────────────────────────────────
def _top_reasons(
    breakdown: List[FactorContribution],
    recommendation: str,
    max_n: int = 3,
) -> List[str]:
    """Pick the 3 most decision-relevant factor reasons.

    Strategy:
      - For sell-side recommendations (Review / Trim / Switch / Exit):
        surface the LOWEST-scoring factors — the reasons to exit.
      - For Strong Hold / Hold:
        surface the HIGHEST-scoring factors — the reasons to keep.
    """
    present = [f for f in breakdown if f.raw_score_0_10 is not None]
    if not present:
        return []

    sell_side = recommendation not in ("Strong Hold", "Hold")
    present.sort(key=lambda f: f.raw_score_0_10, reverse=(not sell_side))
    return [f.reason for f in present[:max_n]]


# ── Main entry point ─────────────────────────────────────────────────
def score_holding(inp: ExitScoreInput) -> ExitScoreResult:
    """Score a single holding. Returns ExitScoreResult; never raises.

    Caller (analytics route) is responsible for assembling the input
    from NIDP feeds — this function is pure and deterministic."""
    # ── 1. Trigger overrides (skip score math when they fire) ──
    override = _check_overrides(inp)

    # ── 2. Compute each factor ──
    factors_data: List[Tuple[str, Optional[float], str]] = [
        ("portfolio_fit",  *_score_portfolio_fit(inp)),
        ("performance",    *_score_performance(inp)),
        ("risk_adj",       *_score_risk_adj(inp)),
        ("fundamentals",   *_score_fundamentals(inp)),
        ("valuation",      *_score_valuation(inp)),
        ("alternatives",   *_score_alternatives(inp)),
        ("concentration",  *_score_concentration(inp)),
        ("governance",     *_score_governance(inp)),
    ]

    raw_scores = {name: s for name, s, _ in factors_data}
    score_100, effective_weights = _weighted_composite(raw_scores)

    # ── 3. Build per-factor breakdown ──
    breakdown: List[FactorContribution] = []
    for name, raw, reason in factors_data:
        eff_w = effective_weights.get(name, 0.0)
        contribution = (raw * eff_w / 10.0) if raw is not None else 0.0
        breakdown.append(FactorContribution(
            name=name,
            raw_score_0_10=None if raw is None else round(raw, 2),
            effective_weight=eff_w,
            contribution=round(contribution, 2),
            reason=reason,
        ))

    missing_signals = [name for name, raw, _ in factors_data if raw is None]

    # ── 4. Recommendation + confidence ──
    if override is not None:
        recommendation, override_reason = override
        confidence = "HIGH"   # overrides are explicit signals
    elif score_100 is None:
        recommendation = "INSUFFICIENT_DATA"
        confidence = "LOW"
        override_reason = None
    else:
        recommendation = _band_recommendation(score_100)
        confidence = _confidence(score_100)
        override_reason = None

    # ── 5. Top reasons ──
    top_reasons = _top_reasons(breakdown, recommendation)
    if override is not None:
        # Prepend the override reason as the headline
        top_reasons = [override_reason] + top_reasons

    return ExitScoreResult(
        holding_id=inp.holding_id,
        name=inp.name,
        score=score_100,
        recommendation=recommendation,
        confidence=confidence,
        factor_breakdown=breakdown,
        top_reasons=top_reasons,
        missing_signals=missing_signals,
        override_triggered=override_reason,
    )
