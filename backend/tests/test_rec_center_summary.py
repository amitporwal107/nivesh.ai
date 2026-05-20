"""Unit tests for Recommendations Center aggregate summary.

Covers the Phase-A optimisation engine numbers exposed by
`_build_summary`: total_optimizable_rs, projected_wealth_gain_10y_rs,
current/target fund counts, diversification scores, and the per-insight
`benefit.optimizable_rs` produced by `_compute_benefit`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes.insights import (  # noqa: E402
    _build_summary, _compute_benefit, _enrich_insights,
)


def _mf(name, val):
    return {"asset_type": "mutual_fund", "name": name, "quantity": 1, "current_price": val}


def test_summary_returns_all_optimisation_keys():
    """Hero needs these keys even when there's nothing to optimise."""
    s = _build_summary([], set(), [])
    for k in (
        "total_optimizable_rs", "projected_wealth_gain_10y_rs",
        "current_fund_count", "target_fund_count",
        "diversification_score_current", "diversification_score_target",
        "potential_fee_savings_annual_rs", "duplicate_fund_count",
    ):
        assert k in s, f"missing key {k}"


def test_duplicate_insight_attaches_optimizable_rs_from_smaller_fund():
    """For an overlap pair, optimizable_rs = AUM of the smaller fund."""
    holdings = [_mf("Nippon Small Cap Regular", 800_000), _mf("Nippon Small Cap Direct", 500_000)]
    ins = [{
        "title": "Nippon Small Cap Regular and Nippon Small Cap Direct overlap 97%",
        "type": "warning", "impact": "high",
        "affected_funds": ["Nippon Small Cap Regular", "Nippon Small Cap Direct"],
    }]
    enriched = _enrich_insights(ins, holdings, sum(h["quantity"] * h["current_price"] for h in holdings))
    b = enriched[0]["benefit"]
    assert b["optimizable_rs"] == 500_000, "should equal smaller fund's AUM"
    assert b["funds_removed"] == 1
    # 50 bps annual fee saving on the freed AUM
    assert b["fee_savings_annual_rs"] == round(500_000 * 0.005)


def test_summary_aggregates_optimizable_across_multiple_duplicates():
    holdings = [
        _mf("Fund A Regular", 600_000), _mf("Fund A Direct", 400_000),
        _mf("Fund B Regular", 300_000), _mf("Fund B Direct", 200_000),
    ]
    ins = [
        {"title": "Fund A Regular and Fund A Direct overlap 95%", "type": "warning", "impact": "high",
         "affected_funds": ["Fund A Regular", "Fund A Direct"]},
        {"title": "Fund B Regular and Fund B Direct overlap 92%", "type": "warning", "impact": "high",
         "affected_funds": ["Fund B Regular", "Fund B Direct"]},
    ]
    total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
    enriched = _enrich_insights(ins, holdings, total_cur)
    s = _build_summary(enriched, set(), holdings)
    # Smaller of each pair = 400K + 200K = 600K
    assert s["total_optimizable_rs"] == 600_000
    # Fund counts: 4 → 2
    assert s["current_fund_count"] == 4
    assert s["target_fund_count"] == 2
    # Annual savings: 0.5% of (400K + 200K) = 3000
    assert s["potential_fee_savings_annual_rs"] == 3000
    # 10Y wealth gain from annuity of ₹3000 at 12%: ~₹52K
    assert 50_000 < s["projected_wealth_gain_10y_rs"] < 55_000


def test_diversification_target_never_drops_below_current():
    """When nothing can be removed, target should equal current."""
    holdings = [_mf("Single Fund", 1_000_000)]
    s = _build_summary([], set(), holdings)
    assert s["diversification_score_current"] == s["diversification_score_target"]


def test_summary_handles_no_holdings_gracefully():
    s = _build_summary([], set(), None)
    assert s["current_fund_count"] == 0
    assert s["target_fund_count"] == 0
    assert s["diversification_score_current"] is None
    assert s["projected_wealth_gain_10y_rs"] == 0.0
