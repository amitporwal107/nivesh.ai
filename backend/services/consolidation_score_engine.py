"""Consolidation Scoring Engine — pair-level decision for duplicate/overlap funds.

User spec (2026-05-20):

  8 pair-level factors → ConsolidationScore 0-100:
    Portfolio Overlap %          35%   common holdings between the two funds
    Relative Performance         20%   3Y/5Y rolling-return delta
    Risk-Adjusted Returns        10%   Sharpe / Sortino delta
    Expense Ratio                10%   TER delta (lower is better)
    Tax & Exit-Load Impact       10%   cost of switching one to the other
    Fund Manager Stability        5%   tenure
    AUM & Liquidity               5%   size
    Portfolio Role Fit            5%   strategy / category alignment

  Overlap-driven decision bands (applied BEFORE the 100-point score):
    < 30%        Keep Both              — different strategies, no redundancy
    30–50%       Review                  — moderate; both quality but redundant
    50–70%       Consider Consolidation  — significant overlap
    70–85%       Switch to One           — high duplication
    > 85%        Consolidate Immediately — near-duplicate

  Fund-selection (which to retain) — separate 100-point rubric on the
  6 quality dimensions per spec:
    Performance Consistency      30%
    Risk-Adjusted Returns        20%
    Portfolio Quality            15%
    Expense Ratio                15%
    Fund Manager Stability       10%
    Drawdown Control             10%

  Higher-scoring fund is retained; lower-scoring fund is the exit candidate.

Output JSON (per user spec):
  {
    "fund_pair":       ["Parag Parikh Flexi Cap", "HDFC Flexi Cap"],
    "overlap_pct":     78,
    "retain":          "Parag Parikh Flexi Cap",
    "exit":            "HDFC Flexi Cap",
    "recommendation":  "Consolidate",
    "confidence":      "HIGH",
    "potential_benefit": "Reduce duplication; lower TER by 0.4pp",
    "fund_scores":     {"A": 78, "B": 52},
    "missing_signals": [],
  }

Design tenets — same as exit_score_engine.py:
  - PURE. No DB / network. Caller assembles signals.
  - HONEST. Missing signals → None, redistributed. Never fabricated.
  - DETERMINISTIC. Same input → same output.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Overlap → decision bands (drive the headline recommendation) ─────
OVERLAP_BANDS: List[Tuple[float, str]] = [
    (85.0, "Consolidate Immediately"),
    (70.0, "Switch to One"),
    (50.0, "Consider Consolidation"),
    (30.0, "Review"),
    (0.0,  "Keep Both"),
]


# ── Fund-selection weights (used by pick_winner) ─────────────────────
SELECTION_WEIGHTS: Dict[str, float] = {
    "performance_consistency": 30.0,
    "risk_adj":                20.0,
    "portfolio_quality":       15.0,
    "expense_ratio":           15.0,
    "manager_stability":       10.0,
    "drawdown_control":        10.0,
}
assert abs(sum(SELECTION_WEIGHTS.values()) - 100.0) < 1e-9


# ── Dataclasses ──────────────────────────────────────────────────────
@dataclass
class FundSnapshot:
    """One fund's view of the signals consolidation needs.

    Caller assembles from NIDP (analytics.fund_category_rank +
    v_mf_lookthrough_quality + mf_scheme_disclosure_snapshot + tax_engine).
    """
    name: str
    scheme_code: Optional[str] = None
    current_value_rs: float = 0.0       # user's invested amount

    # Performance — for relative comparison + winner selection
    return_1y: Optional[float] = None
    return_3y: Optional[float] = None
    return_5y: Optional[float] = None
    return_1y_rank: Optional[int] = None   # within-category rank, 1 = best

    # Risk-adjusted
    sharpe_1y: Optional[float] = None
    sortino_1y: Optional[float] = None
    max_drawdown_1y_pct: Optional[float] = None

    # Cost
    ter_pct: Optional[float] = None

    # Look-through quality (only used when coverage >= 60%)
    lookthrough_piotroski: Optional[float] = None
    lookthrough_coverage_pct: Optional[float] = None

    # Stability metrics
    manager_tenure_years: Optional[float] = None
    aum_cr: Optional[float] = None

    # Tax / exit cost of selling THIS fund
    estimated_tax_impact_rs: Optional[float] = None
    exit_load_pct: Optional[float] = None

    # Categorical
    scheme_category: Optional[str] = None
    sub_category: Optional[str] = None


@dataclass
class ConsolidationInput:
    fund_a: FundSnapshot
    fund_b: FundSnapshot
    overlap_pct: float                  # pairwise holdings overlap (0-100)


@dataclass
class ConsolidationResult:
    fund_pair: Tuple[str, str]
    overlap_pct: float
    recommendation: str                 # one of OVERLAP_BANDS labels
    confidence: str                     # HIGH / MEDIUM / LOW
    retain: Optional[str]               # winning fund name (None if "Keep Both")
    exit: Optional[str]                 # losing fund name (None if "Keep Both")
    fund_scores: Dict[str, float]       # {"A": 78.0, "B": 52.0}
    potential_benefit: str              # human-readable
    missing_signals: List[str]
    role_fit_distinct: bool             # true when categories differ → forces Keep Both

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fund_pair":         list(self.fund_pair),
            "overlap_pct":       round(self.overlap_pct, 1),
            "recommendation":    self.recommendation,
            "confidence":        self.confidence,
            "retain":            self.retain,
            "exit":              self.exit,
            "fund_scores":       {k: round(v, 1) for k, v in self.fund_scores.items()},
            "potential_benefit": self.potential_benefit,
            "missing_signals":   list(self.missing_signals),
            "role_fit_distinct": self.role_fit_distinct,
        }


# ── Helpers ──────────────────────────────────────────────────────────
def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def _band_for_overlap(overlap_pct: float) -> str:
    for cutoff, label in OVERLAP_BANDS:
        if overlap_pct >= cutoff:
            return label
    return "Keep Both"


# ── Per-fund quality scoring (for pick_winner) ───────────────────────
def _score_performance_consistency(f: FundSnapshot) -> Tuple[Optional[float], str]:
    """3Y > 1Y consistency. Prefer funds with stable long-horizon returns."""
    # Use 3Y if available; fall back to 1Y
    r = f.return_3y if f.return_3y is not None else f.return_1y
    if r is None:
        return None, "no return data"

    if r >= 18:    return 10.0, f"3Y/1Y return {r:.1f}% (excellent)"
    if r >= 12:    return 8.0,  f"return {r:.1f}% (strong)"
    if r >= 8:     return 6.0,  f"return {r:.1f}% (ok)"
    if r >= 0:     return 4.0,  f"return {r:.1f}% (weak)"
    return 1.0,                 f"return {r:.1f}% (negative)"


def _score_risk_adj_pair(f: FundSnapshot) -> Tuple[Optional[float], str]:
    if f.sharpe_1y is None:
        return None, "no Sharpe"
    s = f.sharpe_1y
    if s >= 1.5:   return 10.0, f"Sharpe {s:.2f}"
    if s >= 1.0:   return 8.0,  f"Sharpe {s:.2f}"
    if s >= 0.5:   return 5.0,  f"Sharpe {s:.2f}"
    if s >= 0:     return 3.0,  f"Sharpe {s:.2f}"
    return 1.0,                 f"Sharpe {s:.2f} (negative)"


def _score_portfolio_quality(f: FundSnapshot) -> Tuple[Optional[float], str]:
    """Look-through Piotroski of constituent stocks."""
    if (
        f.lookthrough_coverage_pct is None
        or f.lookthrough_coverage_pct < 60
        or f.lookthrough_piotroski is None
    ):
        return None, "look-through unavailable (coverage < 60% or no Piotroski)"
    p = f.lookthrough_piotroski
    score = _clamp(p * (10.0 / 9.0))
    return score, f"lookthrough Piotroski {p:.1f}/9 ({f.lookthrough_coverage_pct:.0f}% cov)"


def _score_expense(f: FundSnapshot) -> Tuple[Optional[float], str]:
    if f.ter_pct is None:
        return None, "no TER"
    ter = f.ter_pct
    if ter < 0.5:   return 10.0, f"TER {ter:.2f}%"
    if ter < 1.0:   return 8.0,  f"TER {ter:.2f}%"
    if ter < 1.5:   return 5.0,  f"TER {ter:.2f}%"
    if ter < 2.0:   return 3.0,  f"TER {ter:.2f}%"
    return 1.0,                  f"TER {ter:.2f}% (high)"


def _score_manager_stability(f: FundSnapshot) -> Tuple[Optional[float], str]:
    if f.manager_tenure_years is None:
        return None, "no manager tenure"
    t = f.manager_tenure_years
    if t >= 7:     return 10.0, f"manager tenure {t:.1f}y"
    if t >= 4:     return 7.0,  f"manager tenure {t:.1f}y"
    if t >= 2:     return 5.0,  f"manager tenure {t:.1f}y"
    return 2.0,                 f"manager tenure {t:.1f}y (short)"


def _score_drawdown_control(f: FundSnapshot) -> Tuple[Optional[float], str]:
    if f.max_drawdown_1y_pct is None:
        return None, "no drawdown data"
    dd = f.max_drawdown_1y_pct
    if dd >= -10:   return 10.0, f"max DD {dd:.1f}%"
    if dd >= -20:   return 7.0,  f"max DD {dd:.1f}%"
    if dd >= -30:   return 5.0,  f"max DD {dd:.1f}%"
    if dd >= -40:   return 2.0,  f"max DD {dd:.1f}%"
    return 1.0,                  f"max DD {dd:.1f}% (severe)"


def _fund_quality_score(f: FundSnapshot) -> Tuple[Optional[float], Dict[str, Any]]:
    """Compose the 6-factor quality score for one fund. Returns
    (score_0_100, breakdown). Score is None when no signals at all.
    """
    factors = [
        ("performance_consistency", *_score_performance_consistency(f)),
        ("risk_adj",                *_score_risk_adj_pair(f)),
        ("portfolio_quality",       *_score_portfolio_quality(f)),
        ("expense_ratio",           *_score_expense(f)),
        ("manager_stability",       *_score_manager_stability(f)),
        ("drawdown_control",        *_score_drawdown_control(f)),
    ]
    raw = {name: s for name, s, _ in factors}
    present = {k: v for k, v in raw.items() if v is not None}
    if not present:
        return None, {"factors": factors, "missing": [n for n, s, _ in factors if s is None]}

    total_base = sum(SELECTION_WEIGHTS[k] for k in present)
    eff = {k: (SELECTION_WEIGHTS[k] / total_base) * 100.0 for k in present}
    score_0_10 = sum(raw[k] * eff[k] for k in present) / 100.0

    return round(score_0_10 * 10.0, 2), {
        "factors": factors,
        "missing": [n for n, s, _ in factors if s is None],
        "effective_weights": eff,
    }


# ── Tax-aware recommendation modifier ────────────────────────────────
def _tax_modifier(loser: FundSnapshot) -> Optional[str]:
    """When the candidate-to-exit has material tax + exit load, hint
    that staggering or waiting is preferable to immediate exit."""
    tax = loser.estimated_tax_impact_rs or 0.0
    el = loser.exit_load_pct or 0.0
    if tax > 0 and tax >= 0.02 * (loser.current_value_rs or 0):  # >2% of capital
        return f"meaningful tax (~₹{int(tax):,}) — stagger over 2 financial years"
    if el >= 1.0:
        return f"{el:.1f}% exit load — wait until load period ends"
    return None


# ── Main entry point ─────────────────────────────────────────────────
def score_pair(inp: ConsolidationInput) -> ConsolidationResult:
    """Decide what to do about a fund pair. Returns ConsolidationResult;
    never raises. Pure function — caller assembles signals."""
    a, b = inp.fund_a, inp.fund_b
    overlap = inp.overlap_pct

    # ── 1. Role-fit check — if categories clearly differ AND overlap
    # is below the "Switch to One" threshold, Keep Both regardless of
    # other factors. Two different-strategy funds with mild overlap is
    # legitimate diversification.
    cats_distinct = (
        a.scheme_category is not None
        and b.scheme_category is not None
        and a.scheme_category != b.scheme_category
    )
    if cats_distinct and overlap < 70:
        return ConsolidationResult(
            fund_pair=(a.name, b.name),
            overlap_pct=overlap,
            recommendation="Keep Both",
            confidence="HIGH",
            retain=None,
            exit=None,
            fund_scores={"A": 0.0, "B": 0.0},
            potential_benefit=f"Different categories ({a.scheme_category} vs {b.scheme_category}) — distinct roles",
            missing_signals=[],
            role_fit_distinct=True,
        )

    # ── 2. Overlap-driven headline band ──
    headline = _band_for_overlap(overlap)

    # ── 3. Per-fund quality scores → pick winner ──
    score_a, detail_a = _fund_quality_score(a)
    score_b, detail_b = _fund_quality_score(b)

    fund_scores: Dict[str, float] = {}
    if score_a is not None:
        fund_scores["A"] = score_a
    if score_b is not None:
        fund_scores["B"] = score_b

    # Aggregate missing signals across both funds
    missing = sorted(set(detail_a.get("missing", []) + detail_b.get("missing", [])))

    # Decide retain/exit
    retain_name: Optional[str] = None
    exit_name: Optional[str] = None
    score_gap: float = 0.0

    if headline == "Keep Both":
        # No exit candidate when overlap is low.
        retain_name, exit_name = None, None
    elif score_a is None and score_b is None:
        # Can't pick a winner — downgrade to Review
        headline = "Review"
        retain_name, exit_name = None, None
    elif score_a is None:
        retain_name, exit_name = b.name, a.name
    elif score_b is None:
        retain_name, exit_name = a.name, b.name
    else:
        score_gap = abs(score_a - score_b)
        if score_a >= score_b:
            retain_name, exit_name = a.name, b.name
        else:
            retain_name, exit_name = b.name, a.name

    # ── 4. Tax-aware modifier on the headline ──
    loser = (b if retain_name == a.name else a) if exit_name else None
    tax_hint = _tax_modifier(loser) if loser else None

    # ── 5. Confidence ──
    # HIGH when overlap is extreme (>= 85 or < 30) AND we have a clear winner
    # MEDIUM when overlap is mid (50-85) with a clear winner
    # LOW when score_gap is small (<10) OR signals largely missing
    if headline == "Keep Both":
        confidence = "HIGH"
    elif headline == "Consolidate Immediately":
        confidence = "HIGH" if (retain_name is not None and score_gap >= 10) else "MEDIUM"
    elif headline in ("Switch to One", "Consider Consolidation"):
        if retain_name is None or score_gap < 5:
            confidence = "LOW"
        elif score_gap >= 15:
            confidence = "HIGH"
        else:
            confidence = "MEDIUM"
    else:  # Review
        confidence = "LOW"

    # ── 6. Human-readable benefit ──
    parts: List[str] = []
    if exit_name and retain_name:
        parts.append(f"Consolidate ₹{int(loser.current_value_rs):,} into {retain_name}")
    if a.ter_pct is not None and b.ter_pct is not None:
        ter_a, ter_b = a.ter_pct, b.ter_pct
        # User saves the higher TER
        ter_save = abs(ter_a - ter_b)
        if ter_save >= 0.1:
            parts.append(f"save {ter_save:.2f}pp/yr on TER")
    if tax_hint:
        parts.append(tax_hint)

    if not parts:
        parts = ["reduce duplication; simplify portfolio"]
    benefit = "; ".join(parts)

    return ConsolidationResult(
        fund_pair=(a.name, b.name),
        overlap_pct=overlap,
        recommendation=headline,
        confidence=confidence,
        retain=retain_name,
        exit=exit_name,
        fund_scores=fund_scores,
        potential_benefit=benefit,
        missing_signals=missing,
        role_fit_distinct=cats_distinct,
    )


# ── Convenience: rank multiple pairs by impact ───────────────────────
def rank_pairs(
    pairs: List[ConsolidationInput],
) -> List[ConsolidationResult]:
    """Score every pair, then sort high-impact first.

    Sort key: (1) overlap_pct desc — higher overlap is more actionable,
              (2) ₹ at stake (sum of both funds' current_value) desc.
    Pairs with recommendation "Keep Both" sink to the bottom.
    """
    scored = [score_pair(p) for p in pairs]

    def _impact(r: ConsolidationResult) -> Tuple[int, float, float]:
        # Tuple: (keep_both_flag, -overlap, -capital). Sort ascending →
        # lower tuples first → Keep-Both pairs sink, high-overlap rises.
        keep_both = 1 if r.recommendation == "Keep Both" else 0
        return (keep_both, -r.overlap_pct, 0.0)

    scored.sort(key=_impact)
    return scored
