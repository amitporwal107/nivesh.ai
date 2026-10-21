"""Regime-fit top ideas: strike planning, pricing and fit scoring.

The chain fixture is a REAL response captured from staging on 2026-10-21
(`GET /api/fno/NIFTY/chain?expiry=2026-10-27`): NIFTY, lot 65, 81 strikes, spot 22811.35,
ATM 22800, ATM IV 14.18, PCR 0.6999, max pain 22900, expected move 333.3, call wall 23000,
put wall 22000. Nothing in it is invented, so the arithmetic below is checked against prices
that actually traded.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.strategy_plan import regime_fit as rf

FIXTURE = Path(__file__).parent / "fixtures" / "fno_chain_nifty_20261021.json"


@pytest.fixture(scope="module")
def chain():
    ch = json.loads(FIXTURE.read_text())
    ch["asof"] = ch["summary"]["as_of"]
    return ch


@pytest.fixture
def regime_down_low():
    """The regime actually measured on 2026-10-19 (GET /api/macro/today): trend down, VIX 14.77
    under the 20.0 threshold, breadth down."""
    return {"available": True, "key": "bearish", "as_of": "2026-10-19", "trend": "down",
            "nifty_close": 22888.95, "nifty_average": 23514.266, "nifty_vs_average_pct": -2.66,
            "india_vix": 14.77, "vix_high_threshold": 20.0, "volatility": "low",
            "breadth": "down", "advancing_share_pct": 19.0, "rule_version": "desk-regime-v1"}


# ── the fixture is what we think it is ──────────────────────────────────────

def test_fixture_is_the_real_captured_chain(chain):
    s = chain["summary"]
    assert chain["symbol"] == "NIFTY" and chain["lot_size"] == 65
    assert s["as_of"] == "2026-10-21" and s["expiry"] == "2026-10-27"
    assert s["atm_strike"] == 22800 and len(chain["strikes"]) == 81


# ── TC-4/TC-5: structures and their direction/premium metadata ──────────────

def test_every_family_declares_view_and_flow():
    for key, meta in rf.FAMILY.items():
        assert meta["view"] in ("up", "down", "flat"), key
        assert meta["flow"] in ("debit", "credit"), key


def test_an_index_is_offered_only_structures_with_no_cash_leg():
    # TC-9 / the gap note: NIFTY cannot be held, so nothing requiring the underlying is offered.
    assert rf.OPTION_ONLY, "an index must still have structures to offer"
    for fam in rf.OPTION_ONLY:
        assert rf.FAMILY[fam]["cash_leg"] is False


# ── strike planning against the real chain ──────────────────────────────────

@pytest.mark.parametrize("family", ["long_call", "long_put", "bull_call_spread",
                                    "bear_put_spread", "bull_put_spread", "bear_call_spread"])
def test_strike_plans_are_listed_strikes(chain, family):
    listed = {r["strike"] for r in chain["strikes"]}
    plans = rf.strike_plans(family, chain)
    assert plans, f"{family} produced no strike plan on a real 81-strike chain"
    for p in plans:
        for k in ("k", "long", "short"):
            if k in p:
                assert p[k] in listed, f"{family}: {k}={p[k]} is not a listed strike"


def test_directional_singles_offer_atm_and_one_otm(chain):
    for family, direction in (("long_call", 1), ("long_put", -1)):
        plans = rf.strike_plans(family, chain)
        assert len(plans) == 2
        assert plans[0]["k"] == 22800
        assert (plans[1]["k"] > 22800) if direction == 1 else (plans[1]["k"] < 22800)


def test_credit_spread_shorts_sit_on_the_correct_side_of_spot(chain):
    # A bull put spread sells a put BELOW spot; a bear call spread sells a call ABOVE spot.
    spot = chain["summary"]["spot"]
    bps = rf.strike_plans("bull_put_spread", chain)[0]
    bcs = rf.strike_plans("bear_call_spread", chain)[0]
    assert bps["short"] < spot and bps["long"] < bps["short"]
    assert bcs["short"] > spot and bcs["long"] > bcs["short"]


def test_iron_condor_is_refused_when_the_walls_are_inside_the_expected_move(chain):
    # Real gate, real numbers: spot 22811.35, call wall 23000 is 188.65 away, expected move 333.3.
    # candidates.condor_ok must refuse, so no condor is offered rather than a bad one being priced.
    assert rf.strike_plans("iron_condor", chain) == []


# ── TC-11/TC-12/TC-13: pricing through the shipped payoff engine ────────────

def _first_priced(chain, family):
    for plan in rf.strike_plans(family, chain):
        got = rf.price_variant(chain, family, plan, chain["lot_size"])
        if got["ok"]:
            return plan, got
    return None, None


@pytest.mark.parametrize("family", ["long_call", "long_put", "bull_call_spread",
                                    "bear_put_spread", "bull_put_spread", "bear_call_spread"])
def test_legs_carry_a_real_price_and_name_their_source(chain, family):
    plan, got = _first_priced(chain, family)
    assert got is not None, f"{family} did not price on the real chain"
    for leg in got["legs"]:
        assert leg["kind"] == "option"
        assert leg["entry_price"] > 0
        assert leg["lot_size"] == 65
        assert leg["price_source"] == "NSE F&O bhavcopy close, 2026-10-21"


def test_debit_spread_metrics_are_bounded_both_ways(chain):
    plan, got = _first_priced(chain, "bull_call_spread")
    m = rf.metrics_for("NIFTY", got["legs"], chain["summary"]["spot"], chain["asof"],
                       scenario_price=rf._expected_move_price("up", chain["summary"]))
    assert m["ok"]
    assert m["profit_unbounded"] is False and m["loss_unbounded"] is False
    assert m["max_profit"] > 0 and m["max_loss"] < 0
    # The spread can never win more than its width, nor lose more than the debit paid.
    width = abs(plan["short"] - plan["long"]) * 65
    assert m["max_profit"] <= width
    assert abs(m["max_loss"]) <= width
    assert m["reward_risk_at_expected_move"] and m["reward_risk_at_expected_move"] > 0
    assert len(m["breakevens"]) >= 1


def test_long_option_profit_is_unbounded_and_loss_is_the_premium(chain):
    plan, got = _first_priced(chain, "long_call")
    m = rf.metrics_for("NIFTY", got["legs"], chain["summary"]["spot"], chain["asof"],
                       scenario_price=rf._expected_move_price("up", chain["summary"]))
    assert m["ok"] and m["profit_unbounded"] is True
    # The most a bought call can lose is what it cost.
    assert abs(m["max_loss"]) == pytest.approx(got["legs"][0]["entry_price"] * 65, rel=1e-6)
    # Unbounded profit has no theoretical reward : risk, and must not be reported as if it did.
    assert m["reward_risk_theoretical"] is None


def test_margin_is_never_estimated(chain):
    plan, got = _first_priced(chain, "bear_call_spread")
    m = rf.metrics_for("NIFTY", got["legs"], chain["summary"]["spot"], chain["asof"],
                       scenario_price=rf._expected_move_price("down", chain["summary"]))
    assert m["margin"] is None
    assert "no margin source" in (m["margin_reason"] or "").lower()


# ── TC-14: net Greeks ───────────────────────────────────────────────────────

def test_net_greeks_are_signed_sums_of_the_chain_rows(chain):
    plan, got = _first_priced(chain, "bull_call_spread")
    g = rf._net_greeks(got["views"], chain, 65)
    rowmap = {r["strike"]: r for r in chain["strikes"]}
    expected = sum((1 if v["side"] == "buy" else -1) * rowmap[v["strike"]][v["option_type"]]["delta"] * 65
                   for v in got["views"])
    assert g["delta"] == pytest.approx(expected, rel=1e-6)
    # A bought-call spread is net long delta.
    assert g["delta"] > 0


# ── fit scoring ─────────────────────────────────────────────────────────────

def test_fit_rewards_the_structure_that_matches_trend_and_volatility(chain, regime_down_low):
    S = chain["summary"]
    bear_debit = rf.score_fit("bear_put_spread", regime_down_low, S, False)   # down + debit, vol low
    bull_debit = rf.score_fit("bull_call_spread", regime_down_low, S, False)  # wrong direction
    bear_credit = rf.score_fit("bear_call_spread", regime_down_low, S, False)  # right way, wrong premium side
    assert bear_debit["score"] > bear_credit["score"] > bull_debit["score"]


def test_every_fit_factor_states_its_real_reason(chain, regime_down_low):
    fit = rf.score_fit("bear_put_spread", regime_down_low, chain["summary"], True)
    keys = {f["factor"] for f in fit["because"]}
    assert keys == {"direction", "volatility", "breadth", "positioning"}
    for f in fit["because"]:
        assert f["state"] in ("supports", "neutral", "conflicts")
        assert f["text"].strip()
    # The real measured numbers must appear in the text, not a generic phrase.
    joined = " ".join(f["text"] for f in fit["because"])
    assert "14.77" in joined and "20.0" in joined and "19.0" in joined


def test_fit_is_neutral_rather_than_wrong_when_an_input_is_missing(chain):
    blank = {"available": True, "trend": None, "volatility": None, "breadth": None,
             "india_vix": None, "vix_high_threshold": None}
    fit = rf.score_fit("long_call", blank, chain["summary"], None)
    assert all(f["state"] == "neutral" for f in fit["because"])
    # All-neutral must land at half the weight, never at zero or full marks.
    assert fit["score"] == pytest.approx(sum(rf.WEIGHTS.values()) / 2)


# ── TC-17/TC-21/TC-22/TC-26: the wording that must travel with every answer ──

def test_ranking_note_refuses_the_three_claims_it_must_not_make():
    note = rf.RANKING_NOTE.lower()
    assert "not a forecast" in note
    assert "not a probability" in note
    assert "not a ranking by past performance" in note
    assert "nothing is sent to a broker" in note


def test_gaps_name_the_two_things_that_cannot_be_done():
    joined = " ".join(rf.GAPS).lower()
    assert "iv percentile" in joined or "iv rank" in joined
    assert "performance" in joined
    assert "end of day" in joined


def test_nothing_in_the_module_tells_anyone_to_trade():
    text = (rf.RANKING_NOTE + " " + " ".join(rf.GAPS)).lower()
    for imperative in (" buy ", " sell ", "you should", "we recommend"):
        assert imperative not in text


# ── the long-option ranking defect, pinned ──────────────────────────────────

def test_a_long_put_is_not_ranked_on_its_payoff_at_an_underlying_price_of_zero(chain):
    """A bought put's theoretical max profit is the strike times the lot, i.e. the payoff if NIFTY
    went to 0. Ranking on it gave a long put a reward:risk of 133 and floated it above every spread.
    The ranking number must be the net P&L at the chain's own expected move instead."""
    S = chain["summary"]
    _, put = _first_priced(chain, "long_put")
    m = rf.metrics_for("NIFTY", put["legs"], S["spot"], chain["asof"],
                       scenario_price=rf._expected_move_price("down", S))
    assert m["reward_risk_theoretical"] > 50, "fixture no longer reproduces the defect"
    assert m["reward_risk_at_expected_move"] < 5, "the ranking number must be an achievable move"

    # And on the real chain the defined-risk spread must now outrank the long put.
    _, spread = _first_priced(chain, "bear_put_spread")
    ms = rf.metrics_for("NIFTY", spread["legs"], S["spot"], chain["asof"],
                        scenario_price=rf._expected_move_price("down", S))
    assert ms["reward_risk_at_expected_move"] > m["reward_risk_at_expected_move"]


def test_expected_move_price_moves_the_right_way_and_degrades(chain):
    S = chain["summary"]
    assert rf._expected_move_price("down", S) == pytest.approx(S["spot"] - S["expected_move"])
    assert rf._expected_move_price("up", S) == pytest.approx(S["spot"] + S["expected_move"])
    assert rf._expected_move_price("flat", S) == pytest.approx(S["spot"])
    # No expected move published -> no invented one.
    assert rf._expected_move_price("up", {"spot": 100.0, "expected_move": None}) is None


# ── the staleness comparison that 500'd on staging, pinned ──────────────────

def test_newest_day_never_returns_something_uncomparable():
    """POST /api/desk/strategy/top answered 500 on staging with
    TypeError: '>' not supported between instances of 'dict' and 'str', because the cash class's
    as_of came from the ideas engine's `data_as_of`, which is an OBJECT of per-source dates."""
    assert rf._newest_day("2026-10-21") == "2026-10-21"
    assert rf._newest_day({"chain": "2026-10-19", "scanner": "2026-10-21"}) == "2026-10-21"
    assert rf._newest_day({}) is None
    assert rf._newest_day({"a": None, "b": 3}) is None
    assert rf._newest_day(None) is None
    assert rf._newest_day(17) is None
    # Whatever comes back must compare against a day without raising.
    for v in ("2026-10-21", {"x": "2026-10-20"}, {}, None, 17):
        d = rf._newest_day(v)
        assert d is None or d > "2000-01-01"
