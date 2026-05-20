"""Unit tests for services.consolidation_score_engine.

Covers each overlap band, the role-fit-distinct override, the
fund-selection winner logic, tax-aware hints, and rank_pairs ordering.
Failure modes:

  1. Overlap < 30% → Keep Both (any other signal ignored).
  2. Overlap in each band → recommendation matches spec.
  3. Different categories → Keep Both (when overlap < 70).
  4. Both funds missing all quality signals → Review (can't pick winner).
  5. One fund missing all signals → the other auto-wins.
  6. Material tax → tax modifier appears in benefit.
  7. Material exit load → exit-load modifier in benefit.
  8. JSON round-trip exposes all spec'd keys.
  9. rank_pairs puts Keep-Both at the bottom.
"""
from __future__ import annotations

from services.consolidation_score_engine import (
    ConsolidationInput,
    ConsolidationResult,
    FundSnapshot,
    OVERLAP_BANDS,
    rank_pairs,
    score_pair,
)


def _strong_fund(**overrides) -> FundSnapshot:
    base = dict(
        name="Parag Parikh Flexi Cap",
        scheme_code="122639",
        current_value_rs=200_000,
        return_1y=18.0, return_3y=22.0, return_5y=19.0,
        sharpe_1y=1.5, sortino_1y=2.0,
        max_drawdown_1y_pct=-12.0,
        ter_pct=0.65,
        lookthrough_piotroski=6.5,
        lookthrough_coverage_pct=78.0,
        manager_tenure_years=8.5,
        aum_cr=12000.0,
        estimated_tax_impact_rs=500.0,
        exit_load_pct=0.0,
        scheme_category="Flexi Cap",
    )
    base.update(overrides)
    return FundSnapshot(**base)


def _weak_fund(**overrides) -> FundSnapshot:
    base = dict(
        name="HDFC Flexi Cap",
        scheme_code="118989",
        current_value_rs=150_000,
        return_1y=11.0, return_3y=13.0, return_5y=11.5,
        sharpe_1y=0.7, sortino_1y=0.9,
        max_drawdown_1y_pct=-22.0,
        ter_pct=1.45,
        lookthrough_piotroski=4.5,
        lookthrough_coverage_pct=72.0,
        manager_tenure_years=2.0,
        aum_cr=18000.0,
        estimated_tax_impact_rs=300.0,
        exit_load_pct=0.0,
        scheme_category="Flexi Cap",
    )
    base.update(overrides)
    return FundSnapshot(**base)


# ── 1. Overlap-band → recommendation mapping ─────────────────────────
def test_overlap_below_30_keeps_both():
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=15.0,
    ))
    assert r.recommendation == "Keep Both"
    assert r.retain is None
    assert r.exit is None


def test_overlap_30_50_is_review():
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=42.0,
    ))
    assert r.recommendation == "Review"


def test_overlap_50_70_is_consider_consolidation():
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=60.0,
    ))
    assert r.recommendation == "Consider Consolidation"
    # And we should be able to pick a winner now
    assert r.retain == "Parag Parikh Flexi Cap"
    assert r.exit == "HDFC Flexi Cap"


def test_overlap_70_85_is_switch_to_one():
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=78.0,
    ))
    assert r.recommendation == "Switch to One"
    assert r.retain == "Parag Parikh Flexi Cap"
    assert r.exit == "HDFC Flexi Cap"


def test_overlap_above_85_is_consolidate_immediately():
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=92.0,
    ))
    assert r.recommendation == "Consolidate Immediately"
    assert r.confidence == "HIGH"


# ── 2. Distinct-category override ────────────────────────────────────
def test_distinct_categories_force_keep_both_at_mid_overlap():
    """Two funds in different categories with overlap 50% should NOT
    be consolidated — they serve distinct roles."""
    a = _strong_fund(scheme_category="Large Cap")
    b = _weak_fund(scheme_category="Mid Cap")
    r = score_pair(ConsolidationInput(fund_a=a, fund_b=b, overlap_pct=55.0))
    assert r.recommendation == "Keep Both"
    assert r.role_fit_distinct is True
    assert "different categories" in r.potential_benefit.lower() or \
           "distinct roles" in r.potential_benefit.lower()


def test_distinct_categories_with_high_overlap_still_consolidates():
    """If overlap >= 70% the category distinction is moot — they're
    effectively the same exposure regardless of label."""
    a = _strong_fund(scheme_category="Large Cap")
    b = _weak_fund(scheme_category="Mid Cap")
    r = score_pair(ConsolidationInput(fund_a=a, fund_b=b, overlap_pct=80.0))
    assert r.recommendation == "Switch to One"


# ── 3. Winner selection ──────────────────────────────────────────────
def test_winner_is_higher_quality_fund():
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=75.0,
    ))
    assert r.retain == _strong_fund().name
    assert r.exit == _weak_fund().name
    assert r.fund_scores["A"] > r.fund_scores["B"]


def test_winner_picks_fund_b_when_better():
    """Swap which side has the better signals — winner must follow."""
    r = score_pair(ConsolidationInput(
        fund_a=_weak_fund(), fund_b=_strong_fund(), overlap_pct=75.0,
    ))
    assert r.retain == _strong_fund().name


def test_one_fund_missing_all_signals_other_wins():
    bare = FundSnapshot(name="Mystery Fund", scheme_category="Flexi Cap")
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=bare, overlap_pct=75.0,
    ))
    assert r.retain == _strong_fund().name
    assert r.exit == "Mystery Fund"


def test_both_funds_missing_all_signals_downgrades_to_review():
    bare_a = FundSnapshot(name="A", scheme_category="Flexi Cap")
    bare_b = FundSnapshot(name="B", scheme_category="Flexi Cap")
    r = score_pair(ConsolidationInput(
        fund_a=bare_a, fund_b=bare_b, overlap_pct=75.0,
    ))
    # Even though overlap is 75% (would normally be Switch to One),
    # we can't pick a winner, so downgrade to Review with LOW confidence.
    assert r.recommendation == "Review"
    assert r.confidence == "LOW"
    assert r.retain is None and r.exit is None


# ── 4. Tax-aware modifier ────────────────────────────────────────────
def test_material_tax_appears_in_benefit():
    """When the loser's exit cost > 2% of capital, the benefit text
    should mention staggering the exit."""
    expensive_to_exit = _weak_fund(
        estimated_tax_impact_rs=8000.0,    # 5.3% of 150k → above 2% threshold
    )
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=expensive_to_exit, overlap_pct=80.0,
    ))
    assert "stagger" in r.potential_benefit.lower() \
        or "tax" in r.potential_benefit.lower(), \
        f"expected tax hint in benefit, got: {r.potential_benefit}"


def test_exit_load_appears_in_benefit():
    """Material exit load → wait-out hint."""
    loaded = _weak_fund(exit_load_pct=1.5)
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=loaded, overlap_pct=80.0,
    ))
    assert "exit load" in r.potential_benefit.lower() \
        or "wait" in r.potential_benefit.lower(), \
        f"expected exit-load hint, got: {r.potential_benefit}"


# ── 5. Confidence ladder ─────────────────────────────────────────────
def test_extreme_overlap_with_clear_winner_is_high_confidence():
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=90.0,
    ))
    assert r.confidence == "HIGH"


def test_low_overlap_keep_both_is_high_confidence():
    """Keep-Both with low overlap is decisively correct."""
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=15.0,
    ))
    assert r.confidence == "HIGH"


def test_close_scores_in_mid_overlap_lowers_confidence():
    """When the two funds are quality-equivalent in a mid-overlap band,
    we shouldn't be high-confidence about which to exit."""
    twin_a = _strong_fund(name="A", return_1y=15.0, sharpe_1y=1.2, ter_pct=0.9)
    twin_b = _strong_fund(name="B", return_1y=15.5, sharpe_1y=1.21, ter_pct=0.9)
    r = score_pair(ConsolidationInput(
        fund_a=twin_a, fund_b=twin_b, overlap_pct=60.0,
    ))
    assert r.confidence in ("LOW", "MEDIUM")


# ── 6. JSON round-trip ───────────────────────────────────────────────
def test_to_dict_has_all_spec_keys():
    r = score_pair(ConsolidationInput(
        fund_a=_strong_fund(), fund_b=_weak_fund(), overlap_pct=78.0,
    ))
    d = r.to_dict()
    expected = {
        "fund_pair", "overlap_pct", "recommendation", "confidence",
        "retain", "exit", "fund_scores", "potential_benefit",
        "missing_signals", "role_fit_distinct",
    }
    assert expected.issubset(d.keys()), f"missing keys: {expected - d.keys()}"
    assert d["overlap_pct"] == 78.0


# ── 7. rank_pairs ordering ───────────────────────────────────────────
def test_rank_pairs_puts_high_overlap_first():
    """Critical: the operator-facing list of pairs to triage must order
    high-impact pairs (high overlap) before low-impact ones."""
    pairs = [
        ConsolidationInput(_strong_fund(name="P"), _weak_fund(name="Q"), 20.0),
        ConsolidationInput(_strong_fund(name="R"), _weak_fund(name="S"), 80.0),
        ConsolidationInput(_strong_fund(name="T"), _weak_fund(name="U"), 55.0),
    ]
    results = rank_pairs(pairs)
    overlaps = [r.overlap_pct for r in results]
    # Keep-Both pair (20%) must be last
    assert overlaps[-1] == 20.0
    # High-overlap (80%) must be first
    assert overlaps[0] == 80.0


# ── 8. OVERLAP_BANDS contract — must match the user's spec ───────────
def test_overlap_bands_match_spec():
    """Locked numerical bands from the user's spec. Changing them is
    a product decision, not a refactor — this test makes that explicit."""
    bands = dict(OVERLAP_BANDS)
    assert 85.0 in bands and bands[85.0] == "Consolidate Immediately"
    assert 70.0 in bands and bands[70.0] == "Switch to One"
    assert 50.0 in bands and bands[50.0] == "Consider Consolidation"
    assert 30.0 in bands and bands[30.0] == "Review"
    assert 0.0  in bands and bands[0.0]  == "Keep Both"
