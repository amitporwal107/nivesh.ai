"""The canonical TradePlan (services/strategy_plan/trade_plan.py): TP-1 … TP-11 of
test_reports/p2_trade_plan_lifecycle_TESTCASES.md.

The plans are built by the real plan builder (services/strategy_plan/plan.build_plan) from the MOCK sources of
tests/test_strategy_plan.py, and by the real strategy-levels engine for the F&O board idea, which is a REAL staging
capture (frontend-v5/e2e/fixtures/desk-strategy-top.json, POST /api/desk/strategy/top on 2026-10-21). The store runs
against the in-memory Mongo stand-in of tests/test_desk_trading.py.
"""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import date
from pathlib import Path

import pytest

from services import desk_trading as desk
from services import strategy_levels
from services import trade_lifecycle as lc
from services.strategy_plan import trade_plan as tpm
from tests.test_desk_trading import FakeDb
from tests.test_strategy_plan import build, bucket, cand, src_ok, world, ASOF

FIXTURES = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures"
TOP = json.loads((FIXTURES / "desk-strategy-top.json").read_text())
IDEA = TOP["classes"]["index_options"]["ideas"][0]          # BANKNIFTY bear put spread, chain 2026-10-21


def pick_bucket(name="pre_breakout", *, entry=1413.21, stop=1375.16, atr=25.36709576770533, swing_low=1291.0, close=1403.0):
    """A scanner snapshot shaped as sources.scanner_snapshot builds it, with the REAL ICICIBANK 26 Oct pick figures
    (B §2b): entry 1413.21, stop 1375.16 = entry − 1.5 × ATR 25.367."""
    item = {"nse_symbol": "RELIANCE", "trigger_price": 1411.8, "stop_price": stop, "close_price": close}
    pick = {"stage": "EARLY_BREAKOUT", "entry_price": entry, "stoploss": stop, "target_price": 1489.31, "final_score": 0.71,
            "signal_date": ASOF, "atr_14": atr, "swing_low_20": swing_low, "timeframe_days_min": 5, "timeframe_days_max": 15}
    return src_ok({"bucket": name, "item": item, "pick": pick}, "MOCK positional watchlist", ASOF, "mock-classifier")


def cash_tp(plan):
    return next(c for c in plan["candidates"] if c["segment"] == "cash")["trade_plan"]


# ── TP-1 / TP-2: identity ────────────────────────────────────────────────────
def test_the_same_inputs_give_the_same_plan_id_and_created_at_is_not_hashed():
    a, b = cash_tp(build(instrument="cash")), cash_tp(build(instrument="cash"))
    assert a["plan_id"] == b["plan_id"] and a["plan_id"].startswith("tp_")
    stamped = {**a, "created_at": "2030-01-01", "version": 9, "owners": ["x"], "source": {"kind": "other"}}
    assert tpm.finalize(copy.deepcopy(stamped))["plan_id"] == a["plan_id"]


@pytest.mark.parametrize("path,value", [(("entry", "price"), 1201.0), (("stop", "price"), 1161.0), (("targets", 1, "price"), 1281.0)])
def test_any_level_change_is_a_different_plan(path, value):
    a = cash_tp(build(instrument="cash"))
    b = copy.deepcopy(a)
    node = b
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    assert tpm.finalize(b)["plan_id"] != a["plan_id"]


# ── TP-3 / TP-4: the stop's method (N13) ─────────────────────────────────────
def test_the_scanner_stop_is_labelled_1_5_atr_from_the_pick_never_2x():
    plan = build(world(scanner_bucket=pick_bucket()), instrument="cash")
    tp = cash_tp(plan)
    assert tp["stop"]["price"] == 1375.16 and tp["stop"]["method"] == "atr" and tp["stop"]["atr_multiple"] == 1.5
    assert tp["stop"]["measured_from"] == 1413.21 and tp["stop"]["distance_atr"] == 1.5
    assert "1.5 x ATR(14) below 1413.21" in tp["stop"]["rationale"]
    assert "2 x ATR below" not in json.dumps(plan)                    # the old fixed label is gone everywhere


def test_a_structural_pick_stop_says_structural():
    sw = 1400.0
    plan = build(world(scanner_bucket=pick_bucket(stop=round(sw * 0.995, 2), swing_low=sw)), instrument="cash")
    st = cash_tp(plan)["stop"]
    assert st["method"] == "structural" and st["swing_ref"] == sw and st["atr_multiple"] is None


def test_a_watchlist_stop_without_a_pick_records_the_bucket_rule():
    tp = cash_tp(build(world(scanner_bucket=bucket("breakout_confirmed", stop=1160.0)), instrument="cash"))
    assert tp["stop"]["method"] == "atr" and tp["stop"]["atr_multiple"] == 1.5 and tp["stop"]["measured_from"] == 1195.0
    # a trend-continuation stop is measured from the 20-day EMA; a row that does not carry it is labelled unknown, not guessed
    tc = cash_tp(build(world(scanner_bucket=bucket("trend_continuation", stop=1160.0)), instrument="cash"))
    assert tc["stop"]["method"] == "unknown"


# ── TP-5 / TP-6: targets in R, order types ───────────────────────────────────
def test_targets_carry_r_multiples_that_match_their_prices():
    tp = cash_tp(build(instrument="cash"))
    e, s = tp["entry"]["price"], tp["stop"]["price"]
    R = e - s
    assert tp["r_per_unit"] == round(R, 2)
    by = {t["name"]: t for t in tp["targets"]}
    assert (by["base"]["r_multiple"], by["optimistic"]["r_multiple"]) == (2.0, 3.0)
    for t in tp["targets"]:
        assert round((t["price"] - e) / R, 2) == t["r_multiple"]
    assert [t["name"] for t in tp["targets"] if t["primary"]] == ["base"]
    assert tpm.validate(tp) == []


@pytest.mark.parametrize("entry,close,bucket_,stage,want", [
    (1413.21, 1403.0, "pre_breakout", "EARLY_BREAKOUT", ("stop_trigger", "break_above")),
    (316.89, 344.40, "true_accumulation", "ACCUMULATION", ("limit_pullback", "pullback_to")),    # FEDERALBNK 26 Oct
    (1200.0, 1200.0, "breakout_confirmed", "BREAKOUT", ("at_close", "at_once")),
    (1200.0, None, None, "ACCUMULATION", ("limit_pullback", "pullback_to")),
    (1200.0, None, "pre_breakout", None, ("stop_trigger", "break_above")),
])
def test_order_type_follows_the_desk_rule(entry, close, bucket_, stage, want):
    ot = tpm.order_type_for(entry, close, bucket=bucket_, stage=stage)
    assert (ot, tpm.DESK_ENTRY_RULE[ot]) == want


def test_a_setup_waiting_for_its_trigger_is_a_wait_plan_with_a_buy_stop():
    tp = cash_tp(build(world(scanner_bucket=pick_bucket()), instrument="cash"))
    assert tp["entry"]["price"] == 1413.21 and tp["entry"]["order_type"] == "stop_trigger"
    assert tp["entry"]["desk_entry_rule"] == "break_above" and tp["entry"]["valid_for_sessions"] == 5
    assert tp["eligibility"]["state"] == "WAIT_FOR_CONFIRMATION" and tp["eligibility"]["paper_eligible"]
    assert tp["setup"]["signal_date"] == ASOF and tp["setup"]["stage"] == "EARLY_BREAKOUT"


# ── TP-7: costs on the desk cost card ────────────────────────────────────────
def test_costs_are_the_desk_cost_card_at_the_stop():
    tp = cash_tp(build(instrument="cash"))
    c = tp["costs"]
    assert c["model"] == "desk-cost-v2"
    model = dict(desk.COST_MODEL, slippage_pct_per_side=0.05, brokerage_rs_per_side=20.0)
    assert c["breakdown_at_stop"] == desk.round_trip_breakdown(c["units"], tp["entry"]["price"], tp["stop"]["price"], model,
                                                               segment="equity_delivery", long=True)


# ── TP-8: proposed vs approved ───────────────────────────────────────────────
def test_a_fresh_plan_is_proposed_and_its_status_is_derived_from_trades():
    tp = cash_tp(build(instrument="cash"))
    assert tp["lifecycle"]["status"] == "proposed" and tp["lifecycle"]["state"] == "TRADE_ELIGIBLE"
    assert lc.plan_status([]) == "proposed" and lc.plan_status(["POSITION_OPEN"]) == "open"


def test_no_trade_and_insufficient_data_are_not_tradeable():
    e = tpm.eligibility("no_trade", [{"code": "reward_risk_below_minimum", "message": "x"}], conditional_entry=False)
    assert (e["state"], e["eligible"], e["paper_eligible"]) == ("REJECTED", False, False)
    assert tpm.eligibility("insufficient_data", [], conditional_entry=False)["state"] == "NO_SETUP"
    assert not tpm.eligibility("wait", [], conditional_entry=False)["paper_eligible"]    # a structure cannot wait


# ── TP-9 / TP-10: the store ──────────────────────────────────────────────────
def run(coro):
    return asyncio.run(coro)


def test_a_plan_is_stored_once_and_its_owners_grow():
    db = FakeDb()
    tp = cash_tp(build(instrument="cash"))
    first = run(tpm.store(db, copy.deepcopy(tp), "user_a"))
    writes = db["trade_plans"].writes
    again = run(tpm.store(db, copy.deepcopy(tp), "user_a"))
    assert db["trade_plans"].writes == writes and again["_id"] == first["_id"] == tp["plan_id"]
    run(tpm.store(db, copy.deepcopy(tp), "user_b"))
    [doc] = db["trade_plans"].docs
    assert doc["owners"] == ["user_a", "user_b"] and doc["version"] == 1 and doc["supersedes"] is None
    assert run(tpm.load(db, tp["plan_id"], "user_b"))["_id"] == tp["plan_id"]
    assert run(tpm.load(db, tp["plan_id"], "user_c")) is None                          # not theirs
    assert run(tpm.load(db, "not-a-plan", "user_a")) is None


def test_a_changed_plan_of_the_same_lineage_is_the_next_version_and_is_revalidated():
    db = FakeDb()
    v1 = cash_tp(build(instrument="cash"))
    run(tpm.store(db, copy.deepcopy(v1), "user_a"))
    db.trades.docs.append({"_id": "t1", "trade_plan_id": v1["plan_id"]})                # v1 was traded (approved)
    v2 = copy.deepcopy(v1)
    v2["stop"]["price"] = 1170.0
    v2["r_per_unit"] = 30.0
    for t in v2["targets"]:
        t["r_multiple"] = round((t["price"] - 1200.0) / 30.0, 2)
    v2 = tpm.finalize(v2)
    doc2 = run(tpm.store(db, v2, "user_a"))
    assert doc2["version"] == 2 and doc2["supersedes"] == v1["plan_id"]
    assert doc2["revalidation"]["ok"] and doc2["revalidation"]["after_approval"]
    bad = copy.deepcopy(v2)
    bad["stop"]["price"] = 1250.0                                                       # above the entry: invalid
    bad = tpm.finalize(bad)
    doc3 = run(tpm.store(db, bad, "user_a"))
    assert doc3["version"] == 3 and not doc3["revalidation"]["ok"]
    assert doc3["eligibility"]["state"] == "REJECTED" and not doc3["eligibility"]["paper_eligible"]
    assert "stop_side" in [p["code"] for p in doc3["revalidation"]["problems"]]


# ── TP-11: the options exit plan from strategy_levels ────────────────────────
def test_an_fno_board_idea_plan_carries_the_levels_engine_exit_plan():
    refs = {"put_wall": None, "call_wall": None, "expected_move": 859.0}
    tp = tpm.from_fno_idea(IDEA, board_rules_version=TOP["rules_version"], refs=refs, today=date(2026, 10, 21))
    from services import ai_watchlist_build as b
    want = strategy_levels.compute(b.payoff_request_for(IDEA), refs, date(2026, 10, 21))
    opt = tp["exit_plan"]["options"]
    assert opt["status"] == "ok" and opt["premium_stop"] == want["premium"]["planned_stop"]
    assert (opt["t1"], opt["t2"]) == (want["premium"]["target_1"], want["premium"]["target_2"])
    assert tp["stop"]["price"] == want["underlying"]["stop"] and tp["stop"]["method"] == "underlying"
    assert tpm.primary_target(tp)["price"] == want["underlying"]["target"]
    assert tp["strategy"]["direction"] == "bearish" and tp["entry"]["order_type"] == "at_premium"
    assert tp["costs"]["model"] == "desk-cost-v2" and tp["costs"]["breakdown_round_trip_at_entry"]["total"] > 0
    assert tp["eligibility"]["paper_eligible"] and tpm.validate(tp) == []


def test_a_builder_options_candidate_plan_records_the_builders_own_levels():
    plan = build(instrument="all")
    c = next(x for x in plan["candidates"] if x["segment"] == "options" and x.get("trade_plan"))
    tp = c["trade_plan"]
    assert tp["stop"]["price"] == c["invalidation"]["technical"]["price"]
    assert tpm.primary_target(tp)["price"] == next(t["price"] for t in c["targets"] if t["name"] == "base")
    assert tp["exit_plan"]["options"]["status"] == "ok"                                 # the premium levels still travel
    assert plan["trade_plans"][c["id"]] == tp["plan_id"]


def test_a_level_the_engine_cannot_work_out_is_reported_not_dropped(monkeypatch):
    def boom(*a, **k):
        raise ValueError("engine failed")
    monkeypatch.setattr(strategy_levels, "compute", boom)
    tp = tpm.from_fno_idea(IDEA, board_rules_version="v", refs={}, today=date(2026, 10, 21))
    assert tp["exit_plan"]["options"]["status"] == "unavailable" and "ValueError" in tp["exit_plan"]["options"]["reason"]
    assert tp["stop"]["price"] is None and tp["stop"]["method"] == "premium"


# ── what a paper trade must carry ────────────────────────────────────────────
def test_cash_and_strategy_mismatch_checks():
    tp = cash_tp(build(instrument="cash"))
    body = {"symbol": "RELIANCE", "entry_price": tp["entry"]["price"], "stop_price": tp["stop"]["price"],
            "target_price": tpm.primary_target(tp)["price"], "entry_rule": "at_once"}
    assert tpm.cash_mismatches(tp, body) == []
    assert tpm.cash_mismatches(tp, {**body, "stop_price": 1150.0}) == ["stop_price: the plan has 1160.0, the request 1150.0"]
    fno = tpm.from_fno_idea(IDEA, board_rules_version="v", refs={"expected_move": 859.0}, today=date(2026, 10, 21))
    sbody = {"underlying": "BANKNIFTY", "direction": "bearish", "family": "bear_put_spread",
             "stop_underlying": fno["stop"]["price"], "target_underlying": tpm.primary_target(fno)["price"],
             "legs": [{"side": l["side"], "strike": l["strike"], "option_type": l["option_type"], "expiry": l["expiry"],
                       "lots": l["quantity"], "lot_size": l["lot_size"], "entry_price": l["entry_price"]} for l in IDEA["legs"]]}
    assert tpm.strategy_mismatches(fno, sbody) == []
    sbody["legs"][0]["entry_price"] = 999.0
    assert tpm.strategy_mismatches(fno, sbody) == ["legs: the request's legs are not the plan's"]
