"""Entry, stop and target levels (test_reports/strategy_levels_TESTCASES.md). Uses the real payoff engine (pure); numbers worked by hand."""
from __future__ import annotations

from datetime import date

import pytest

from services import strategy_levels as sl

TODAY = date(2026, 10, 1)


def leg(side, kind, strike, price, qty=1, lot=100, iv=20.0):
    return {"kind": "option", "side": side, "quantity": qty, "lot_size": lot, "entry_price": price, "expiry": "2026-10-27", "strike": strike, "option_type": kind, "underlying": "TST", "iv_pct": iv}


def body(legs, ref=100.0):
    return {"underlying": "TST", "reference_price": ref, "as_of": "2026-10-01", "legs": legs}


REFS = {"put_wall": 92.0, "call_wall": 108.0, "expected_move": 5.0}


def test_tc1_bull_call_spread_debit_levels():
    r = sl.compute(body([leg("buy", "call", 100, 5.0), leg("sell", "call", 110, 2.0)]), REFS, TODAY)
    assert r["valid"] is True and r["premium"]["kind"] == "debit"
    p = r["premium"]
    assert (p["entry"], p["planned_stop"], p["target_1"], p["target_2"]) == (3.0, 2.1, 3.9, 4.8)            # D=3: stop 0.7D, +30%, +60%
    assert p["risk_boundary"]["value"] == 0.0 and p["planned_stop_loss_per_unit"] == 0.9
    assert (r["max_profit_per_unit"], r["max_loss_per_unit"], r["risk_reward"]) == (7.0, 3.0, 2.33)
    assert r["max_profit_total"] == 700.0 and r["max_loss_total"] == -300.0
    u = r["underlying"]
    assert u["view"] == "bullish" and u["entry"] == 100.0
    # the thesis levels are the prices at which the STRUCTURE reaches its own stop and targets; the walls stay as a reference
    assert u["stop"] < 100.0 < u["target"] < u["target_2"] and u["wall_stop"] == 92.0 and u["wall_target"] == 108.0
    assert u["value_at_stop"] == pytest.approx(2.1, abs=0.02) and u["value_at_target"] == pytest.approx(3.9, abs=0.02)
    assert r["totals"] == {"planned_stop_loss": 90.0, "target_1_gain": 90.0, "target_2_gain": 180.0, "shares": 100, "note": "per share x the position's size (lot size x lots)"}
    assert r["greeks"]["review_when"].startswith("net delta falls below") and r["sent_to_broker"] is False
    assert any("not an executable price" in c for c in r["caveats"]) and any("no accuracy" in c for c in r["caveats"])


def test_tc2_bear_put_spread_mirrors_the_underlying_levels():
    r = sl.compute(body([leg("buy", "put", 100, 4.0), leg("sell", "put", 90, 1.5)]), REFS, TODAY)
    p, u = r["premium"], r["underlying"]
    assert p["kind"] == "debit" and p["entry"] == 2.5 and p["planned_stop"] == 1.75 and r["max_profit_per_unit"] == 7.5
    assert u["view"] == "bearish" and u["stop"] > 100.0 > u["target"] and u["wall_stop"] == 108.0 and u["wall_target"] == 92.0   # stop above, target below
    assert u["value_at_stop"] == pytest.approx(1.75, abs=0.02)
    assert r["greeks"]["review_when"].startswith("net delta rises above")


def test_tc3_bull_put_spread_credit_defined_risk():
    r = sl.compute(body([leg("sell", "put", 95, 3.0), leg("buy", "put", 90, 1.0)]), REFS, TODAY)
    p = r["premium"]
    assert p["kind"] == "credit" and p["entry"] == 2.0 and r["max_loss_per_unit"] == 3.0 and r["max_profit_per_unit"] == 2.0
    assert p["planned_stop"] == 3.5 and p["risk_boundary"]["value"] == 5.0                                    # C + min(C, 0.5 L) ; C + L
    assert (p["target_1"], p["target_2"]) == (1.0, 0.4) and p["planned_stop_loss_per_unit"] == 1.5


def test_tc4_an_undefined_risk_structure_is_rejected_by_the_engine_and_gets_no_levels():
    r = sl.compute(body([leg("sell", "call", 100, 4.0), leg("sell", "put", 100, 4.0)]), REFS, TODAY)
    assert r["valid"] is False and r["problems"][0]["code"] == "undefined_risk_not_supported" and "premium" not in r


def test_tc4b_iron_butterfly_is_a_defined_risk_credit():
    legs = [leg("sell", "call", 100, 4.0), leg("sell", "put", 100, 4.0), leg("buy", "call", 105, 3.0), leg("buy", "put", 95, 3.0)]
    r = sl.compute(body(legs), REFS, TODAY)
    p = r["premium"]                                                       # credit 8 - 6 = 2 per unit; width 5, so max loss 5 - 2 = 3
    assert r["valid"] and p["kind"] == "credit" and p["entry"] == 2.0 and r["max_profit_per_unit"] == 2.0 and r["max_loss_per_unit"] == 3.0
    assert p["planned_stop"] == 3.5 and p["risk_boundary"]["value"] == 5.0 and (p["target_1"], p["target_2"]) == (1.0, 0.4)
    assert r["underlying"]["view"] == "neutral" and r["underlying"]["range_low"] == 92.0 and r["underlying"]["range_high"] == 108.0


def test_tc5_a_wall_on_the_wrong_side_is_replaced_and_missing_inputs_leave_null():
    legs = [leg("buy", "call", 100, 5.0), leg("sell", "call", 110, 2.0)]
    r = sl.compute(body(legs), {"put_wall": 105.0, "call_wall": 95.0, "expected_move": 4.0}, TODAY)
    assert r["underlying"]["wall_stop"] == 96.0 and r["underlying"]["wall_target"] == 104.0                  # spot -/+ the expected move
    r = sl.compute(body(legs), {}, TODAY)
    assert r["underlying"]["wall_stop"] is None and r["underlying"]["wall_target"] is None                   # no walls and no move: no reference level, never a guess
    assert r["underlying"]["stop"] is not None and r["underlying"]["value_at_stop"] is not None             # the structure-based level does not need them


def test_tc6_per_unit_figures_do_not_depend_on_lots_or_lot_size():
    a = sl.compute(body([leg("buy", "call", 100, 5.0), leg("sell", "call", 110, 2.0)]), REFS, TODAY)
    b = sl.compute(body([leg("buy", "call", 100, 5.0, qty=2, lot=4525), leg("sell", "call", 110, 2.0, qty=2, lot=4525)]), REFS, TODAY)
    assert a["premium"] == b["premium"] and a["risk_reward"] == b["risk_reward"] and b["unit"]["shares"] == 9050
    assert b["max_loss_total"] == -3 * 9050


def test_tc7_invalid_structure_and_expiry_week_flag():
    bad = sl.compute(body([{**leg("buy", "call", 100, 5.0), "strike": None}]), REFS, TODAY)
    assert bad["valid"] is False and bad["problems"] and "premium" not in bad
    near = body([leg("buy", "call", 100, 5.0), leg("sell", "call", 110, 2.0)])
    near["as_of"] = "2026-10-25"
    r = sl.compute(near, REFS, date(2026, 10, 25))
    assert r["valid"] and any(f["code"] == "expiry_week" for f in r["flags"]) and r["days_to_expiry"] == 2


def test_scenarios_reprice_the_legs_and_attach_no_probabilities():
    r = sl.compute(body([leg("buy", "call", 100, 5.0), leg("sell", "call", 110, 2.0)]), REFS, TODAY)
    by = {s["name"]: s for s in r["scenarios"]}
    assert list(by) == ["Bullish", "Sideways", "Bearish", "Expiry day, small rise"]
    assert by["Expiry day, small rise"]["underlying"] == 101.0 and by["Expiry day, small rise"]["date"] == "2026-10-27"
    assert by["Expiry day, small rise"]["pnl_per_unit"] == pytest.approx(-2.0, abs=0.01)         # at expiry: (101 - 100) - 3 debit
    assert by["Bullish"]["pnl_per_unit"] > by["Sideways"]["pnl_per_unit"] > by["Bearish"]["pnl_per_unit"]
    assert all("probability" not in s for s in r["scenarios"]) and "expected_pnl" not in r and r["iv_rank"] is None and "history" in r["iv_note"]


def test_tc8_the_route_answers_200_with_levels_and_422_on_a_bad_body(monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from routes import strategy_plan as route

    async def fake_user(request: Request):
        return {"user_id": "u1"}

    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    c = TestClient(app)
    ok = c.post("/api/desk/strategy/levels", json={"payoff": body([leg("buy", "call", 100, 5.0), leg("sell", "call", 110, 2.0)]), "refs": REFS})
    assert ok.status_code == 200 and ok.json()["premium"]["entry"] == 3.0 and ok.json()["valid"] is True
    assert c.post("/api/desk/strategy/levels", json={"refs": {}}).status_code == 422
    assert c.post("/api/desk/strategy/levels", data="not json").status_code == 422


def test_legs_and_cost_breakdown_are_returned_with_the_levels():
    r = sl.compute(body([leg("buy", "put", 100, 4.0), leg("sell", "put", 90, 1.5)]), REFS, TODAY)
    assert [(l["side"], l["option_type"], l["strike"], l["entry_price"]) for l in r["legs"]] == [("buy", "put", 100, 4.0), ("sell", "put", 90, 1.5)]
    assert r["legs"][0]["delta"] < 0 < r["legs"][1]["delta"] and r["legs"][0]["theta"] is not None
    c = r["costs"]
    assert c["max_loss_gross_total"] == -250.0 and c["capital_at_risk"] is not None and c["capital_at_risk"] >= 250.0 and c["round_trip"] is not None
    assert c["capital_at_risk_basis"] and "worst net loss" in c["capital_at_risk_basis"]


def test_a_butterfly_keeps_its_wall_range_and_is_not_solved():
    legs = [leg("sell", "call", 100, 4.0), leg("sell", "put", 100, 4.0), leg("buy", "call", 105, 3.0), leg("buy", "put", 95, 3.0)]
    r = sl.compute(body(legs), REFS, TODAY)
    assert r["underlying"]["view"] == "neutral" and "stop" not in r["underlying"] and r["underlying"]["range_low"] == 92.0
