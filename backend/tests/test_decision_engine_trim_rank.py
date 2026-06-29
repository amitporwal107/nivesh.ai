"""Unit tests for the composite trim-ranking in decision_engine_actions.

Covers the pure ordering/reason logic (no DB / no async): given per-fund
signals, the engine must trim the *worst* holding first and explain *why*.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.decision_engine_actions import (  # noqa: E402
    _composite_trim_order,
    _trim_reason_suffix,
    _minmax_norm,
)


def _h(name, value, **sig):
    return {"name": name, "value": value, "bucket": "equity", **sig}


def test_minmax_flat_is_zero():
    assert _minmax_norm([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]
    assert _minmax_norm([0.0, 10.0]) == [0.0, 1.0]


def test_no_signals_falls_back_to_size_order():
    cands = [_h("Small", 1_00_000), _h("Big", 5_00_000), _h("Mid", 3_00_000)]
    out = _composite_trim_order(cands)
    assert [c["name"] for c in out] == ["Big", "Mid", "Small"]
    assert all(c["_decider"] is None for c in out)
    # No deciding signal → no "why this fund" suffix.
    assert _trim_reason_suffix(out[0]) == ""


def test_worst_quality_trimmed_first():
    cands = [
        _h("GoodFund", 5_00_000, exit_score=2.0),   # strong fund, keep
        _h("WeakFund", 1_00_000, exit_score=8.5),   # weak vs peers, trim
    ]
    out = _composite_trim_order(cands)
    assert out[0]["name"] == "WeakFund"
    assert out[0]["_decider"] == "quality"
    assert "weakest on quality" in _trim_reason_suffix(out[0])
    assert "8.5/10" in _trim_reason_suffix(out[0])


def test_high_overlap_trimmed_first():
    cands = [
        _h("UniqueFund", 5_00_000, overlap_pct=10.0),
        _h("DupFund", 4_00_000, overlap_pct=92.0, overlap_with="UniqueFund"),
    ]
    out = _composite_trim_order(cands)
    assert out[0]["name"] == "DupFund"
    assert out[0]["_decider"] == "overlap"
    s = _trim_reason_suffix(out[0])
    assert "overlaps 92% with UniqueFund" in s


def test_lower_tax_trimmed_first_when_tax_dominates():
    # Equal/absent other signals; tax is the only differentiator → cheaper to
    # exit (lower tax_pct) should be trimmed first.
    cands = [
        _h("HighTax", 5_00_000, tax_pct=18.0),
        _h("LowTax", 5_00_000, tax_pct=1.0),
    ]
    out = _composite_trim_order(cands)
    assert out[0]["name"] == "LowTax"
    assert out[0]["_decider"] == "tax"
    assert "cheapest to exit on tax" in _trim_reason_suffix(out[0])


def test_partial_signals_do_not_unfairly_zero_a_fund():
    # FundA has only a (bad) quality score; FundB has no signals. FundA must
    # still rank first — it shouldn't be dragged down to FundB's level.
    cands = [
        _h("FundA", 2_00_000, exit_score=9.0),
        _h("FundB", 9_00_000),
    ]
    out = _composite_trim_order(cands)
    assert out[0]["name"] == "FundA"
    assert out[0]["_decider"] == "quality"


def test_quality_outweighs_overlap_on_a_straight_two_way_conflict():
    # With only two candidates, min-max maps each signal to {0,1}, so a
    # straight conflict is decided by the heavier weight: quality (.40) beats
    # overlap (.30). B is worst on quality → trimmed first.
    cands = [
        _h("A", 3_00_000, exit_score=6.0, overlap_pct=95.0),
        _h("B", 3_00_000, exit_score=7.0, overlap_pct=5.0),
    ]
    out = _composite_trim_order(cands)
    assert out[0]["name"] == "B"
    assert out[0]["_decider"] == "quality"


def test_composite_order_differs_from_both_single_signal_orders():
    # P worst quality / no overlap; Q near-worst quality + worst overlap;
    # R cleanest. The blended order (Q,P,R) must differ from BOTH the pure
    # quality order (P,Q,R) and the pure overlap order (Q,R,P) — proof the
    # composite genuinely combines signals rather than tracking one.
    cands = [
        _h("P", 3_00_000, exit_score=7.0, overlap_pct=0.0),
        _h("Q", 3_00_000, exit_score=6.5, overlap_pct=100.0),
        _h("R", 3_00_000, exit_score=4.0, overlap_pct=40.0),
    ]
    out = [c["name"] for c in _composite_trim_order(cands)]
    assert out == ["Q", "P", "R"]


def test_empty_input():
    assert _composite_trim_order([]) == []
