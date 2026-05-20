"""Unit tests for fund_performance.enrich_with_alternatives — the contract
consumed by the Performance & Benchmark dashboard's Action Matrix
(inline alternative arrows on Review/Exit rows + aggregate uplift banner).

Covers the user-visible failure modes the dashboard must handle gracefully:

  1. Solo fund in a category → no peer → no alternative (UI hides arrow).
  2. All-equal returns → uplift falls below noise floor → no alternative.
  3. Missing return_1y → row is skipped (UI shows no fake uplift).
  4. Clear underperformer with strong peer → alternative attached with
     HIGH confidence and correct uplift_per_year_rs math.
  5. Marginal alpha (<1pp) → suppressed; noise floor enforced.
"""
import sys
import types

# Stub heavyweight transitive deps for in-process testing.
if "deps" not in sys.modules:
    sys.modules["deps"] = types.ModuleType("deps")
    sys.modules["deps"].db = None

from services.fund_performance import enrich_with_alternatives  # noqa: E402


def _rating(name: str, cat: str, ret_1y, rating="meeting", current_value: float = 100_000):
    return {
        "name": name,
        "scheme_category": cat,
        "return_1y": ret_1y,
        "rating": rating,
        "current_value": current_value,
        "scheme_code": name.lower().replace(" ", "_"),
    }


def test_solo_fund_in_category_no_alternative():
    """Only one fund in 'Mid Cap' — nothing to switch to."""
    ratings = [_rating("Solo Mid Cap Fund", "Mid Cap", 12.0)]
    enrich_with_alternatives(ratings)
    assert "alternative" not in ratings[0]


def test_all_equal_returns_no_alternative():
    """Two funds at exactly the same return — uplift is zero, must suppress."""
    ratings = [
        _rating("Fund A", "Flexi Cap", 10.0),
        _rating("Fund B", "Flexi Cap", 10.0),
    ]
    enrich_with_alternatives(ratings)
    assert "alternative" not in ratings[0]
    assert "alternative" not in ratings[1]


def test_missing_return_1y_row_skipped():
    """Holding without return_1y must not get a fabricated alternative."""
    ratings = [
        _rating("No-Data Fund", "Large Cap", None),
        _rating("Good Fund", "Large Cap", 15.0),
    ]
    enrich_with_alternatives(ratings)
    assert "alternative" not in ratings[0]


def test_underperformer_gets_high_confidence_alternative():
    """Strong peer in same category → alternative with HIGH confidence."""
    ratings = [
        _rating("Weak Flexi", "Flexi Cap", 6.0, rating="underperforming", current_value=200_000),
        _rating("Strong Flexi", "Flexi Cap", 18.0, rating="overperforming", current_value=300_000),
    ]
    enrich_with_alternatives(ratings)
    weak = ratings[0]
    assert "alternative" in weak
    alt = weak["alternative"]
    assert alt["name"] == "Strong Flexi"
    assert alt["confidence"] == "HIGH"
    # (18 − 6) * 200_000 * 1% = 24_000
    assert alt["uplift_per_year_rs"] == 24_000
    assert alt["alpha_pp"] == 12.0


def test_marginal_alpha_below_noise_floor_suppressed():
    """Peer is only 0.5pp better — below MIN_ALPHA_PP=1.0 noise floor."""
    ratings = [
        _rating("Fund A", "Small Cap", 14.0),
        _rating("Fund B", "Small Cap", 14.5),
    ]
    enrich_with_alternatives(ratings)
    assert "alternative" not in ratings[0]
    assert "alternative" not in ratings[1]


def test_confidence_ladders_down_when_alpha_small():
    """Peer is 1.5–3pp better → MEDIUM confidence, not HIGH."""
    ratings = [
        _rating("Fund A", "Large Cap", 12.0, rating="meeting"),
        _rating("Fund B", "Large Cap", 14.0, rating="meeting"),
    ]
    enrich_with_alternatives(ratings)
    alt = ratings[0]["alternative"]
    assert alt["confidence"] == "MEDIUM"
