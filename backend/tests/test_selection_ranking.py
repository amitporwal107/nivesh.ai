"""Unit tests for services.selection_ranking — pure ranking, no DB, no network.

Teeth/negative fixtures throughout: the corrected peer-relative category rank must
beat the legacy point-to-point quality_score (PRD golden rule #1), and the passive
override must ignore active-return factors and rank on cost/tracking-error (PRD A4).
"""
import pytest

from services import selection_ranking as sr


# ── rank_value: corrected category rank beats legacy quality_score ────────────────
def test_rank_value_prefers_category_pct_over_quality_score():
    # High category percentile, LOW quality_score. The corrected field must win, so
    # rank_value reflects the percentile, NOT the point-to-point quality_score.
    cand = {"category_pct": 92, "quality_score": 40}
    assert sr.rank_value(cand) == pytest.approx(92)


def test_rank_value_prefers_category_rank_pct_when_pct_absent():
    cand = {"category_rank_pct": 80, "quality_score": 10}
    assert sr.rank_value(cand) == pytest.approx(80)


def test_rank_value_falls_back_to_quality_score_when_no_category_rank():
    cand = {"quality_score": 73}
    assert sr.rank_value(cand) == pytest.approx(73)


def test_rank_value_no_usable_field_sorts_last():
    assert sr.rank_value({"scheme_name": "Mystery Fund"}) == float("-inf")


def test_rank_value_category_pct_zero_is_used_not_treated_as_missing():
    # A genuine bottom-of-peer-group 0 percentile must NOT fall through to
    # quality_score — 0 is real data, only None/absent is "missing".
    cand = {"category_pct": 0, "quality_score": 99}
    assert sr.rank_value(cand) == pytest.approx(0)


# ── rank_candidates: corrected rank reorders vs point-to-point, stable on ties ────
def test_rank_candidates_corrected_rank_outranks_high_quality_score():
    # HIGH_PCT has a weak point-to-point quality_score but a strong PEER-RELATIVE
    # percentile; HIGH_Q has the reverse. The corrected ranker must put HIGH_PCT first
    # — the whole point of the fix (golden rule #1: stop chasing point-to-point).
    high_pct = {"isin": "HIGH_PCT", "category_pct": 90, "quality_score": 30}
    high_q = {"isin": "HIGH_Q", "category_pct": 20, "quality_score": 95}
    ordered = sr.rank_candidates([high_q, high_pct])
    assert [c["isin"] for c in ordered] == ["HIGH_PCT", "HIGH_Q"]


def test_rank_candidates_stable_on_ties():
    a = {"isin": "A", "category_pct": 50}
    b = {"isin": "B", "category_pct": 50}
    c = {"isin": "C", "category_pct": 50}
    ordered = sr.rank_candidates([a, b, c])
    assert [x["isin"] for x in ordered] == ["A", "B", "C"]  # input order preserved


def test_rank_candidates_mixed_fields_orders_by_resolved_key():
    cands = [
        {"isin": "Q", "quality_score": 60},       # fallback -> 60
        {"isin": "P", "category_pct": 85},        # corrected -> 85
        {"isin": "R", "category_rank_pct": 70},   # corrected -> 70
    ]
    assert [c["isin"] for c in sr.rank_candidates(cands)] == ["P", "R", "Q"]


# ── is_passive detection ──────────────────────────────────────────────────────────
def test_is_passive_detects_index_and_passive():
    assert sr.is_passive("Index Funds") is True
    assert sr.is_passive("Passive ETF") is True
    assert sr.is_passive("NIFTY 50 INDEX") is True
    assert sr.is_passive("Flexi Cap Fund") is False
    assert sr.is_passive(None) is False


# ── index_passive_score / rank_passive: PRD A4 override ───────────────────────────
def test_passive_score_lower_expense_scores_higher():
    cheap = {"expense_ratio": 0.10}
    pricey = {"expense_ratio": 0.80}
    assert sr.index_passive_score(cheap) > sr.index_passive_score(pricey)


def test_passive_score_lower_tracking_error_scores_higher():
    tight = {"tracking_error": 0.05}
    loose = {"tracking_error": 0.50}
    assert sr.index_passive_score(tight) > sr.index_passive_score(loose)


def test_passive_override_ignores_return_factors():
    # TEETH: a high-return, HIGH-EXPENSE index fund must LOSE to a low-expense one,
    # even though it carries a fat quality_score / return_vs_category. PRD A4 drops
    # all active-return factors, so those fields must not influence the passive score.
    fat_return_expensive = {
        "isin": "EXPENSIVE", "expense_ratio": 0.90, "tracking_error": 0.40,
        "quality_score": 99, "return_vs_category": 99, "return_3y": 25,
    }
    cheap_tight = {
        "isin": "CHEAP", "expense_ratio": 0.05, "tracking_error": 0.02,
        "quality_score": 10, "return_vs_category": 1, "return_3y": 1,
    }
    ordered = sr.rank_passive([fat_return_expensive, cheap_tight])
    assert [c["isin"] for c in ordered] == ["CHEAP", "EXPENSIVE"]
    # And prove the return fields are inert: stripping them changes nothing.
    stripped = {k: v for k, v in fat_return_expensive.items()
                if k not in ("quality_score", "return_vs_category", "return_3y")}
    assert sr.index_passive_score(stripped) == pytest.approx(
        sr.index_passive_score(fat_return_expensive))


def test_passive_score_missing_factor_omitted_not_zero():
    # A fund missing tracking_error is scored on the factors it DOES have; it is not
    # penalized to 0 for the absent factor. Two identical funds, one without TE, must
    # not have the TE-less one scored worse purely for the absence.
    with_te = {"expense_ratio": 0.10, "tracking_error": 0.05, "aum_cr": 1000, "fund_age_years": 5}
    without_te = {"expense_ratio": 0.10, "aum_cr": 1000, "fund_age_years": 5}
    # with_te has a near-100 TE sub-score; absent TE just drops the term, so the
    # remaining mean (all near-100) stays high — the TE-less fund is not crushed.
    assert sr.index_passive_score(without_te) > 90
    assert sr.index_passive_score(with_te) > 90


def test_passive_score_empty_candidate_is_zero():
    assert sr.index_passive_score({"isin": "EMPTY"}) == 0.0


def test_passive_score_bounded_0_100():
    # Out-of-band inputs (huge AUM, negative-ish) must clamp into 0..100.
    huge = {"expense_ratio": 0.0, "tracking_error": 0.0, "aum_cr": 1_000_000, "fund_age_years": 50}
    s = sr.index_passive_score(huge)
    assert 0.0 <= s <= 100.0
    assert s == pytest.approx(100.0)
    bad = {"expense_ratio": 5.0, "tracking_error": 5.0}  # both far past full-scale
    s2 = sr.index_passive_score(bad)
    assert s2 == pytest.approx(0.0)


def test_rank_passive_stable_on_ties():
    a = {"isin": "A", "expense_ratio": 0.20}
    b = {"isin": "B", "expense_ratio": 0.20}
    ordered = sr.rank_passive([a, b])
    assert [x["isin"] for x in ordered] == ["A", "B"]
