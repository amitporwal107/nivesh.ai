"""The unified trade lifecycle (services/trade_lifecycle.py): LC-1, LC-2, LC-9, LC-11 and the ticket mapping of
test_reports/p2_trade_plan_lifecycle_TESTCASES.md. Pure functions; no database.

MOCK — not real data: the trade documents below are made up in the shape services/desk_trading.new_trade and
services/desk_strategy_trades.new_strategy_trade store.
"""
from __future__ import annotations

import pytest

from services import trade_lifecycle as lc

OPENED = "2026-10-26T09:30:00+00:00"          # 15:00 IST on 26 Oct


def cash(**over):
    doc = {"_id": "t1", "user_id": "u1", "symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0,
           "target_price": 110.0, "entry_rule": "at_once", "opened_at": OPENED, "status": "open",
           "rules_version": "desk-paper-v2", "signal_at": "2026-10-26", "source": {"kind": "scanner", "signal_date": "2026-10-26"}}
    doc.update(over)
    return doc


def strategy(**over):
    doc = {"_id": "s1", "user_id": "u1", "kind": "strategy", "underlying": "NIFTY", "reference_price": 22600.0,
           "stop_underlying": 22400.0, "target_underlying": 22900.0, "opened_at": OPENED, "status": "open",
           "rules_version": "desk-paper-v3", "signal": {"signal_at": "2026-10-26"},
           "legs": [{"kind": "option", "side": "buy", "lots": 1, "lot_size": 75, "entry_price": 120.0, "strike": 22600, "expiry": "2026-11-04"}]}
    doc.update(over)
    return doc


# ── LC-1: the transition table ───────────────────────────────────────────────
@pytest.mark.parametrize("frm,to", [
    (None, "TRADE_ELIGIBLE"), (None, "REJECTED"), (None, "WAIT_FOR_CONFIRMATION"), (None, "NO_SETUP"),
    ("NO_SETUP", "WAIT_FOR_CONFIRMATION"), ("WAIT_FOR_CONFIRMATION", "TRADE_ELIGIBLE"),
    ("TRADE_ELIGIBLE", "ENTRY_TRIGGERED"), ("ENTRY_TRIGGERED", "POSITION_OPEN"), ("POSITION_OPEN", "EXIT_PENDING"),
    ("EXIT_PENDING", "CLOSED"), ("TRADE_ELIGIBLE", "REJECTED"), ("TRADE_ELIGIBLE", "CLOSED"),
    ("ENTRY_TRIGGERED", "TRADE_ELIGIBLE"), ("EXIT_PENDING", "POSITION_OPEN"),
])
def test_every_prd_transition_is_allowed(frm, to):
    assert lc.allowed(frm, to)


@pytest.mark.parametrize("frm,to", [
    ("CLOSED", "POSITION_OPEN"), ("REJECTED", "TRADE_ELIGIBLE"), ("NO_SETUP", "POSITION_OPEN"),
    ("POSITION_OPEN", "CLOSED"), ("WAIT_FOR_CONFIRMATION", "POSITION_OPEN"), (None, "POSITION_OPEN"),
    ("POSITION_OPEN", "REJECTED"), ("TRADE_ELIGIBLE", "BOGUS"),
])
def test_invalid_transitions_are_refused(frm, to):
    assert not lc.allowed(frm, to)
    with pytest.raises(lc.InvalidTransition):
        lc.make_event("x", 1, frm, to, at=OPENED, reason="r", source="test")


def test_terminal_states_have_no_way_out():
    assert lc.TERMINAL == {"CLOSED", "REJECTED"}
    assert all(not lc.ALLOWED[s] for s in lc.TERMINAL)


# ── LC-2: every event carries the required fields ────────────────────────────
def test_an_event_carries_every_required_field_and_its_ist_session():
    e = lc.make_event("t1", 1, None, "TRADE_ELIGIBLE", at="2026-10-26T20:00:00+00:00", reason="accepted", source="desk",
                      actor="u1", rule_version="desk-paper-v2", signal_at="2026-10-26", data_as_of={"price": "2026-10-26"},
                      levels={"entry": 100}, quantity=10, est_costs_rs=12.5, risk_decision_id="rd1",
                      rejection_reasons=None, fill_price=None, slippage=None, exit_reason=None)
    assert set(lc.EVENT_FIELDS) <= set(e)
    assert e["event_id"] == "t1:1" and e["seq"] == 1
    assert e["session"] == "2026-10-27"            # 20:00 UTC is 01:30 IST the next day
    assert e["lifecycle_version"] == lc.LIFECYCLE_VERSION


# ── LC-3 / LC-7: opening events ──────────────────────────────────────────────
def test_an_at_once_cash_trade_opens_eligible_triggered_open_with_its_fill():
    ev = lc.opening_events(cash(), est_costs_rs=40.0)
    assert [(e["from"], e["to"]) for e in ev] == [(None, "TRADE_ELIGIBLE"), ("TRADE_ELIGIBLE", "ENTRY_TRIGGERED"),
                                                  ("ENTRY_TRIGGERED", "POSITION_OPEN")]
    assert ev[-1]["fill_price"] == 100.0 and ev[-1]["slippage"] == 0.0
    assert ev[0]["est_costs_rs"] == 40.0 and ev[0]["levels"]["stop"] == 95.0 and ev[0]["quantity"] == 10
    assert ev[0]["signal_at"] == "2026-10-26" and ev[0]["rule_version"] == "desk-paper-v2"
    assert lc.replay(ev) == ("POSITION_OPEN", [])


def test_a_conditional_cash_trade_waits_eligible():
    ev = lc.opening_events(cash(entry_rule="break_above"))
    assert [e["to"] for e in ev] == ["TRADE_ELIGIBLE"]


def test_a_strategy_trade_opens_at_once():
    ev = lc.opening_events(strategy())
    assert [e["to"] for e in ev] == ["TRADE_ELIGIBLE", "ENTRY_TRIGGERED", "POSITION_OPEN"]
    assert ev[0]["levels"]["stop_underlying"] == 22400.0 and ev[0]["quantity"] == [{"lots": 1, "lot_size": 75}]


def test_a_plan_ref_and_a_roll_name_their_source():
    assert lc.opening_events(cash(plan_ref={"plan_id": "tp_x", "candidate_id": "cash:a"}))[0]["source"] == "trade_plan"
    assert lc.opening_events(strategy(rolled_from={"trade_id": "old"}))[0]["source"] == "roll"


# ── LC-4 / LC-5 / LC-6: fills and closes ─────────────────────────────────────
def with_events(doc, events):
    return {**doc, "state": events[-1]["to"], "transitions": events}


def test_a_reached_conditional_entry_writes_triggered_and_open_with_the_gap_slippage():
    doc = with_events(cash(entry_rule="break_above"), lc.opening_events(cash(entry_rule="break_above")))
    ev = lc.entry_fill_events(doc, session="2026-10-27", fill_price=101.5)
    assert [(e["from"], e["to"], e["seq"]) for e in ev] == [("TRADE_ELIGIBLE", "ENTRY_TRIGGERED", 2), ("ENTRY_TRIGGERED", "POSITION_OPEN", 3)]
    assert ev[-1]["slippage"] == 1.5 and ev[-1]["session"] == "2026-10-27"
    # once open, a second evaluation finds nothing to write
    assert lc.entry_fill_events(with_events(doc, doc["transitions"] + ev), session="2026-10-27", fill_price=101.5) == []


def test_closing_an_open_position_writes_exit_pending_then_closed():
    doc = with_events(cash(), lc.opening_events(cash()))
    ev = lc.close_events(doc, exit_reason="stop", at="2026-10-28T10:00:00+00:00", session="2026-10-28", fill_price=95.0,
                         est_costs_rs=41.2)
    assert [(e["from"], e["to"]) for e in ev] == [("POSITION_OPEN", "EXIT_PENDING"), ("EXIT_PENDING", "CLOSED")]
    assert ev[-1]["exit_reason"] == "stop" and ev[-1]["fill_price"] == 95.0 and ev[-1]["est_costs_rs"] == 41.2
    assert [e["seq"] for e in ev] == [4, 5]
    assert lc.replay(doc["transitions"] + ev) == ("CLOSED", [])


def test_entry_not_reached_closes_from_eligible_without_a_position():
    doc = with_events(cash(entry_rule="pullback_to"), lc.opening_events(cash(entry_rule="pullback_to")))
    ev = lc.close_events(doc, exit_reason="entry_not_reached", at=OPENED, session="2026-11-02")
    assert [(e["from"], e["to"]) for e in ev] == [("TRADE_ELIGIBLE", "CLOSED")]


def test_a_conditional_trade_entered_and_stopped_in_one_evaluation_writes_the_whole_path():
    doc = with_events(cash(entry_rule="break_above"), lc.opening_events(cash(entry_rule="break_above")))
    ev = lc.close_events(doc, exit_reason="stop", at=OPENED, session="2026-10-29", fill_price=95.0,
                         entry_session="2026-10-27", entry_fill=100.0, entered=True)
    assert [e["to"] for e in ev] == ["ENTRY_TRIGGERED", "POSITION_OPEN", "EXIT_PENDING", "CLOSED"]
    assert ev[1]["session"] == "2026-10-27" and ev[1]["slippage"] == 0.0


def test_a_closed_trade_cannot_close_again():
    doc = with_events(cash(), lc.opening_events(cash()))
    ev = lc.close_events(doc, exit_reason="manual", at=OPENED, fill_price=99.0)
    closed = with_events(doc, doc["transitions"] + ev)
    with pytest.raises(lc.InvalidTransition):
        lc.close_events(closed, exit_reason="manual", at=OPENED, fill_price=99.0)


# ── LC-11: a document stored before the lifecycle ────────────────────────────
def test_a_legacy_open_trade_closes_with_its_derived_history_first():
    legacy = cash()                                  # no state, no transitions
    assert lc.current_state(legacy) == "POSITION_OPEN"
    ev = lc.close_events(legacy, exit_reason="target", at=OPENED, session="2026-10-28", fill_price=110.0)
    assert [e["to"] for e in ev] == ["TRADE_ELIGIBLE", "ENTRY_TRIGGERED", "POSITION_OPEN", "EXIT_PENDING", "CLOSED"]
    assert [e["derived"] for e in ev] == [True, True, True, False, False]
    assert lc.replay(ev) == ("CLOSED", [])


def test_derived_history_of_closed_trades():
    stopped = cash(status="closed", exit_reason="stop", exit_price=95.0, exit_session="2026-10-28",
                   closed_at="2026-10-28T12:00:00+00:00", entry_status="assumed", sim_entry_price=100.0)
    assert [e["to"] for e in lc.derive_history(stopped)][-2:] == ["EXIT_PENDING", "CLOSED"]
    never = cash(entry_rule="pullback_to", status="closed", exit_reason="entry_not_reached", entry_status="not_reached")
    assert [e["to"] for e in lc.derive_history(never)] == ["TRADE_ELIGIBLE", "CLOSED"]
    reached = cash(entry_rule="break_above", status="closed", exit_reason="target", entry_status="reached",
                   entry_session="2026-10-27", sim_entry_price=101.0)
    ev = lc.derive_history(reached)
    assert [e["to"] for e in ev] == ["TRADE_ELIGIBLE", "ENTRY_TRIGGERED", "POSITION_OPEN", "EXIT_PENDING", "CLOSED"]
    assert ev[2]["slippage"] == 1.0
    for d in (stopped, never, reached, strategy(), strategy(status="closed", exit_reason="expiry")):
        assert lc.replay(lc.derive_history(d))[1] == []


# ── LC-9: replay and restart ─────────────────────────────────────────────────
def test_replay_reports_a_broken_chain_and_a_stored_state_that_disagrees():
    ev = lc.opening_events(cash())
    broken = [ev[0], ev[2]]                           # skips ENTRY_TRIGGERED
    state, problems = lc.replay(broken)
    assert state == "POSITION_OPEN" and problems
    ok, why = lc.consistent({"state": "CLOSED", "transitions": ev})
    assert not ok and "replay to POSITION_OPEN" in why[-1]
    assert lc.consistent({"state": "POSITION_OPEN", "transitions": ev}) == (True, [])


def test_the_update_moves_state_and_pushes_events_with_the_callers_set():
    ev = lc.opening_events(cash())
    upd = lc.update_for(ev[1:], {"status": "open"})
    assert upd["$set"] == {"status": "open", "state": "POSITION_OPEN"}
    assert upd["$push"]["transitions"]["$each"] == ev[1:]
    assert lc.state_filter({"state": "TRADE_ELIGIBLE"}) == {"state": "TRADE_ELIGIBLE"}
    assert lc.state_filter({}) == {"state": None}


# ── LC-10: AI Trader tickets ─────────────────────────────────────────────────
def ticket(status, **over):
    t = {"_id": "k1", "status": status, "created_at": OPENED, "signal_date": "2026-10-26", "entry_price": 100.0,
         "stop_price": 95.0, "target_price": 110.0, "quantity": 10, "reason_codes": ["MAX_POSITION"],
         "decision": {"limits_version": "gov-v1"}}
    t.update(over)
    return t


def test_ticket_opening_events_follow_its_status():
    assert [e["to"] for e in lc.ticket_opening_events(ticket("rejected"))] == ["REJECTED"]
    assert lc.ticket_opening_events(ticket("rejected"))[0]["rejection_reasons"] == ["MAX_POSITION"]
    assert [e["to"] for e in lc.ticket_opening_events(ticket("awaiting_confirmation"))] == ["TRADE_ELIGIBLE"]
    assert [e["to"] for e in lc.ticket_opening_events(ticket("confirmed"))] == ["TRADE_ELIGIBLE", "ENTRY_TRIGGERED"]


def test_ticket_steps_and_idempotency():
    t = ticket("awaiting_confirmation")
    t = with_events(t, lc.ticket_opening_events(t))
    claim = lc.ticket_step(t, "ENTRY_TRIGGERED", at=OPENED, reason="confirmed")
    assert [(e["from"], e["to"], e["seq"]) for e in claim] == [("TRADE_ELIGIBLE", "ENTRY_TRIGGERED", 2)]
    t2 = with_events(t, t["transitions"] + claim)
    assert lc.ticket_step(t2, "ENTRY_TRIGGERED", at=OPENED, reason="again") == []
    back = lc.ticket_step(t2, "TRADE_ELIGIBLE", at=OPENED, reason="claim released")
    assert back[0]["from"] == "ENTRY_TRIGGERED"
    with pytest.raises(lc.InvalidTransition):
        lc.ticket_step(with_events(t2, t2["transitions"] + lc.ticket_step(t2, "REJECTED", at=OPENED, reason="desk")),
                       "POSITION_OPEN", at=OPENED, reason="x")


def test_legacy_tickets_derive_their_history():
    cases = {
        "executed_paper": ["TRADE_ELIGIBLE", "ENTRY_TRIGGERED", "POSITION_OPEN"],
        "expired": ["TRADE_ELIGIBLE", "REJECTED"],
        "awaiting_confirmation": ["TRADE_ELIGIBLE"],
    }
    for status, want in cases.items():
        assert [e["to"] for e in lc.derive_ticket_history(ticket(status))] == want
    assert [e["to"] for e in lc.derive_ticket_history(ticket("rejected", rejected_by="user"))] == ["TRADE_ELIGIBLE", "REJECTED"]
    assert [e["to"] for e in lc.derive_ticket_history(ticket("rejected", rejected_by="desk"))] == ["TRADE_ELIGIBLE", "ENTRY_TRIGGERED", "REJECTED"]


# ── the plan's derived status ────────────────────────────────────────────────
def test_plan_status_is_derived_from_its_trades():
    assert lc.plan_status([]) == "proposed"
    assert lc.plan_status(["REJECTED"]) == "rejected"
    assert lc.plan_status(["TRADE_ELIGIBLE"]) == "approved"
    assert lc.plan_status(["CLOSED", "POSITION_OPEN"]) == "open"
    assert lc.plan_status(["CLOSED", "REJECTED"]) == "closed"


def test_a_rejection_record_for_a_refused_open():
    r = lc.rejection_record(frm="TRADE_ELIGIBLE", reason="kill switch", source="desk_paper_trade", at=OPENED,
                            codes=["RISK_CONTROL"], plan_id="tp_1")
    assert (r["from"], r["to"], r["rejection_reasons"], r["plan_id"]) == ("TRADE_ELIGIBLE", "REJECTED", ["RISK_CONTROL"], "tp_1")
    assert lc.rejection_record(frm="CLOSED", reason="x", source="s", at=OPENED, codes=[])["from"] is None
