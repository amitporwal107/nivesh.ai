"""Lifecycle and TradePlan references through the real paper-trade route (routes/desk_trading.py): LC-3 … LC-8, LC-11,
LC-12, PR-1 … PR-5 and OP-1 of test_reports/p2_trade_plan_lifecycle_TESTCASES.md.

Runs the route, the validator, the exit simulation and the account with the in-memory stand-ins of
tests/test_desk_trading.py. MOCK — not real data: the FIXA / RELIANCE bars. The F&O idea and its levels are the REAL
2026-10-21 staging capture the Phase 0 contract test uses (frontend-v5/e2e/fixtures/desk-strategy-top.json).
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date

import pytest

from services import ai_watchlist_build as awb
from services import desk_strategy_trades as strat
from services import risk_controls as rc
from services import trade_lifecycle as lc
from services.strategy_plan import trade_plan as tpm
from tests.test_desk_trading import A, B, TRADES_URL, api, bar, trades, world  # noqa: F401  (fixtures)
from tests.test_fno_idea_paper_trade_contract import CLOCK, CONTRACT, IDEA, TOP, exchange_lots  # noqa: F401  (fixture)
from tests.test_strategy_plan import build, world as plan_world


def run(coro):
    return asyncio.run(coro)


def states(doc):
    return [(e["from"], e["to"]) for e in doc.get("transitions") or []]


def cash_plan(**inputs):
    plan = build(plan_world(), instrument="cash", **inputs)
    return next(c for c in plan["candidates"] if c["segment"] == "cash")["trade_plan"]


@pytest.fixture
def reliance(world):
    # MOCK — not real data: RELIANCE ranges that contain the plan's 1200 entry, so an at-once entry is tradable.
    world.add("RELIANCE", bar("2026-10-09", 1210.0, 1190.0, 1200.0), bar("2026-10-12", 1212.0, 1188.0, 1201.0))
    return world


def plan_body(tp, **over):
    prim = tpm.primary_target(tp)
    body = {"symbol": "RELIANCE", "quantity": 5, "entry_price": tp["entry"]["price"], "stop_price": tp["stop"]["price"],
            "target_price": prim["price"], "entry_rule": tp["entry"]["desk_entry_rule"],
            "plan_ref": {"plan_id": tp["plan_id"], "candidate_id": tp["strategy"]["candidate_id"], "rules_version": tp["rules_version"]}}
    body.update(over)
    return body


# ── PR-1 / LC-3 / LC-12: a cash trade at its plan's levels ───────────────────
def test_a_cash_trade_at_its_plans_levels_opens_with_its_plan_ref_and_lifecycle(api, reliance):
    tp = cash_plan()
    run(tpm.store(reliance.db, copy.deepcopy(tp), "user_a"))
    got = api.get(f"/api/desk/trade-plans/{tp['plan_id']}", headers=A).json()
    assert got["lifecycle"]["status"] == "proposed" and got["plan"]["lifecycle"]["status"] == "proposed"
    r = api.post(TRADES_URL, json=plan_body(tp), headers=A)
    assert r.status_code == 201, r.text
    [doc] = reliance.db.trades.docs
    assert doc["trade_plan_id"] == tp["plan_id"] and doc["plan_ref"]["candidate_id"] == "cash:breakout_continuation"
    assert doc["plan_levels"] == tpm.canonical_levels(tp)
    assert doc["state"] == "POSITION_OPEN" and states(doc) == [(None, "TRADE_ELIGIBLE"), ("TRADE_ELIGIBLE", "ENTRY_TRIGGERED"),
                                                               ("ENTRY_TRIGGERED", "POSITION_OPEN")]
    first = doc["transitions"][0]
    assert first["source"] == "trade_plan" and first["levels"]["stop"] == tp["stop"]["price"] and first["quantity"] == 5
    assert first["est_costs_rs"] is not None and first["rule_version"] == "desk-paper-v2"
    t = r.json()["trade"]
    assert t["state"] == "POSITION_OPEN" and t["plan_ref"]["plan_id"] == tp["plan_id"]
    assert api.get(f"/api/desk/trade-plans/{tp['plan_id']}", headers=A).json()["lifecycle"]["status"] == "open"


# ── PR-2 / LC-8: levels that are not the plan's ──────────────────────────────
def test_levels_that_differ_from_the_plan_are_refused_and_recorded_as_rejected(api, reliance):
    tp = cash_plan()
    run(tpm.store(reliance.db, copy.deepcopy(tp), "user_a"))
    r = api.post(TRADES_URL, json=plan_body(tp, stop_price=1150.0), headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_levels_mismatch"
    assert "stop_price" in r.json()["detail"]["mismatches"][0]
    assert reliance.db.trades.docs == []
    row = reliance.db[rc.DECISIONS].docs[-1]
    assert row["detail"]["lifecycle"]["to"] == "REJECTED" and row["detail"]["lifecycle"]["plan_id"] == tp["plan_id"]
    [stored] = reliance.db["trade_plans"].docs
    assert stored["events"][-1]["to"] == "REJECTED" and stored["events"][-1]["rejection_reasons"] == ["plan_levels_mismatch"]


# ── PR-3: unknown plan, another user's plan ──────────────────────────────────
def test_an_unknown_or_someone_elses_plan_is_404(api, reliance):
    tp = cash_plan()
    r = api.post(TRADES_URL, json=plan_body(tp), headers=A)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "plan_not_found"
    run(tpm.store(reliance.db, copy.deepcopy(tp), "user_b"))                  # built by user B with B's inputs
    assert api.post(TRADES_URL, json=plan_body(tp), headers=A).status_code == 404
    assert api.get(f"/api/desk/trade-plans/{tp['plan_id']}", headers=A).status_code == 404
    assert api.post(TRADES_URL, json=plan_body(tp, plan_ref={"plan_id": 7}), headers=A).json()["detail"]["code"] == "invalid_plan_ref"
    assert reliance.db.trades.docs == []


def test_a_system_built_plan_is_usable_by_any_signed_in_user(api, reliance):
    tp = cash_plan()
    run(tpm.store(reliance.db, copy.deepcopy(tp), "system:ai-watchlist"))
    assert api.post(TRADES_URL, json=plan_body(tp), headers=B).status_code == 201


# ── PR-4: a plan that is not eligible ────────────────────────────────────────
def test_a_no_trade_plan_cannot_be_paper_traded(api, reliance):
    tp = cash_plan(min_reward_risk=9.0)                       # the reward : risk gate makes it no_trade
    assert tp["eligibility"]["state"] == "REJECTED"
    run(tpm.store(reliance.db, copy.deepcopy(tp), "user_a"))
    r = api.post(TRADES_URL, json=plan_body(tp), headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_not_eligible"
    assert "below the minimum" in r.json()["detail"]["message"]
    assert reliance.db.trades.docs == []


def test_a_ref_that_names_another_candidate_is_refused(api, reliance):
    tp = cash_plan()
    run(tpm.store(reliance.db, copy.deepcopy(tp), "user_a"))
    body = plan_body(tp)
    body["plan_ref"]["candidate_id"] = "cash:other"
    assert api.post(TRADES_URL, json=body, headers=A).json()["detail"]["code"] == "plan_ref_mismatch"


# ── PR-5 / OP-1 / LC-7: a strategy trade at its plan's levels ────────────────
def fno_plan():
    return tpm.from_fno_idea(IDEA, board_rules_version=TOP["rules_version"], refs=awb.levels_refs_for(TOP, IDEA["underlying"]),
                             today=date(2026, 10, 21))


def test_a_strategy_trade_at_its_plans_legs_and_levels_opens_and_stores_the_premium_exit_plan(api, world):
    world.now = CLOCK
    tp = fno_plan()
    run(tpm.store(world.db, copy.deepcopy(tp), "system:ai-watchlist"))
    body = {**copy.deepcopy(CONTRACT["body_with_levels"]), "plan_ref": {"plan_id": tp["plan_id"]}}
    r = api.post(TRADES_URL, json=body, headers=A)
    assert r.status_code == 201, r.text
    [doc] = world.db.trades.docs
    assert doc["trade_plan_id"] == tp["plan_id"] and doc["state"] == "POSITION_OPEN"
    opt = doc["exit_plan"]["options"]
    assert opt["status"] == "ok" and opt["premium_stop"] == tp["exit_plan"]["options"]["premium_stop"]
    assert "feat/p2-exits-backtest" in opt["evaluation"]
    assert doc["entry_record_hash"] == strat.record_hash(doc)                     # the immutable core is unchanged


def test_a_strategy_leg_that_is_not_the_plans_is_refused(api, world):
    world.now = CLOCK
    tp = fno_plan()
    run(tpm.store(world.db, copy.deepcopy(tp), "system:ai-watchlist"))
    body = {**copy.deepcopy(CONTRACT["body_with_levels"]), "plan_ref": {"plan_id": tp["plan_id"]}}
    body["legs"][1]["entry_price"] = 150.0
    r = api.post(TRADES_URL, json=body, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_levels_mismatch"


def test_without_a_plan_a_strategy_trade_still_stores_the_engines_premium_levels(api, world):
    world.now = CLOCK
    r = api.post(TRADES_URL, json=copy.deepcopy(CONTRACT["body_without_levels"]), headers=A)
    assert r.status_code == 201, r.text
    [doc] = world.db.trades.docs
    want = tpm.options_exit(tpm.compute_levels("BANKNIFTY", IDEA["reference_price"], "2026-10-21", [
        {**l, "quantity": l["quantity"]} for l in IDEA["legs"]], {"put_wall": None, "call_wall": None, "expected_move": None},
        date(2026, 10, 22))[0], as_of="2026-10-21")
    assert doc["exit_plan"]["options"]["premium_stop"] == want["premium_stop"] and doc["exit_plan"]["source"] == "entry"


def test_closing_a_strategy_trade_writes_exit_pending_and_closed_in_the_same_update(world):
    world.now = CLOCK
    doc = strat.new_strategy_trade("user_a", copy.deepcopy(CONTRACT["body_with_levels"]), now=CLOCK)
    from services import desk_trading as svc
    svc.open_lifecycle(doc)
    run(world.db.trades.insert_one(doc))
    sim = {"legs": [{"mark": 400.0, "mark_date": date(2026, 10, 23), "mark_basis": "settle"},
                    {"mark": 120.0, "mark_date": date(2026, 10, 23), "mark_basis": "settle"}],
           "gross_pnl_rs": -330.0, "mfe_rs": 0.0, "mae_rs": -330.0, "observations": 1, "held_sessions": 1, "flags": [],
           "checked_through": date(2026, 10, 23)}
    stored, mine = run(strat.close_strategy_trade(world.db, doc, exit_reason="manual", exit_session=date(2026, 10, 23),
                                                  exit_note="by hand", sim=sim))
    assert mine and stored["state"] == "CLOSED"
    [saved] = world.db.trades.docs
    assert states(saved)[-2:] == [("POSITION_OPEN", "EXIT_PENDING"), ("EXIT_PENDING", "CLOSED")]
    assert saved["transitions"][-1]["fill_price"] == [400.0, 120.0] and saved["transitions"][-1]["exit_reason"] == "manual"
    again, mine2 = run(strat.close_strategy_trade(world.db, doc, exit_reason="manual", exit_session=date(2026, 10, 23),
                                                  exit_note="by hand", sim=sim))
    assert not mine2 and len(world.db.trades.docs[0]["transitions"]) == 5               # a repeat writes nothing


# ── LC-4 / LC-5 / LC-6: fills and exits on read ──────────────────────────────
def test_a_conditional_entry_reached_on_read_is_recorded_once(api, world):
    r = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 103.0, "stop_price": 95.0,
                                   "target_price": 130.0, "entry_rule": "break_above"}, headers=A)
    assert r.status_code == 201, r.text
    assert world.db.trades.docs[0]["state"] == "TRADE_ELIGIBLE"
    world.add("FIXA", bar("2026-10-13", 104.0, 99.0, 103.5))
    trades(api)
    doc = world.db.trades.docs[0]
    assert doc["state"] == "POSITION_OPEN" and states(doc)[1:] == [("TRADE_ELIGIBLE", "ENTRY_TRIGGERED"), ("ENTRY_TRIGGERED", "POSITION_OPEN")]
    assert doc["transitions"][-1]["fill_price"] == 103.0 and doc["transitions"][-1]["session"] == "2026-10-13"
    trades(api)
    assert len(world.db.trades.docs[0]["transitions"]) == 3                             # the second read wrote nothing


def test_a_stop_exit_on_read_closes_once_with_its_events_and_a_later_close_adds_none(api, world):
    t = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0,
                                   "target_price": 110.0}, headers=A).json()["trade"]
    world.add("FIXA", bar("2026-10-13", 101.0, 94.0, 95.5))
    trades(api)
    trades(api)
    doc = world.db.trades.docs[0]
    assert doc["status"] == "closed" and doc["state"] == "CLOSED" and doc["exit_reason"] == "stop"
    assert states(doc)[-2:] == [("POSITION_OPEN", "EXIT_PENDING"), ("EXIT_PENDING", "CLOSED")] and len(doc["transitions"]) == 5
    assert doc["transitions"][-1]["fill_price"] == 95.0 and doc["transitions"][-1]["actor"] == "exit_rule"
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A)
    assert r.status_code == 409 and len(world.db.trades.docs[0]["transitions"]) == 5
    ok, why = lc.consistent(world.db.trades.docs[0])
    assert ok, why


def test_an_entry_never_reached_closes_from_eligible(api, world):
    api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 90.0, "stop_price": 85.0,
                               "target_price": 120.0, "entry_rule": "pullback_to", "entry_window_sessions": 1}, headers=A)
    world.add("FIXA", bar("2026-10-13", 104.0, 99.0, 103.5))
    trades(api)
    doc = world.db.trades.docs[0]
    assert doc["exit_reason"] == "entry_not_reached" and states(doc) == [(None, "TRADE_ELIGIBLE"), ("TRADE_ELIGIBLE", "CLOSED")]


def test_a_manual_close_is_actor_user(api, world):
    t = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0,
                                   "target_price": 110.0}, headers=A).json()["trade"]
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": 102.0}, headers=A)
    assert r.status_code == 200 and r.json()["trade"]["state"] == "CLOSED"
    last = world.db.trades.docs[0]["transitions"][-1]
    assert (last["actor"], last["source"], last["fill_price"], last["exit_reason"]) == ("user_a", "user", 102.0, "manual")


# ── LC-8: a refused open is a REJECTED event on the refusal's record ─────────
def test_a_duplicate_open_is_recorded_as_rejected(api, world):
    body = {"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0}
    assert api.post(TRADES_URL, json=body, headers=A).status_code == 201
    assert api.post(TRADES_URL, json=body, headers=A).status_code == 409
    row = world.db[rc.DECISIONS].docs[-1]
    assert row["detail"]["lifecycle"]["to"] == "REJECTED" and row["detail"]["lifecycle"]["rejection_reasons"] == ["duplicate_open_trade"]


# ── LC-11: a trade stored before the lifecycle ───────────────────────────────
def test_a_legacy_trade_without_state_closes_with_its_derived_history(api, world):
    t = api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0,
                                   "target_price": 110.0}, headers=A).json()["trade"]
    legacy = world.db.trades.docs[0]
    legacy.pop("state")
    legacy.pop("transitions")
    world.add("FIXA", bar("2026-10-13", 111.0, 99.0, 110.5))
    trades(api)
    doc = world.db.trades.docs[0]
    assert doc["exit_reason"] == "target" and doc["state"] == "CLOSED"
    assert [e["derived"] for e in doc["transitions"]] == [True, True, True, False, False]
    assert lc.consistent(doc) == (True, [])
    assert t["id"] == doc["_id"]


# ── LC-5 / LC-9: a close worked out from a stale copy re-reads the stored state and duplicates nothing ──
def test_a_close_from_a_stale_copy_rereads_the_state_and_writes_no_duplicate_events(api, world):
    from services import desk_trading as svc
    api.post(TRADES_URL, json={"symbol": "FIXA", "quantity": 10, "entry_price": 103.0, "stop_price": 95.0,
                               "target_price": 130.0, "entry_rule": "break_above"}, headers=A)
    stale = copy.deepcopy(world.db.trades.docs[0])                    # TRADE_ELIGIBLE, as a racing reader saw it
    world.add("FIXA", bar("2026-10-13", 104.0, 99.0, 103.5))
    trades(api)                                                          # another read records the entry fill first
    assert world.db.trades.docs[0]["state"] == "POSITION_OPEN"
    sim = {"entry_status": "reached", "entry_session": date(2026, 10, 13), "sim_entry_price": 103.0, "observations": 1,
           "held_sessions": 1, "checked_through": date(2026, 10, 13), "max_high": 104.0, "min_low": 99.0, "flags": [], "exit": None}
    stored, mine = run(svc.close_trade(world.db, stale, exit_reason="manual", exit_price=103.5,
                                       exit_session=date(2026, 10, 13), sim=sim))
    assert mine and stored["state"] == "CLOSED"
    doc = world.db.trades.docs[0]
    assert [e["to"] for e in doc["transitions"]] == ["TRADE_ELIGIBLE", "ENTRY_TRIGGERED", "POSITION_OPEN", "EXIT_PENDING", "CLOSED"]
    assert lc.consistent(doc) == (True, [])
