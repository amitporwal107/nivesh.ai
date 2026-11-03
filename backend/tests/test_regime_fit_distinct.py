"""Regime-fit board, one row per underlying (`distinct`) — test cases B-1 … B-7 of
test_reports/desk_scanner_top10_TESTCASES.md.

The ideas here are synthetic: only the fields the ranking and the grouping read (underlying, structure,
fit score, reward : risk) are set, so each assertion is about the ordering rule, not about pricing.
Pricing and fit scoring are covered against the real captured chain in test_regime_fit.py.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from routes import strategy_plan as route
from services.strategy_plan import regime_fit as rf


def idea(underlying: str, structure: str, fit: float, rr):
    return {"underlying": underlying, "structure": structure, "fit": {"score": fit, "because": []}, "reward_risk": rr}


POOL = [
    idea("BANKNIFTY", "bear_put_spread", 92.5, 2.01),
    idea("NIFTY", "bear_put_spread", 92.5, 1.44),
    idea("BANKNIFTY", "long_put", 92.5, 1.01),
    idea("BANKNIFTY", "long_put_otm", 92.5, 0.97),
    idea("NIFTY", "long_put", 92.5, 0.63),
    idea("BANKNIFTY", "bear_call_spread", 80.0, 3.5),
    idea("NIFTY", "iron_condor", 55.0, None),
]


# ── B-2 / B-3 / B-4: one row per underlying ───────────────────────────────

def test_distinct_keeps_the_best_idea_of_each_underlying_in_rank_order():
    out = rf.one_per_underlying(POOL, limit=10)
    assert [(i["underlying"], i["structure"]) for i in out] == [("BANKNIFTY", "bear_put_spread"), ("NIFTY", "bear_put_spread")]
    assert [i["rank"] for i in out] == [1, 2]


def test_alternatives_are_the_next_structures_of_the_same_underlying_in_order_and_capped():
    out = rf.one_per_underlying(POOL, limit=10)
    bank, nifty = out
    assert [a["structure"] for a in bank["alternatives"]] == ["long_put", "long_put_otm"]   # capped at ALTERNATIVES_MAX = 2
    assert [a["structure"] for a in nifty["alternatives"]] == ["long_put", "iron_condor"]
    assert all(a["rank"] is None for a in bank["alternatives"] + nifty["alternatives"])
    top_level = {(i["underlying"], i["structure"]) for i in out}
    assert not top_level & {(a["underlying"], a["structure"]) for i in out for a in i["alternatives"]}


def test_a_missing_reward_risk_sorts_last_within_its_fit_band():
    pool = [idea("A", "x", 90.0, None), idea("B", "y", 90.0, 0.5)]
    assert [i["underlying"] for i in rf.one_per_underlying(pool, limit=5)] == ["B", "A"]


@pytest.mark.parametrize("limit, want", [(1, 1), (2, 2), (10, 2)])
def test_limit_counts_underlyings_not_structures(limit, want):
    assert len(rf.one_per_underlying(POOL, limit=limit)) == want


def test_distinct_does_not_mutate_the_pool():
    pool = [dict(i) for i in POOL]
    rf.one_per_underlying(pool, limit=10)
    assert all("alternatives" not in i and "rank" not in i for i in pool)


# ── B-5: the stock F&O universe ───────────────────────────────────────────

def setup(sym, fno):
    return {"symbol": sym, "fno_eligible": fno}


def test_non_fno_names_are_skipped_with_a_reason_and_known_fno_names_come_first():
    setups = [setup("PREMEXPLN", False), setup("MPHASIS", True), setup("ODDCO", None), setup("ICICIBANK", True),
              setup("SGMART", False), setup("HAL", True)]
    syms, skipped = rf.order_fno_names(setups, want=12)
    assert syms == ["MPHASIS", "ICICIBANK", "HAL", "ODDCO"]
    assert [s["underlying"] for s in skipped] == ["PREMEXPLN", "SGMART"]
    assert all(s["reason"] == rf.NOT_FNO_REASON for s in skipped)


def test_the_walk_stops_once_enough_fno_names_are_found():
    setups = [setup("A", True), setup("B", True), setup("C", False), setup("D", True)]
    syms, skipped = rf.order_fno_names(setups, want=2)
    assert syms == ["A", "B"]
    assert skipped == []        # C was never reached, so it is not reported as passed over


def test_duplicates_and_blank_symbols_are_ignored():
    syms, skipped = rf.order_fno_names([setup("a", True), setup("A", True), {"symbol": None, "fno_eligible": True}], want=5)
    assert syms == ["A"] and skipped == []


# ── B-6: the route's body validation ──────────────────────────────────────

def test_distinct_must_be_a_boolean():
    with pytest.raises(HTTPException) as e:
        route._parse_top_body({"distinct": "yes"})
    assert e.value.status_code == 422
    assert [p["field"] for p in e.value.detail["problems"]] == ["distinct"]


def test_distinct_true_is_accepted_and_defaults_to_false():
    assert route._parse_top_body({"distinct": True, "limit": 10})["distinct"] is True
    assert route._parse_top_body({})["distinct"] is False


def test_unknown_fields_are_still_refused():
    with pytest.raises(HTTPException) as e:
        route._parse_top_body({"distinct": True, "nope": 1})
    assert e.value.detail["problems"][0]["code"] == "unknown_field"


# ── B-7 / B-1: build_top end to end, with the chain reads stubbed ────────

REGIME = {"available": True, "key": "bearish", "as_of": "2026-10-19", "trend": "down", "india_vix": 14.77,
          "vix_high_threshold": 20.0, "volatility": "low", "breadth": "down"}


def _stub(monkeypatch, reads: list):
    async def regime():
        return REGIME

    async def per_underlying(request, symbol, regime, *, expiry=None, limit=5):
        reads.append((symbol, limit))
        if symbol == "NOCHAIN":
            return {"underlying": symbol, "available": False, "reason": "LookupError: no expiries", "ideas": []}
        mine = sorted([dict(i) for i in POOL if i["underlying"] == symbol] or
                      [idea(symbol, "bear_put_spread", 70.0 + len(symbol), 1.2), idea(symbol, "long_put", 60.0, 0.8)],
                      key=rf._rank_key)
        return {"underlying": symbol, "available": True, "as_of": "2026-10-21", "spot": 100.0, "expiry": "2026-10-27",
                "chain_context": {}, "ideas": mine[:limit], "considered": len(mine) + 3}

    async def eligible(request, limit):
        return {"setups": [setup("PREMEXPLN", False), setup("MPHASIS", True), setup("NOCHAIN", True), setup("HAL", True)]}

    async def select(request, want):
        return {"setups": [setup("PREMEXPLN", False), setup("MPHASIS", True)]}

    from services.strategy_plan import selection
    monkeypatch.setattr(rf, "read_regime", regime)
    monkeypatch.setattr(rf, "ideas_for_underlying", per_underlying)
    monkeypatch.setattr(selection, "eligible_setups", eligible)
    monkeypatch.setattr(selection, "select_opportunities", select)


def test_build_top_distinct_gives_one_row_per_underlying_in_both_option_classes(monkeypatch):
    reads: list = []
    _stub(monkeypatch, reads)
    out = asyncio.run(rf.build_top(None, "u1", limit=10, classes=["index_options", "stock_fno"], distinct=True))
    assert out["distinct"] is True and set(out["classes"]) == {"index_options", "stock_fno"}
    for cls in out["classes"].values():
        us = [i["underlying"] for i in cls["ideas"]]
        assert len(us) == len(set(us)) and cls["distinct"] is True
    stock = out["classes"]["stock_fno"]
    assert stock["universe"]["symbols_tried"] == ["MPHASIS", "NOCHAIN", "HAL"]
    assert [s["underlying"] for s in stock["universe"]["skipped"]] == ["PREMEXPLN"]
    assert "PREMEXPLN" not in [s for s, _ in reads]                      # no chain read for a non-F&O name
    assert [u["underlying"] for u in stock["unavailable"]] == ["NOCHAIN"]  # an unreadable chain is reported, not dropped
    assert all(lim == 1 + rf.ALTERNATIVES_MAX for _, lim in reads)
    assert stock["considered"] > len(stock["ideas"])                     # every structure priced, not only the kept ones
    assert out["sent_to_broker"] is False


def test_build_top_without_distinct_is_unchanged(monkeypatch):
    reads: list = []
    _stub(monkeypatch, reads)
    out = asyncio.run(rf.build_top(None, "u1", limit=5, classes=["index_options", "stock_fno"]))
    assert out["distinct"] is False
    idx = out["classes"]["index_options"]
    assert [i["underlying"] for i in idx["ideas"]].count("BANKNIFTY") > 1   # duplicates allowed, as before
    assert all("alternatives" not in i for i in idx["ideas"]) and "distinct" not in idx
    assert out["classes"]["stock_fno"]["universe"] == {
        "source": "the AI scanner's merged setup list (services/strategy_plan/selection.select_opportunities)",
        "symbols_tried": ["PREMEXPLN", "MPHASIS"]}
    assert all(lim == 5 for _, lim in reads)


def test_build_top_with_no_regime_scores_nothing(monkeypatch):
    reads: list = []
    _stub(monkeypatch, reads)

    async def no_regime():
        return {"available": False, "reason": "no classification yet"}

    monkeypatch.setattr(rf, "read_regime", no_regime)
    out = asyncio.run(rf.build_top(None, "u1", limit=10, classes=["index_options", "stock_fno"], distinct=True))
    assert all(c["ideas"] == [] for c in out["classes"].values()) and reads == []
