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
    _isin_of,
    _build_signal_index,
    _sector_lookthrough,
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


# ── Sector look-through attribution (which funds/stocks drive a sector) ────
def test_sector_lookthrough_attributes_funds_and_stocks():
    intel = {
        "mf_investments": [
            {"instrument_id": "f1", "scheme_name": "Fund A", "amount_rs": 100_000, "resolved": True},
            {"instrument_id": "f2", "scheme_name": "Fund B", "amount_rs": 50_000, "resolved": True},
            {"instrument_id": "f3", "scheme_name": "Skip", "amount_rs": 99_999, "resolved": False},
        ],
        "catalog": {
            "f1": {"scheme_name": "Fund A", "holdings": [
                {"holding_name": "HDFC Bank", "holding_sector": "Financial", "weight_percent": 30},
                {"holding_name": "Infosys", "holding_sector": "Technology", "weight_percent": 10}]},
            "f2": {"scheme_name": "Fund B", "holdings": [
                {"holding_name": "ICICI Bank", "holding_sector": "Financial", "weight_percent": 20},
                {"holding_name": "HDFC Bank", "holding_sector": "Financial", "weight_percent": 10}]},
        },
    }
    funds, stocks = _sector_lookthrough(intel, "Financial")
    # Fund A: 30% × 100k = 30k ; Fund B: (20%+10%) × 50k = 15k
    assert funds == [("Fund A", 30_000.0), ("Fund B", 15_000.0)]
    # HDFC Bank: 30k (A) + 5k (B) = 35k ; ICICI Bank: 10k. Unresolved fund excluded.
    assert stocks[0] == ("HDFC Bank", 35_000.0)
    assert dict(stocks)["ICICI Bank"] == 10_000.0
    assert "Infosys" not in dict(stocks)  # wrong sector excluded


def test_sector_lookthrough_empty_when_no_match():
    intel = {"mf_investments": [{"instrument_id": "f1", "amount_rs": 1, "resolved": True}],
             "catalog": {"f1": {"holdings": [{"holding_sector": "Energy", "weight_percent": 50}]}}}
    funds, stocks = _sector_lookthrough(intel, "Financial")
    assert funds == [] and stocks == []


# ── ISIN join (the staging-surfaced bug: name-matching never worked) ──────
def test_isin_of_reads_holding_ticker_and_intel_isin():
    # Holdings keep the ISIN in `ticker`; intelligence entries in `isin`.
    assert _isin_of({"ticker": "INF179K01830"}) == "INF179K01830"
    assert _isin_of({"isin": "inf179k01830"}) == "INF179K01830"  # upper-cased
    assert _isin_of({"ticker": "GROWTH"}) is None                # not 12-char alnum
    assert _isin_of({"ticker": ""}) is None
    assert _isin_of({}) is None


def test_build_signal_index_joins_by_isin_not_name():
    # Mirrors the real staging shapes: scheme_name differs from the holding
    # name ("… - Growth Plan" vs "… Growth"), so only ISIN can join. The user
    # holds the same scheme as Regular + Direct → ~100% overlap with its twin.
    mfs = [
        {"instrument_id": "iid-reg", "isin": "INF179K01830",
         "scheme_name": "HDFC Balanced Advantage Fund Growth"},
        {"instrument_id": "iid-dir", "isin": "INF179K01WA6",
         "scheme_name": "HDFC Balanced Advantage Fund Direct Growth"},
    ]
    pairs = [{
        "a": "iid-reg", "a_name": "HDFC Balanced Advantage Fund Growth",
        "b": "iid-dir", "b_name": "HDFC Balanced Advantage Fund Direct Growth",
        "overlap_pct": 99.86,
    }]
    mf_by_isin, best_ov = _build_signal_index(mfs, pairs)

    # The holding name would never match by normalisation — ISIN does.
    holding = {"ticker": "INF179K01830", "name": "HDFC Balanced Advantage Fund - Growth Plan"}
    m = mf_by_isin.get(_isin_of(holding))
    assert m is not None
    assert m["scheme_name"] == "HDFC Balanced Advantage Fund Growth"

    pct, sib = best_ov[m["instrument_id"]]
    assert pct == 99.86
    assert sib == "HDFC Balanced Advantage Fund Direct Growth"


def test_build_signal_index_keeps_highest_overlap_per_instrument():
    mfs = [{"instrument_id": "x", "isin": "INF000000001", "scheme_name": "X"}]
    pairs = [
        {"a": "x", "a_name": "X", "b": "y", "b_name": "Y-low", "overlap_pct": 40.0},
        {"a": "z", "a_name": "Z", "b": "x", "b_name": "X", "overlap_pct": 88.0},
    ]
    _, best_ov = _build_signal_index(mfs, pairs)
    pct, sib = best_ov["x"]
    assert pct == 88.0 and sib == "Z"  # highest wins, sibling taken from the pair
