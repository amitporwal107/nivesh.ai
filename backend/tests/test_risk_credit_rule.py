"""The credit-structure rule of the universal risk service (policy universal-risk-v2, owner decision 2026-10-28).

TESTCASES: test_reports/risk_credit_rule_TESTCASES.md (CR-1 … CR-18). A defined-risk credit structure (decided from its
legs and payoff by estimate.credit_terms) skips the min_reward_risk (1.5) check; instead its net credit less the risk
estimate's round-trip costs must be at least 1/3 of its strike width (credit_too_small). Its maximum loss + costs must
still fit the per-trade budget. Every other entry keeps 1.5 (reward_risk_too_low).

MOCK — not real data: NIFTY / BANKNIFTY / FIXA / FIXB and every premium, lot and price here are made up. The snapshots
are the hand-built calm-market ones of tests/test_risk_service.py; CR-18 runs the REAL routes on the in-memory Mongo of
tests/test_plan_sizing.py.
"""
from __future__ import annotations

import asyncio
import copy

import pytest

from services.risk_gate import estimate as est
from services.risk_gate import replay
from services.risk_gate import service as svc
from services.strategy_plan import trade_plan as tpm
from tests import contract_fixtures as cf
from services import desk_trading as desk
from tests.test_fno_idea_paper_trade_contract import CLOCK, CONTRACT, exchange_lots  # noqa: F401  (autouse: MOCK exchange lot)
from tests.test_plan_sizing import H, account_size, world  # noqa: F401  (the real-routes fixture)
from tests.test_risk_service import EXPIRY, cash, codes, listed, snap, structure

V1, V2 = "universal-risk-v1", "universal-risk-v2"


def opt(side, typ, strike, price, lots=1, lot=50, expiry=EXPIRY):
    return {"kind": "option", "side": side, "lots": lots, "lot_size": lot, "entry_price": price, "expiry": expiry,
            "strike": strike, "option_type": typ}


def shares(n, price):
    return {"kind": "cash", "side": "buy", "lots": n, "lot_size": 1, "entry_price": price, "expiry": None,
            "strike": None, "option_type": None}


def reason(d, code):
    return next(r for r in d["reasons"] if r["code"] == code)


def check(d, name):
    return next(c for c in d["checks"] if c["check"] == name)


def nifty(legs, equity=1_000_000.0, **over):
    return svc.decide(structure(legs, **over), snap(last_close=25010.0, equity=equity, refs=listed(50)))


# A MOCK stock at Rs 100 with a 1,000-share lot (CR-1): low strike notional, so the estimate's exit costs stay small.
def fixb(legs, equity=1_000_000.0):
    req = structure(legs, symbol="FIXB", reference_price=100.0)
    return svc.decide(req, snap(last_close=100.0, equity=equity, refs=listed(1000)))


BULL_PUT_FIXB = [opt("buy", "put", 95, 0.8, lot=1000), opt("sell", "put", 100, 3.0, lot=1000)]
BEAR_CALL = [opt("sell", "call", 25100, 80), opt("buy", "call", 25200, 40)]          # credit 40 a unit, width 100


def iron_condor(short_call):
    """Put wing 100 points, call wing 200 points (the wider): width = 200 x 50 = Rs 10,000."""
    return [opt("buy", "put", 24700, 40), opt("sell", "put", 24800, 60), opt("sell", "call", 25200, short_call),
            opt("buy", "call", 25400, 25)]


def collar(put_px, call_px):
    """100 FIXA shares at 1,005, a long 980 put and a short 1,040 call (lot 100)."""
    return [shares(100, 1005.0), opt("buy", "put", 980, put_px, lot=100), opt("sell", "call", 1040, call_px, lot=100)]


def fixa(legs, equity=2_000_000.0):
    req = structure(legs, symbol="FIXA", reference_price=1005.0)
    return svc.decide(req, snap(last_close=1005.0, equity=equity, refs=listed(100)))


# ── CR-1 … CR-3: vertical credit spreads ─────────────────────────────────────
def test_cr1_a_bull_put_spread_with_a_third_of_the_width_after_costs_is_allowed_below_1_5():
    terms = est.credit_terms(BULL_PUT_FIXB)
    assert terms["net_credit_rs"] == 2200.0 and terms["width_rs"] == 5000.0          # (100 - 95) x 1,000
    d = fixb(BULL_PUT_FIXB)
    b = d["budget"]
    assert d["outcome"] == "allow" and d["approved_lots"] == 1, codes(d)
    assert b["reward_risk_rule"] == svc.RULE_CREDIT and b["min_reward_risk"] is None and b["reward_risk"] is None
    assert b["credit_after_costs_rs"] == round(2200.0 - d["estimated_risk_rs"]["costs"], 2) >= b["min_credit_rs"] == 1666.67
    assert check(d, "reward_risk")["status"] == "pass" and "credit structure" in check(d, "reward_risk")["detail"]
    # the same request under v1 is refused by the 1.5 minimum: the owner's rule is what lets it in
    old = svc.decide(structure(BULL_PUT_FIXB, symbol="FIXB", reference_price=100.0),
                     snap(last_close=100.0, refs=listed(1000)), policy_version=V1)
    assert old["outcome"] == "block" and "reward_risk_too_low" in codes(old) and old["budget"]["reward_risk"] < 1.5


def test_cr2_a_bull_put_spread_below_a_third_of_the_width_is_blocked_credit_too_small():
    legs = [opt("buy", "put", 95, 1.0, lot=1000), opt("sell", "put", 100, 2.5, lot=1000)]      # credit Rs 1,500
    d = fixb(legs)
    r = reason(d, "credit_too_small")
    assert d["outcome"] == "block" and r["check"] == "reward_risk" and r["severity"] == "block"
    assert r["value"] == round(1500.0 - d["estimated_risk_rs"]["costs"], 2) and r["limit"] == 1666.67
    assert "reward_risk_too_low" not in codes(d) and check(d, "reward_risk")["status"] == "fail"


@pytest.mark.parametrize("long_call_px,allowed", [(40, True), (50, False)])
def test_cr3_a_bear_call_spread_is_judged_by_the_same_rule(long_call_px, allowed):
    legs = [opt("sell", "call", 25100, 80), opt("buy", "call", 25200, long_call_px)]
    d = nifty(legs, direction="bearish")
    b = d["budget"]
    assert b["reward_risk_rule"] == svc.RULE_CREDIT and b["strike_width_rs"] == 5000.0
    assert (d["outcome"] == "allow") is allowed, codes(d)
    assert ("credit_too_small" in codes(d)) is (not allowed) and "reward_risk_too_low" not in codes(d)


# ── CR-4: iron condor, the wider wing ────────────────────────────────────────
def test_cr4_an_iron_condor_is_measured_against_its_wider_wing():
    low = iron_condor(70)                                 # credit (60-40) + (70-25) = 65 a unit = Rs 3,250
    t = est.credit_terms(low)
    assert t["width_rs"] == 10_000.0 and t["net_credit_rs"] == 3250.0
    assert t["net_credit_rs"] >= 5000.0 / 3                # enough against the NARROWER (put) wing …
    d = nifty(low, equity=2_500_000.0, direction="neutral")
    r = reason(d, "credit_too_small")                      # … but not against the wider one
    assert d["outcome"] == "block" and r["limit"] == 3333.33
    ok = nifty(iron_condor(90), equity=2_500_000.0, direction="neutral")       # credit Rs 4,250
    assert ok["outcome"] == "allow" and ok["budget"]["credit_after_costs_rs"] >= 3333.33, codes(ok)
    assert svc.decide(structure(iron_condor(90), direction="neutral"),
                      snap(last_close=25010.0, equity=2_500_000.0, refs=listed(50)), policy_version=V1)["outcome"] == "block"


# ── CR-5, CR-6: a collar for a credit vs for a debit ─────────────────────────
def test_cr5_a_collar_opened_for_a_net_credit_is_a_credit_structure():
    t = est.credit_terms(collar(12, 30))
    assert t["net_credit_rs"] == 1800.0 and t["width_rs"] == 2500.0           # (1,005 - 980) x 100 shares
    d = fixa(collar(12, 30))
    assert d["outcome"] == "allow" and d["budget"]["reward_risk_rule"] == svc.RULE_CREDIT, codes(d)
    small = fixa(collar(20, 28))                          # credit Rs 800: under 1/3 of Rs 2,500 even before costs
    assert small["outcome"] == "block" and "credit_too_small" in codes(small) and "reward_risk_too_low" not in codes(small)
    assert reason(small, "credit_too_small")["limit"] == 833.33


def test_cr6_a_collar_opened_for_a_net_debit_keeps_the_1_5_minimum():
    legs = collar(25, 12)
    assert est.credit_terms(legs) is None
    d = fixa(legs)
    assert d["outcome"] == "block" and "reward_risk_too_low" in codes(d) and "credit_too_small" not in codes(d)
    assert d["budget"]["reward_risk_rule"] == svc.RULE_REWARD_RISK and d["budget"]["min_reward_risk"] == 1.5


# ── CR-7, CR-8: directional trades keep 1.5 ──────────────────────────────────
def test_cr7_a_debit_spread_keeps_the_1_5_minimum():
    legs = [opt("buy", "call", 25000, 220), opt("sell", "call", 25200, 130)]
    assert est.credit_terms(legs) is None
    d = nifty(legs, equity=2_000_000.0)
    r = reason(d, "reward_risk_too_low")
    assert d["outcome"] == "block" and r["limit"] == 1.5 and r["value"] < 1.5 and "credit_too_small" not in codes(d)
    assert d["budget"]["reward_risk_rule"] == svc.RULE_REWARD_RISK


def test_cr8_a_cash_trade_keeps_the_1_5_minimum():
    d = svc.decide(cash(quantity=10, target_price=1040.0), snap())
    assert d["outcome"] == "block" and "reward_risk_too_low" in codes(d) and "credit_too_small" not in codes(d)
    assert d["budget"]["reward_risk_rule"] == svc.RULE_REWARD_RISK and d["budget"]["min_reward_risk"] == 1.5
    assert svc.decide(cash(quantity=10), snap())["outcome"] == "allow"                # target 1,110: above 1.5


# ── CR-9, CR-10: the per-trade budget still binds ────────────────────────────
def test_cr9_a_credit_that_passes_does_not_let_a_max_loss_over_the_budget_in():
    legs = [opt("sell", "call", 25000, 200), opt("buy", "call", 25300, 60)]   # credit Rs 7,000 of a Rs 15,000 width
    t = est.credit_terms(legs)
    assert t["net_credit_rs"] - est.structure_risk(legs, direction=None, stop_underlying=None)[0]["costs"] >= t["width_rs"] / 3
    d = nifty(legs, direction="bearish")                  # 0.5% of Rs 10 lakh = Rs 5,000; max loss Rs 8,000 + costs
    r = reason(d, "min_lot_exceeds_budget")
    assert d["outcome"] == "block" and r["check"] == "per_trade_risk" and r["limit"] == 5000.0 and r["value"] > 8000.0


def test_cr10_over_the_budget_at_three_lots_it_is_reduced_and_judged_at_two():
    legs = [opt("sell", "call", 25100, 80, lots=3), opt("buy", "call", 25200, 40, lots=3)]
    d = nifty(legs, equity=1_400_000.0, direction="bearish")      # Rs 7,000 budget: ~Rs 3,111 a lot
    assert d["outcome"] == "reduce" and (d["requested_lots"], d["approved_lots"]) == (3, 2), codes(d)
    assert d["budget"]["credit_rs"] == 4000.0 and d["budget"]["strike_width_rs"] == 10_000.0     # at 2 lots
    assert d["estimated_risk_rs"]["total"] <= 7000.0 and "per_trade_risk_exceeded" in codes(d)


# ── CR-11: the costs are in the credit ───────────────────────────────────────
@pytest.mark.parametrize("legs,direction", [
    ([opt("sell", "call", 25100, 74), opt("buy", "call", 25200, 40)], "bearish"),        # gross Rs 1,700 >= 1,666.67
    ([opt("buy", "put", 24800, 60), opt("sell", "put", 24900, 94)], "bullish"),          # the same, put side
])
def test_cr11_the_credit_is_judged_after_the_estimates_round_trip_costs(legs, direction):
    t = est.credit_terms(legs)
    assert t["net_credit_rs"] == 1700.0 and t["net_credit_rs"] >= t["width_rs"] / 3          # passes BEFORE costs
    d = nifty(legs, equity=2_000_000.0, direction=direction)
    costs = d["estimated_risk_rs"]["costs"]
    assert costs == est.structure_risk(legs, direction=direction, stop_underlying=None)[0]["costs"] > 0
    r = reason(d, "credit_too_small")                                                         # fails AFTER them
    assert d["outcome"] == "block" and r["value"] == round(1700.0 - costs, 2) and r["limit"] == 1666.67
    assert d["budget"]["credit_costs_rs"] == costs


# ── CR-12 … CR-14: what is and is not a credit structure ─────────────────────
def test_cr12_a_covered_call_is_not_a_credit_structure_its_loss_runs_to_zero():
    legs = [shares(100, 1005.0), opt("sell", "call", 1040, 30, lot=100)]
    assert est.credit_terms(legs) is None
    d = fixa(legs, equity=25_000_000.0)                   # large enough for its Rs 97,500 loss to zero to be sized
    assert d["budget"]["reward_risk_rule"] == svc.RULE_REWARD_RISK and "reward_risk_too_low" in codes(d), codes(d)


def test_cr13_a_structure_with_a_futures_leg_is_not_a_credit_structure():
    fut = {"kind": "future", "side": "buy", "lots": 1, "lot_size": 100, "entry_price": 1005.0, "expiry": EXPIRY,
           "strike": None, "option_type": None}
    assert est.credit_terms([fut, opt("sell", "call", 1040, 30, lot=100)]) is None
    assert est.credit_terms([fut, opt("buy", "put", 980, 12, lot=100), opt("sell", "call", 1040, 30, lot=100)]) is None


def test_cr14_the_legs_decide_not_their_order_or_a_name():
    legs = [opt("buy", "put", 95, 0.8, lot=1000), opt("sell", "put", 100, 3.0, lot=1000)]
    named = [{**leg, "family": "bear_put_spread"} for leg in reversed(legs)]      # a wrong name changes nothing
    assert est.credit_terms(legs) == est.credit_terms(named) is not None
    assert est.credit_terms([opt("buy", "call", 25000, 100)]) is None                     # long option: a debit
    assert est.credit_terms([opt("sell", "put", 24900, 95)]) is None                      # naked: loss runs to zero
    assert est.credit_terms(legs[:1] + [opt("sell", "put", 100, 3.0, lot=1000, expiry="2026-12-31")]) is None  # 2 expiries


# ── CR-15, CR-16: replay under the decision's own policy ─────────────────────
def _row(req, s, policy_version):
    s = svc.gate.bson_safe({**s, "request": req.model_dump()})
    body = svc.decide(req, s, policy_version=policy_version)
    return {"_id": "d-" + policy_version, "source": "risk_service", "snapshot": s, "snapshot_version": svc.SNAPSHOT_VERSION,
            "snapshot_hash": svc.snapshot_hash(s), "inputs_hash": svc.inputs_hash(req), "policy_version": policy_version,
            "outcome": {"allow": "allowed", "reduce": "reduced", "block": "blocked"}[body["outcome"]],
            "reasons": body["reasons"], "checks": body["checks"], "approved_qty": body["approved_qty"],
            "approved_lots": body["approved_lots"]}


def test_cr15_a_v1_decision_replays_under_v1_unchanged_though_v2_now_allows_it():
    req, s = structure(BEAR_CALL, direction="bearish"), snap(last_close=25010.0, refs=listed(50))
    row = _row(req, s, V1)
    assert row["outcome"] == "blocked" and "reward_risk_too_low" in [r["code"] for r in row["reasons"]]
    out = replay.replay(row)
    assert out["replayable"] and out["match"], out["differences"]
    assert (out["policy_version_then"], out["replayed_under_policy"], out["policy_version_now"]) == (V1, V1, V2)
    assert out["reasons_now"] == out["reasons_then"] and out["outcome_now"] == "block"
    assert svc.decide(req, row["snapshot"])["outcome"] == "allow"                  # the same request, decided today


def test_cr16_a_v2_decision_replays_to_itself_and_an_unknown_policy_is_not_replayable():
    req, s = structure(BEAR_CALL, direction="bearish"), snap(last_close=25010.0, refs=listed(50))
    row = _row(req, s, V2)
    out = replay.replay(row)
    assert row["outcome"] == "allowed" and out["match"] and out["replayed_under_policy"] == V2, out["differences"]
    row["outcome"] = "blocked"                            # a row edited after the fact does not match
    assert replay.replay(row)["match"] is False
    gone = replay.replay({**_row(req, s, V2), "policy_version": "universal-risk-v0"})
    assert gone["replayable"] is False and "universal-risk-v0" in gone["reason"]
    with pytest.raises(ValueError):
        svc.decide(req, s, policy_version="universal-risk-v0")


def test_cr17_new_decisions_are_made_and_recorded_under_v2():
    assert svc.POLICY_VERSION == V2 and svc.POLICY_VERSIONS == (V1, V2) and svc.CREDIT_RULE_POLICIES == (V2,)
    assert svc.CREDIT_MIN_WIDTH_FRACTION == pytest.approx(1 / 3)
    req = structure(BEAR_CALL, direction="bearish")
    assert svc.decide(req, snap(last_close=25010.0, refs=listed(50)))["budget"]["reward_risk_rule"] == svc.RULE_CREDIT
    assert svc.stamp({}, {"correlation_id": "c", "decision_id": "d"})["risk_policy_version"] == V2


# ── CR-18: the card's size and the paper-trade route agree ───────────────────
BANK_EXPIRY = "2026-10-27"


def _credit_plan(short_px, long_px):
    """The captured BANKNIFTY board plan (bearish) with its legs replaced by a bear call spread (sell 55,000, buy
    55,200, lot 30: width Rs 6,000, so the minimum credit after costs is Rs 2,000)."""
    tp = copy.deepcopy(cf._fno_idea(cf._fno_top())["trade_plan"])
    legs = [dict(tp["instrument"]["legs"][0], side="sell", option_type="call", strike=55000, entry_price=short_px),
            dict(tp["instrument"]["legs"][0], side="buy", option_type="call", strike=55200, entry_price=long_px)]
    tp["instrument"]["legs"] = legs
    tp["strategy"]["family"] = "bear_call_spread"
    return tpm.finalize(tp)


def _body(tp, lots):
    body = copy.deepcopy(CONTRACT["body_with_levels"])
    body["family"] = "bear_call_spread"
    body["legs"] = [{k: leg.get(k) for k in ("kind", "side", "lot_size", "entry_price", "expiry", "strike", "option_type",
                                             "price_source")} | {"lots": lots} for leg in tp["instrument"]["legs"]]
    body["plan_ref"] = cf.plan_ref(tp)
    return body


@pytest.mark.parametrize("short_px,long_px,passes", [(300.0, 210.0, True), (300.0, 240.0, False)])
def test_cr18_plan_sizing_and_the_paper_trade_route_apply_the_same_credit_rule(world, monkeypatch, short_px, long_px, passes):
    monkeypatch.setattr(desk, "utcnow", lambda: CLOCK)     # the captured board's clock: after its 2026-10-21 signal
    tp = _credit_plan(short_px, long_px)
    assert tp["instrument"]["legs"][0]["expiry"] == BANK_EXPIRY and est.credit_terms(tp["instrument"]["legs"]) is not None
    asyncio.run(tpm.store(world.db, copy.deepcopy(tp), "system:ai-watchlist"))
    size = account_size(world, "user_a", tp["plan_id"])                  # user_a: the loosest profile (min R:R 0)
    assert size["policy_version"] == V2
    if passes:
        assert size["status"] == "sized" and size["lots"] == 1, size
        r = world.post("/api/desk/paper-trades", json=_body(tp, size["lots"]), headers=H("user_a"))
        assert r.status_code == 201, r.text
        [doc] = [d for d in world.db.cols["desk_paper_trades"].docs if d.get("trade_plan_id") == tp["plan_id"]]
        assert doc["risk_policy_version"] == V2
    else:
        assert size["status"] == "not_sizable" and "credit_too_small" in [b["code"] for b in size["blocking"]], size
        r = world.post("/api/desk/paper-trades", json=_body(tp, 1), headers=H("user_a"))
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "risk_blocked" and "credit_too_small" in [x["code"] for x in detail["reasons"]]
        assert detail["policy_version"] == V2
