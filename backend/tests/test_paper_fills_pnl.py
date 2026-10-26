"""Paper fills, P&L and costs — release gates 3 and 4 (docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md §9; criteria group
0.2 of docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md).

TESTCASES: test_reports/paper_fills_pnl_TESTCASES.md (FM = the fill model written in services/desk_trading.py, P = P&L
from the simulated fill, C = costs in sizing, risk reporting and realised P&L, R = reconciliation invariants).
Defects reproduced on origin/dev 5b6b3cfd by the study's probes (docs/ai_research/guidelines_gap_study_20261027/probe/):
gap_entry.py (₹1,000 booked against ₹600 from the fill) and stale_entry.py (FEDERALBNK booked at once at 316.89).

Harness: the desk's own (tests/test_desk_trading.py `world`/`api`: in-memory Mongo, a fake data platform serving
GET /v1/prices/eod/{symbol}, the clock fixed at 2026-10-12 10:30 IST unless a test moves it). Bodies are the shapes the
Top 10 / AI watchlist / Scanner "Add paper trade" sends.

Data: the FEDERALBNK 26 Oct 2026 bar (open 341.00, high 344.80, low 337.20, close 344.40) is the real NSE end-of-day bar
quoted in study B §7c; the 27 Oct bar is HYPOTHETICAL. Everything else (FIX*, Example A's levels) is MOCK — not real data.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List

import pytest

from routes import positional as positional_route
from services import desk_strategy_trades as strat
from services import desk_trading as svc
from services import paper_account as acct
from services import risk_controls as rc
from services.strategy_plan import candidates as cd
from tests.test_desk_paper_sim import obar, side
from tests.test_desk_trading import (  # noqa: F401  (`world` and `api` are fixtures)
    A, TRADES_URL, FakeDb, api, trade_body, trades, world,
)
from tests.test_risk_gate import run

FEDERAL_BODY = {"symbol": "FEDERALBNK", "quantity": 100, "entry_price": 316.89, "stop_price": 312.18, "target_price": 355.5,
                "source": {"kind": "scanner", "bucket": "true_accumulation", "signal_date": "2026-10-26"}}
FEDERAL_26 = obar("2026-10-26", 341.0, 344.8, 337.2, 344.4)          # real (study B §7c)
FEDERAL_27 = obar("2026-10-27", 345.0, 356.0, 343.0, 355.0)          # HYPOTHETICAL


def _post(api, body, headers=A):
    return api.post(TRADES_URL, json=body, headers=headers)


def _doc(world, trade_id):
    return next(d for d in world.db.trades.docs if d["_id"] == trade_id)


def _detail_code(r):
    d = r.json()["detail"]
    return d if isinstance(d, str) else d["code"]


# ── FM: the fill model ───────────────────────────────────────────────────────
def test_fm2_federalbnk_at_once_far_below_the_last_range_is_refused_with_the_range(api, world):
    # Study B probe B3: the Top 10 body with no entry rule was booked "at once" at 316.89 and showed ₹3,861 of profit.
    world.now = datetime(2026, 10, 26, 14, 30, tzinfo=timezone.utc)                 # 20:00 IST, after the session closed
    world.rows["FEDERALBNK"] = [FEDERAL_26]
    r = _post(api, FEDERAL_BODY, {**A, "X-Correlation-ID": "corr-fed"})
    assert r.status_code == 422 and _detail_code(r) == "entry_not_tradable"
    message = r.json()["detail"]["message"]
    assert "₹316.89 is below the last completed session's range (2026-10-26: ₹337.20–₹344.80)" in message
    assert 'entry rule "pull back to"' in message
    assert world.db.trades.docs == [] and world.db.cols[acct.ACCOUNTS].docs == []
    (row,) = world.db.cols[rc.DECISIONS].docs                         # the refusal is recorded (desk_paper_safety A-1)
    assert (row["reasons"][0]["code"], row["symbol"], row["path"]) == ("entry_not_tradable", "FEDERALBNK", "desk_paper_trade")


def test_fm14_the_same_levels_as_a_pullback_wait_and_are_never_filled_at_316_89_by_those_bars(api, world):
    world.now = datetime(2026, 10, 26, 14, 30, tzinfo=timezone.utc)
    world.rows["FEDERALBNK"] = [FEDERAL_26]
    r = _post(api, {**FEDERAL_BODY, "entry_rule": "pullback_to"})
    assert r.status_code == 201, r.text
    world.add("FEDERALBNK", FEDERAL_27)
    [row] = trades(api)["trades"]
    assert (row["status"], row["entry_status"], row["sim_entry_price"], row["gross_pnl_rs"]) == ("open", "waiting", None, None)


def test_fm1_at_once_inside_the_range_fills_at_the_entry(api, world):
    r = _post(api, trade_body())                                            # FIXA 12 Oct traded 94–104; entry 100
    assert r.status_code == 201, r.text
    t = r.json()["trade"]
    assert (t["entry_rule"], t["entry_status"], t["sim_entry_price"]) == ("at_once", "assumed", 100.0)
    assert _doc(world, t["id"])["entry_range_checked"] == {"date": "2026-10-12", "low": 94.0, "high": 104.0}


@pytest.mark.parametrize("entry,side_word", [(104.01, "above"), (93.99, "below")])
def test_fm2_at_once_one_paisa_outside_is_refused(api, world, entry, side_word):
    r = _post(api, trade_body(entry_price=entry, stop_price=90.0, target_price=120.0))
    assert r.status_code == 422 and _detail_code(r) == "entry_not_tradable" and side_word in r.json()["detail"]["message"]


def test_fm2_the_session_is_the_last_one_completed_when_recorded_not_a_later_one(api, world):
    # A bar dated after the day the trade is recorded is not the "last completed session" for it.
    world.now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)          # 9 Oct: FIXA traded 98–102
    assert _post(api, trade_body(entry_price=103.0, stop_price=95.0, target_price=110.0)).status_code == 422
    assert _post(api, trade_body(entry_price=101.0, stop_price=95.0, target_price=110.0)).status_code == 201


def test_fm3_no_bar_on_record_is_unverifiable_and_writes_nothing(api, world):
    r = _post(api, trade_body(symbol="FIXNONE"))
    assert r.status_code == 422 and _detail_code(r) == "entry_unverifiable"
    assert world.db.trades.docs == []


def test_fm4_unreadable_prices_refuse_an_at_once_entry_rather_than_assume_it(api, world):
    world.fail["FIXA"] = svc.daas_client.DaasError("DAAS /prices/eod/FIXA returned HTTP 502", status_code=502)
    r = _post(api, trade_body())
    assert (r.status_code, r.json()["detail"]) == (503, "prices_unavailable")
    assert world.db.trades.docs == [] and world.db.cols[acct.ACCOUNTS].docs == []
    # A conditional entry needs no fill now, so it is still recorded; it waits for bars that show its level.
    assert _post(api, trade_body(entry_rule="break_above", entry_price=106.0)).status_code == 201


def test_fm12_partial_exits_are_not_modelled_a_close_takes_no_quantity(api, world):
    t = _post(api, trade_body()).json()["trade"]
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"quantity": 5}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "unknown_field")
    assert _doc(world, t["id"])["status"] == "open"


def _trade(rule: str = "at_once", **over) -> Dict[str, Any]:
    body = {"symbol": "FIXT", "quantity": 100, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0, **over}
    if rule != "at_once":
        body["entry_rule"] = rule
    return svc.new_trade("u1", body, datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc))


def _bar(day: int, o, h, l, c) -> Dict[str, Any]:
    return {"date": date(2026, 10, day), "open": o, "high": h, "low": l, "close": c}


# Every rule of the FILL MODEL block in services/desk_trading.py, on the pure simulator (bars from 20 Oct 2026, after
# the 19 Oct open date). (rule, overrides, bars, expected entry status, entry fill, exit reason, exit fill, flags).
FILL_MODEL = [
    ("break_above reaches the entry", "break_above", {}, [_bar(20, 99, 100.5, 98, 100)], "reached", 100.0, None, None, []),
    ("break_above gap-through entry fills at the open", "break_above", {},
     [_bar(20, 104, 106, 103, 105)], "reached", 104.0, None, None, ["entry_gap"]),
    ("pullback_to reaches the entry", "pullback_to", {}, [_bar(20, 101, 102, 99.5, 101)], "reached", 100.0, None, None, []),
    ("pullback_to gap-down entry fills at the open", "pullback_to", {}, [_bar(20, 97, 99, 96, 98)], "reached", 97.0, None, None,
     ["entry_gap"]),
    ("stop touched fills at the stop", "at_once", {}, [_bar(20, 99, 101, 94, 96)], "assumed", 100.0, "stop", 95.0, []),
    ("gap-through stop fills at the open", "at_once", {}, [_bar(20, 92, 94, 90, 93)], "assumed", 100.0, "stop", 92.0,
     ["gap_through_stop"]),
    ("target touched fills at the target", "at_once", {}, [_bar(20, 104, 111, 103, 109)], "assumed", 100.0, "target", 110.0, []),
    ("target jump fills at the target, not the better open", "at_once", {}, [_bar(20, 115, 118, 114, 117)], "assumed", 100.0,
     "target", 110.0, []),
    ("stop and target in one session count as the stop", "at_once", {}, [_bar(20, 100, 112, 94, 100)], "assumed", 100.0,
     "stop", 95.0, ["both_in_range"]),
    ("time exit at the close of the last session held", "at_once", {"max_hold_sessions": 2},
     [_bar(20, 100, 103, 97, 101), _bar(21, 101, 104, 98, 102.5)], "assumed", 100.0, "time", 102.5, []),
    ("entry not reached in its window: no fill", "break_above", {"entry_window_sessions": 2, "entry_price": 120.0, "target_price": 130.0},
     [_bar(20, 100, 103, 97, 101), _bar(21, 101, 104, 98, 102)], "not_reached", None, "entry_not_reached", None, []),
    ("a session with no high or low stops the scan: the trade waits", "break_above", {},
     [_bar(20, 99, None, None, 99), _bar(21, 104, 106, 103, 105)], "waiting", None, None, None, ["bar_missing_high_low"]),
]


@pytest.mark.parametrize("name,rule,over,bars,status,fill,reason,exit_fill,flags", FILL_MODEL, ids=[f[0] for f in FILL_MODEL])
def test_fm5_to_fm13_the_documented_fill_model(name, rule, over, bars, status, fill, reason, exit_fill, flags):
    sim = svc.simulate(_trade(rule, **over), bars)
    assert (sim["entry_status"], sim["sim_entry_price"]) == (status, fill)
    assert (sim["exit"] or {}).get("exit_reason") == reason and (sim["exit"] or {}).get("exit_price") == exit_fill
    assert [f["code"] for f in sim["flags"]] == flags
    # Partial fills are not modelled: a fill is always the whole quantity (FM-12).
    assert _trade(rule, **over)["quantity"] == 100


# ── P: P&L from the simulated fill ───────────────────────────────────────────
def _gap_world(world):
    """Break-above at 100; 13 Oct stays below; 14 Oct OPENS at 104 (fill 104); 15 Oct reaches the 110 target (probe B2)."""
    world.rows["FIXG"] = [obar("2026-10-12", 99, 99.5, 98, 99), obar("2026-10-13", 99, 99.5, 98, 99),
                          obar("2026-10-14", 104, 106, 103, 105)]


def test_p1_p2_a_gapped_entry_books_600_from_its_fill_not_1000_and_the_open_and_closed_pnl_agree(api, world):
    _gap_world(world)
    t = _post(api, {"symbol": "FIXG", "quantity": 100, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0,
                    "entry_rule": "break_above"}).json()["trade"]
    [open_row] = trades(api)["trades"]
    assert (open_row["entry_status"], open_row["sim_entry_price"], open_row["unrealized_pnl_rs"]) == ("reached", 104.0, 100.0)
    world.add("FIXG", obar("2026-10-15", 106, 111, 105, 110.5))
    [row] = trades(api)["trades"]
    costs = round(side(104, 100) + side(110, 100), 2)                       # 25.20 + 25.50 = 50.70
    assert (row["status"], row["exit_reason"], row["exit_price"]) == ("closed", "target", 110.0)
    assert row["realized_pnl_rs"] == 600.0 == row["gross_pnl_rs"]          # (110 − 104) × 100; it booked 1,000 before
    assert row["costs_rs"] == costs == 50.7 and row["net_pnl_rs"] == round(600.0 - costs, 2) == 549.3
    stored = _doc(world, t["id"])
    assert (stored["realized_pnl_rs"], stored["costs_rs"], stored["net_pnl_rs"], stored["sim_entry_price"]) == (600.0, 50.7, 549.3, 104.0)
    (account,) = world.db.cols[acct.ACCOUNTS].docs
    assert account["cash_rs"] == round(acct.DEFAULT_CAPITAL + 549.3, 2) and account["blocked_rs"] == 0.0


def test_p1_the_service_close_uses_the_fill_too():
    # The probe's exact path: close_trade(sim=...) on a gapped break-above.
    t = _trade("break_above")
    sim = svc.simulate(t, [_bar(20, 99, 99.5, 98, 99), _bar(21, 104, 106, 103, 105), _bar(22, 106, 111, 105, 110.5)])
    db = FakeDb()
    db.trades.docs.append(t)
    stored, mine = run(svc.close_trade(db, t, **sim["exit"], sim=sim))
    assert mine and (stored["realized_pnl_rs"], stored["costs_rs"], stored["net_pnl_rs"]) == (600.0, 50.7, 549.3)


def test_p3_an_older_closed_record_without_costs_is_priced_at_its_stored_fill():
    doc = {**_trade("break_above"), "status": "closed", "exit_price": 110.0, "realized_pnl_rs": 600.0, "sim_entry_price": 104.0,
           "entry_status": "reached"}
    out = svc.public_trade(doc)
    assert out["costs_rs"] == round(side(104, 100) + side(110, 100), 2) and out["net_pnl_rs"] == 549.3


def test_p5_a_gap_through_the_stop_books_the_loss_at_the_open(api, world):
    t = _post(api, trade_body(quantity=20)).json()["trade"]                 # FIXA at 100, stop 95
    world.add("FIXA", obar("2026-10-13", 92, 94, 90, 93))
    [row] = trades(api)["trades"]
    assert (row["exit_reason"], row["exit_price"]) == ("stop", 92.0)
    assert row["realized_pnl_rs"] == (92.0 - 100.0) * 20 == -160.0
    assert row["costs_rs"] == round(side(100, 20) + side(92, 20), 2) and _doc(world, t["id"])["net_pnl_rs"] == row["net_pnl_rs"]


def test_p4_strategy_trades_have_no_separate_fill_open_and_closed_pnl_use_the_recorded_legs():
    from tests.test_desk_strategy_trades import CALL_1300, CALL_1360, UNDERLYING, call, strategy_body
    from tests.test_desk_trading import NOW
    doc = strat.new_strategy_trade("u1", strategy_body(legs=[call("buy", 1300, 40), call("sell", 1360, 15)]), NOW)
    bars = svc.session_bars(UNDERLYING)
    sim = strat.simulate_strategy(doc, bars, [CALL_1300, CALL_1360])
    # 15 Oct: target; marks 110 / 60 → (110 − 40) × 250 − (60 − 15) × 250 = 6,250, from the recorded leg prices.
    assert sim["exit"]["exit_reason"] == "target" and sim["gross_pnl_rs"] == 6250.0
    db = FakeDb()
    db.trades.docs.append(doc)
    stored, _ = run(strat.close_strategy_trade(db, doc, **sim["exit"], sim=sim))
    assert stored["realized_pnl_rs"] == 6250.0 == sim["gross_pnl_rs"]


# ── C: costs in sizing, risk reporting and realised P&L ──────────────────────
EXAMPLE_A = dict(entry=1005.0, stop=970.0, budget=3000.0)                  # PRD Example A


def test_c1_example_a_is_sized_so_the_loss_after_costs_fits_the_budget():
    e, s, b = EXAMPLE_A["entry"], EXAMPLE_A["stop"], EXAMPLE_A["budget"]
    slip, brokerage = svc.cost_terms()
    inputs = {"risk_budget_inr": b, "capital": 300_000.0, "max_allocation_pct": 100.0}
    gross_only = cd.size_position(inputs, risk_per_unit=e - s, value_per_unit=e, unit="shares", per_unit_label="x")
    assert gross_only["quantity"] == 85                                     # the PRD's figure, on the gross distance
    over = 85 * (e - s) + svc.round_trip_cost(85, e, s)
    assert round(over, 2) == 3098.94 and over > b                          # study A probe P2: over the budget
    sized = cd.size_position(inputs, risk_per_unit=e - s, value_per_unit=e, unit="shares", per_unit_label="x",
                             cost_per_unit=(e + s) * slip, fixed_cost=2 * brokerage)
    # floor((3,000 − 40) / (35 + 1,975 × 0.05%)) = floor(2,960 / 35.9875) = 82
    assert (sized["quantity"], sized["by_risk_budget"], sized["costs_included"]) == (82, 82, True)
    # 82 x 35 = 2,870 gross; 82 x 0.9875 + 40 = 120.975 of costs; 2,990.975 after costs (rounded to the paisa)
    assert sized["risk_at_stop_inr"] == 2870.0 and sized["risk_at_stop_net_inr"] == pytest.approx(2990.975, abs=0.006)
    assert sized["risk_at_stop_net_inr"] <= b
    assert svc.max_units_within_budget(b, e, s) == 82


def test_c2_the_desk_scenario_sizes_example_a_after_costs():
    r = positional_route._trade_scenario(entry=1005.0, stop=970.0, target=1075.0, risk_budget=3000.0)
    assert r["sizing"]["quantity"] == 82 and r["sizing"]["binding"] == "risk_budget"
    assert r["outcomes"]["loss_at_stop_net"] == pytest.approx(2990.975, abs=0.006) and r["outcomes"]["loss_at_stop_net"] <= 3000.0


def test_c3_the_basket_never_forces_a_share_above_its_risk_cap():
    # Capital 1,00,000 over 8 positions: 12,500 a position; 2% risk cap = 2,000. A 4,900 stop distance on a 5,000 share:
    # before, qty = max(1, floor(12,500 / 5,000)) = 2 and the cap (floor(2,000 / 4,900) = 0) was skipped → ₹9,800 at risk.
    wide = positional_route._size_position(100_000.0, 8, 5000.0, 100.0, 1.0)
    assert wide["qty"] == 0 and wide["risk_rs"] == 0.0
    ok = positional_route._size_position(100_000.0, 8, 1000.0, 960.0, 1.0)
    # by allocation floor(12,500 / 1,000) = 12; by risk floor((2,000 − 40) / (40 + 1,960 × 0.05%)) = floor(47.83) = 47 → 12
    assert ok["qty"] == 12 and ok["risk_gross_rs"] == 480.0
    assert ok["risk_rs"] == round(480.0 + svc.round_trip_cost(12, 1000.0, 960.0), 2) and "after estimated round-trip costs" in ok["risk_basis"]
    tight = positional_route._size_position(100_000.0, 1, 1000.0, 960.0, 1.0)  # allocation 100: the risk cap binds at 47
    assert tight["qty"] == 47 and tight["risk_rs"] <= 2000.0
    # On the gross distance it would have been floor(2,000 / 40) = 50, with ₹2,000 + ₹137.80 of costs over the cap.
    assert 50 * 40 + svc.round_trip_cost(50, 1000.0, 960.0) > 2000.0


def test_c4_one_cost_function_for_sizing_the_estimate_on_the_trade_and_the_realised_costs():
    # The plan's cash candidate (tests/test_strategy_plan.py fixture world: entry 1200, stop 1160, 208 shares) and the
    # paper trade its "Paper trade this" records (frontend strategy/plan-data.ts cashPaperBody) price the stop the same.
    from tests.test_strategy_plan import build, cand
    c = cand(build(instrument="cash"), "cash:breakout_continuation")
    sz, leg = c["sizing"], c["legs"][0]
    t = svc.new_trade("u1", {"symbol": "RELIANCE", "quantity": leg["quantity"], "entry_price": leg["entry_price"],
                             "stop_price": c["invalidation"]["technical"]["price"]}, svc.utcnow())
    estimate = svc.estimated_costs(t)["at_stop"]                                 # shown on the trade (est_costs_rs)
    realised = svc.trade_costs(t, t["entry_price"], t["stop_price"])             # booked by a stop exit at those fills
    assert sz["costs_at_stop_inr"] == estimate == realised == 285.44
    assert sz["risk_at_stop_net_inr"] == round(208 * 40 + realised, 2) == 8605.44
    scenario = positional_route._trade_scenario(entry=1200.0, stop=1160.0, risk_budget=10_000.0, max_qty=208)
    assert scenario["costs"]["round_trip_at_stop"] == realised


def test_c5_the_cost_model_is_versioned_explicit_and_an_old_trade_keeps_its_own():
    assert svc.COST_MODEL["version"] == "desk-flat-v1"
    assert {"STT", "stamp duty", "GST"} <= set(svc.COST_MODEL["excludes"])
    old = {**_trade(), "cost_model": {"name": "older", "slippage_pct_per_side": 0.1, "brokerage_rs_per_side": 0.0}}
    assert svc.trade_costs(old, 100.0, 110.0) == round(100 * 100 * 0.001 + 110 * 100 * 0.001, 2)
    t = svc.public_trade({**_trade(), "status": "closed", "exit_price": 110.0, "realized_pnl_rs": 1000.0, "costs_rs": 41.0})
    assert "not included" in t["costs_basis"]


# ── R: reconciliation invariants ─────────────────────────────────────────────
def _assert_reconciles(world) -> None:
    docs: List[Dict[str, Any]] = world.db.trades.docs
    for d in docs:
        if d["status"] != "closed":
            continue
        if d.get("exit_price") is None:                                       # never filled: no P&L, no costs
            assert (d["realized_pnl_rs"], d["costs_rs"], d["net_pnl_rs"]) == (None, None, None)
            continue
        fill = d["sim_entry_price"]
        assert d["realized_pnl_rs"] == round((d["exit_price"] - fill) * d["quantity"], 2)
        assert d["costs_rs"] == svc.trade_costs(d, fill, d["exit_price"])
        assert d["net_pnl_rs"] == round(d["realized_pnl_rs"] - d["costs_rs"], 2)
    (account,) = world.db.cols[acct.ACCOUNTS].docs
    ledger = world.db.cols[acct.LEDGER].docs
    reserved = sum(r["amount_rs"] for r in ledger if r["action"] == "reserve")
    released = sum(r["amount_rs"] for r in ledger if r["action"] == "release")
    open_reserved = sum(d.get("paper_reserved_rs") or 0 for d in docs if d["status"] == "open")
    net = sum(d["net_pnl_rs"] for d in docs if d["status"] == "closed" and d["net_pnl_rs"] is not None)
    assert account["blocked_rs"] == pytest.approx(open_reserved) == pytest.approx(reserved - released)
    assert account["cash_rs"] == pytest.approx(acct.DEFAULT_CAPITAL + net)
    assert sum(r.get("net_pnl_rs") or 0 for r in ledger if r["action"] == "release") == pytest.approx(net)


def test_r1_r2_r3_entry_full_exit_cancellation_and_refusals_reconcile(api, world):
    _gap_world(world)
    world.rows["FIXW"] = [obar("2026-10-12", 50, 51, 49, 50)]
    world.rows["FIXC"] = [obar("2026-10-12", 70, 71, 69, 70)]
    target = _post(api, {"symbol": "FIXG", "quantity": 100, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0,
                         "entry_rule": "break_above"}).json()["trade"]
    stop = _post(api, trade_body(quantity=20)).json()["trade"]                 # FIXA at 100
    by_hand = _post(api, trade_body(symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=520.0)).json()["trade"]
    never = _post(api, {"symbol": "FIXW", "quantity": 10, "entry_price": 60.0, "stop_price": 55.0, "target_price": 70.0,
                        "entry_rule": "break_above", "entry_window_sessions": 1}).json()["trade"]
    cancelled = _post(api, {"symbol": "FIXC", "quantity": 10, "entry_price": 80.0, "stop_price": 75.0, "target_price": 90.0,
                            "entry_rule": "break_above"}).json()["trade"]
    # Refused and replayed submissions move nothing (R-3).
    assert _post(api, trade_body()).status_code == 409                         # a duplicate FIXA
    assert _post(api, trade_body(symbol="FIXB", entry_price=501.0, stop_price=480.0, target_price=520.0)).status_code == 409
    assert api.post(f"{TRADES_URL}/{by_hand['id']}/close", json={"exit_price": 510.0}, headers=A).status_code == 200
    assert api.post(f"{TRADES_URL}/{cancelled['id']}/close", json={}, headers=A).status_code == 200
    world.add("FIXA", obar("2026-10-13", 92, 94, 90, 93))                       # gap through the stop
    world.add("FIXW", obar("2026-10-13", 50, 51, 49, 50))                       # never reaches 60 in its 1 session
    world.add("FIXG", obar("2026-10-15", 106, 111, 105, 110.5))                 # target
    body = trades(api)
    by_id = {t["id"]: t for t in body["trades"]}
    assert by_id[target["id"]]["exit_reason"] == "target" and by_id[stop["id"]]["exit_reason"] == "stop"
    assert by_id[by_hand["id"]]["exit_reason"] == "manual" and by_id[cancelled["id"]]["exit_reason"] == "cancelled"
    assert by_id[never["id"]]["exit_reason"] == "entry_not_reached"
    _assert_reconciles(world)
    (account,) = world.db.cols[acct.ACCOUNTS].docs
    assert account["blocked_rs"] == 0.0                                          # everything closed, everything released
