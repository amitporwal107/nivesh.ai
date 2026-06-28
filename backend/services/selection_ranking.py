"""Selection ranking — pure ordering of an MF candidate pool (no DB, no network).

This is the rank-wiring layer the builder (services.sleeve_builder) should call BEFORE
handing a shortlist to services.selection (gates / overlap / capacity). It fixes the
documented defect where the builder ranks on point-to-point ``quality_score``:

PRD golden rule #1 (docs/Nivesh_Selection_Framework.md): *never rank on trailing
point-to-point returns* — score peer-relative. So ``rank_value`` prefers the CORRECTED
category-rank percentile (peer-relative, rolling-derived upstream) and only falls back
to ``quality_score`` when no category rank is present.

PRD A4 (index/passive override): an index/passive fund is scored on
``f(tracking_error ↓, expense_ratio ↓, AUM adequacy, fund age)`` with **all
active-return factors dropped**. ``index_passive_score`` / ``rank_passive`` implement
that override.

Everything here is a PURE function over plain dicts: no DB, no network, fully
unit-testable. Like services.selection, a missing field is never silently treated as a
good value — a factor whose field is absent is simply OMITTED from the blend (and the
blend renormalizes over the factors that are present), so absence neither helps nor
hurts a fund. Higher returned score = better; sorts are best-first and STABLE.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_MISSING = object()  # sentinel: field absent / non-numeric on the candidate

# Category-rank fields, in preference order. Both are 0..100 percentiles where
# HIGHER = better (100 = best in peer group), matching the upstream
# mf_category_rank_daily convention (see services.fund_performance).
_CATEGORY_RANK_FIELDS = ("category_pct", "category_rank_pct")

# ── Index / passive override (PRD A4) ────────────────────────────────────────────
# Each blend factor: (candidate fields tried in order, direction, normalizer).
# direction "high" -> bigger raw value is better; "low" -> smaller raw value is
# better. Every factor is mapped to a 0..100 sub-score; the composite is the mean
# of ONLY the factors whose field is present (missing factors are omitted, not
# scored 0 — absence must not silently penalize, per CONTEXT.md honesty rules).
#
# NOTE: there is deliberately NO active-return factor here (no return_vs_category,
# no point-to-point return, no quality_score) — PRD A4 drops active factors entirely
# for passive funds.
_PASSIVE_TE_FULL_SCALE_PCT = 1.0      # tracking error >= 1.0% (annualized) scores 0
_PASSIVE_ER_FULL_SCALE_PCT = 1.0      # expense ratio >= 1.0% scores 0
_PASSIVE_AUM_ADEQUATE_CR = 1000.0     # AUM at/above this is fully adequate (-> 100)
_PASSIVE_AGE_MATURE_YEARS = 5.0       # fund age at/above this is fully mature (-> 100)


def _num(cand: Dict[str, Any], *keys: str) -> Any:
    """First present, non-None, numeric field among ``keys``, else ``_MISSING``."""
    for k in keys:
        v = cand.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return _MISSING


def _clamp01x100(x: float) -> float:
    """Clamp to the 0..100 band."""
    if x < 0.0:
        return 0.0
    if x > 100.0:
        return 100.0
    return x


# ── Active / default ranking (PRD golden rule #1) ─────────────────────────────────
def rank_value(cand: Dict[str, Any]) -> float:
    """Ranking key for one candidate, best = highest.

    Prefers the CORRECTED, peer-relative category-rank percentile (``category_pct``
    then ``category_rank_pct``; both 0..100, higher = better). Only when NEITHER is
    present does it fall back to point-to-point ``quality_score`` — the legacy field
    whose use is the documented defect this module fixes. A candidate with no usable
    ranking field sorts last (returns ``-inf``); it is never treated as a good fund.
    """
    cat = _num(cand, *_CATEGORY_RANK_FIELDS)
    if cat is not _MISSING:
        return cat
    q = _num(cand, "quality_score")
    if q is not _MISSING:
        return q
    return float("-inf")


def rank_candidates(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return candidates sorted best-first by ``rank_value``, STABLY.

    Stable: candidates that tie on the ranking key keep their input order (Python's
    ``sorted`` is stable, and we sort by the negated key only). This is the active /
    default order — use ``rank_passive`` for an index/passive sub-bucket.
    """
    return sorted(cands, key=lambda c: -rank_value(c))


# ── Index / passive detection + override (PRD A4) ─────────────────────────────────
def is_passive(sub_category: Optional[str]) -> bool:
    """True for an index / passive sub-category (name contains 'index' or 'passive')."""
    s = str(sub_category or "").lower()
    return "index" in s or "passive" in s


def index_passive_score(cand: Dict[str, Any]) -> float:
    """PRD A4 passive override score in 0..100 (higher = better).

    Composite of: tracking_error (LOWER better), expense_ratio (LOWER better), AUM
    adequacy (HIGHER better, capped) and fund age (HIGHER better, capped). ALL
    active-return factors are dropped — there is no return / quality_score term here.

    Each factor present on the candidate contributes a 0..100 sub-score; the result is
    the MEAN of only the present factors. A factor whose field is absent is OMITTED
    (renormalized away) — missing data neither helps nor hurts the fund, matching the
    "never silent-pass on missing data" honesty rule. With no factors present at all,
    returns 0.0.
    """
    subs: List[float] = []

    # tracking error: 0% -> 100, full-scale -> 0 (lower is better)
    te = _num(cand, "tracking_error", "tracking_error_pct", "te")
    if te is not _MISSING:
        subs.append(_clamp01x100(100.0 * (1.0 - te / _PASSIVE_TE_FULL_SCALE_PCT)))

    # expense ratio: 0% -> 100, full-scale -> 0 (lower is better). Prefer the direct
    # plan's expense ratio when present (that is what we actually buy).
    er = _num(cand, "expense_ratio_direct", "expense_ratio", "ter")
    if er is not _MISSING:
        subs.append(_clamp01x100(100.0 * (1.0 - er / _PASSIVE_ER_FULL_SCALE_PCT)))

    # AUM adequacy: linear up to the adequacy threshold, then 100 (higher is better).
    aum = _num(cand, "aum_cr", "aum")
    if aum is not _MISSING:
        subs.append(_clamp01x100(100.0 * (aum / _PASSIVE_AUM_ADEQUATE_CR)))

    # fund age: linear up to maturity, then 100 (higher is better).
    age = _num(cand, "fund_age_years", "inception_age_years", "age_years")
    if age is not _MISSING:
        subs.append(_clamp01x100(100.0 * (age / _PASSIVE_AGE_MATURE_YEARS)))

    if not subs:
        return 0.0
    return sum(subs) / len(subs)


def rank_passive(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return passive/index candidates sorted best-first by ``index_passive_score``.

    STABLE on ties (preserves input order). Use this for an index/passive sub-bucket
    instead of ``rank_candidates`` so active-return factors are excluded (PRD A4).
    """
    return sorted(cands, key=lambda c: -index_passive_score(c))
