"""SPT slice C — paper orders: creation (slice B's call), idempotency, refusals, cancel / expiry, reservations, positions
from fills, the one release at close. Test cases: test_reports/spt_c_TESTCASES.md (SPT-C-01…06, 15, 16, 17).

No network, no real database: tests/spt_c_fakes.py (in-memory Mongo semantics; the paper account and the risk controls
run for real on it). MOCK — not real data: the FIXA / FIXB quotes are made up.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from services import desk_cost_card as cost_card
from services import paper_account as acct
from services import risk_controls as rc
from services.spt import constants as C
from services.spt.paper import execution, orders, positions, store
from tests.spt_c_fakes import NOW, World, ist, quote, reset_module_state


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def w(monkeypatch):
    reset_module_state(monkeypatch)
    return World()


async def fill(w: World, order_id: str, q: dict, now=None):
    o = await store.get_order(w.db, order_id)
    return await execution.execute_order(w.db, o, q, now or w.now, session_open=True)


# ── SPT-C-01 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c01_create_entry_order_happy_path(w):
    o = run(w.entry(qty=100, entry=100.0))
    assert o["state"] == C.ORD_PENDING and o["version"] == 2            # CREATED → VALIDATED → PENDING, conditional
    assert o["purpose"] == "ENTRY" and o["side"] == "BUY" and o["quantity"] == 100 and o["remaining_quantity"] == 100
    assert o["risk"]["reservation_id"] and o["risk"]["decision_id"] == o["risk"]["reservation_id"]
    assert o["risk"]["funding_rs"] == 10000.0
    assert o["expires_at"] == store.iso(ist(15, 30))                     # DAY: 15:30 IST of today's session
    assert o["session_day"] == "2026-11-05"
    assert o["cost_model"]["version"] == cost_card.VERSION and o["cost_model"]["slippage_in_price"] is True
    created = w.events("PAPER_ORDER_CREATED")
    assert len(created) == 1 and created[0]["account_id"] == "user_a" and created[0]["instrument_id"] == "FIXA"
    assert created[0]["idempotency_key"] == f"order:{o['_id']}:created"
    assert run(w.position_of(o["_id"])) is None                          # no position before a fill (WF §12.5)


def test_c01b_day_order_after_the_close_is_for_the_next_session(w):
    w.now = ist(20, 0)                                                   # Thursday 20:00 IST
    o = run(w.entry())
    assert o["session_day"] == "2026-11-06" and o["expires_at"] == store.iso(ist(15, 30, day=ist(20).date().replace(day=6)))
    w.now = ist(20, 0, day=ist(20).date().replace(day=6))                # Friday evening → Monday
    o2 = run(w.entry(symbol="FIXB"))
    assert o2["session_day"] == "2026-11-09"


# ── SPT-C-02 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c02_duplicate_create_returns_the_first_order(w):
    first = run(w.entry(order_id="ord-1", key="prop-1:entry"))
    again = run(w.entry(order_id="ord-1", key="prop-1:entry", decision=first and {
        "outcome": "allow", "reservation_id": first["risk"]["reservation_id"], "approved_qty": 100}))
    assert again["duplicate"] is True and again["_id"] == "ord-1"
    other_id = run(w.entry(order_id="ord-2", key="prop-1:entry",       # same key, another id (B retried enter)
                           decision={"outcome": "allow", "reservation_id": "r-2", "approved_qty": 100}))
    assert other_id["duplicate"] is True and other_id["_id"] == "ord-1"
    assert len(w.db.docs(store.ORDERS)) == 1
    assert len(w.events("PAPER_ORDER_CREATED")) == 1


# ── SPT-C-03 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c03_refusals_reject_and_release_once(w):
    blocked = run(w.entry(reserve=False))
    assert blocked["state"] == C.ORD_REJECTED and blocked["reject_reason"] == "risk_not_approved"
    assert blocked["reservation_state"] == "none"

    over = run(w.entry(symbol="FIXB", qty=100, decision=None))
    # the same reservation, but asking for more than approved
    rd = run(w.reserve("user_a", "ord-over", qty=50, entry=100.0, stop=96.0, symbol="FIXC"))
    o = run(w.entry(symbol="FIXC", qty=60, order_id="ord-over", decision=rd))
    assert o["state"] == C.ORD_REJECTED and o["reject_reason"] == "quantity_exceeds_approved"
    assert o["reservation_state"] == "released"
    acc = run(w.account("user_a"))
    assert all(e["trade_id"] != "ord-over" for e in acc["reservations"])
    assert len([r for r in w.ledger("user_a", "cancel_reservation") if r["trade_id"] == "ord-over"]) == 1
    assert over["state"] == C.ORD_PENDING


def test_c03b_kill_switch_at_create_rejects_and_releases(w):
    run(rc.set_control(w.db, "user_a", field="kill_switch", value=True, reason="test", actor="tester"))
    o = run(w.entry())
    assert o["state"] == C.ORD_REJECTED and o["reject_reason"] == "kill_switch_on"
    acc = run(w.account("user_a"))
    assert acc["blocked_rs"] == 0 and acc["reservations"] == [] and acc["open_risk_rs"] == 0
    assert len(w.ledger("user_a", "cancel_reservation")) == 1
    rej = [e for e in w.events("PAPER_ORDER_CANCELLED") if e["payload"].get("reject_reason")]
    assert rej and rej[0]["payload"]["state"] == C.ORD_REJECTED


def test_c03c_open_position_in_the_symbol_rejects_a_second_entry(w):
    o = run(w.entry(qty=10))
    run(fill(w, o["_id"], quote(100.0, bid=99.9, ask=100.0, ask_qty=500)))
    assert run(w.position_of(o["_id"]))["quantity"] == 10
    second = run(w.entry(qty=10, decision={"outcome": "allow", "reservation_id": "r-x", "approved_qty": 10}))
    assert second["state"] == C.ORD_REJECTED and second["reject_reason"] == "position_already_open"


# ── SPT-C-04 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c04_cancel_unfilled_entry_releases_exactly_once(w):
    o = run(w.entry())
    before = run(w.account("user_a"))
    assert before["blocked_rs"] == 10000.0 and before["open_positions"] == 1
    c = run(orders.cancel_order(w.db, o["_id"], reason="user", user_id="user_a", now=w.now))
    assert c["state"] == C.ORD_CANCELLED and c["cancelled_quantity"] == 100 and c["reservation_state"] == "released"
    assert run(orders.cancel_order(w.db, o["_id"], reason="user", user_id="user_a", now=w.now)) is None
    run(orders.sync_order(w.db, o["_id"], now=w.now))
    acc = run(w.account("user_a"))
    assert acc["blocked_rs"] == 0 and acc["open_positions"] == 0 and acc["cash_rs"] == acct.DEFAULT_CAPITAL
    assert len(w.ledger("user_a", "cancel_reservation")) == 1
    assert len(w.events("PAPER_ORDER_CANCELLED")) == 1
    assert run(orders.cancel_order(w.db, o["_id"], reason="x", user_id="user_b", now=w.now)) is None


# ── SPT-C-05 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c05_day_and_gtd_expiry(w):
    day = run(w.entry())
    gtd = run(w.entry(symbol="FIXB", tif="GTD", expires_at=store.iso(ist(12, 0))))
    assert run(orders.expire_due(w.db, ist(11, 59))) == 0
    assert run(orders.expire_due(w.db, ist(12, 0))) == 1
    assert run(store.get_order(w.db, gtd["_id"]))["state"] == C.ORD_EXPIRED
    assert run(orders.expire_due(w.db, ist(15, 29))) == 0
    assert run(orders.expire_due(w.db, ist(15, 30))) == 1
    d = run(store.get_order(w.db, day["_id"]))
    assert d["state"] == C.ORD_EXPIRED and d["reservation_state"] == "released"
    assert {e["payload"]["order_id"] for e in w.events("ORDER_EXPIRED")} == {day["_id"], gtd["_id"]}
    acc = run(w.account("user_a"))
    assert acc["blocked_rs"] == 0 and acc["reservations"] == []


def test_c05b_gtd_in_the_past_is_rejected(w):
    o = run(w.entry(tif="GTD", expires_at=store.iso(NOW - timedelta(minutes=1))))
    assert o["state"] == C.ORD_REJECTED and o["reject_reason"] == "expiry_invalid" and o["reservation_state"] == "released"


# ── SPT-C-06 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c06_partial_then_expiry_keeps_the_reservation_for_the_position(w):
    o = run(w.entry(qty=100))
    run(fill(w, o["_id"], quote(100.0, bid=99.9, ask=100.0, ask_qty=40)))
    run(orders.expire_due(w.db, ist(15, 30)))
    e = run(store.get_order(w.db, o["_id"]))
    assert e["state"] == C.ORD_EXPIRED and e["filled_quantity"] == 40 and e["remaining_quantity"] == 0
    assert e["cancelled_quantity"] == 60 and e["reservation_state"] == "kept_for_position"
    pos = run(w.position_of(o["_id"]))
    assert pos["quantity"] == 40 and pos["is_open"] is True
    acc = run(w.account("user_a"))
    assert acc["blocked_rs"] == 10000.0 and len(acc["reservations"]) == 1   # the whole planned size stays blocked
    assert w.ledger("user_a", "cancel_reservation") == []


# ── SPT-C-15 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c15_position_on_first_fill_with_weighted_average(w):
    o = run(w.entry(qty=100))
    assert run(w.position_of(o["_id"])) is None
    run(fill(w, o["_id"], quote(100.0, bid=99.9, ask=100.0, ask_qty=40)))
    run(fill(w, o["_id"], quote(100.5, bid=100.4, ask=100.6, ask_qty=500, at=NOW + timedelta(seconds=15)),
             now=NOW + timedelta(seconds=15)))
    pos = run(w.position_of(o["_id"]))
    p1, p2 = cost_card.paisa(100.0 * 1.0005), cost_card.paisa(100.6 * 1.0005)
    assert pos["quantity"] == 100 and pos["entry_qty"] == 100
    assert pos["avg_entry_price"] == round((40 * p1 + 60 * p2) / 100, 4)
    assert len(pos["fill_ids"]) == 2 and pos["state"] == C.POS_OPEN
    assert len(w.events("POSITION_OPENED")) == 1
    assert pos["exit_plan"]["stop_loss"] == 96.0 and pos["stop_loss"] == 96.0 and pos["target_1"] == 108.0
    assert pos["initial_risk_rs"] == round((pos["avg_entry_price"] - 96.0) * 100, 2)


# ── SPT-C-16 / SPT-C-17 ──────────────────────────────────────────────────────────────────────────────────────────────
def test_c16_c17_pnl_from_fills_and_one_release(w):
    o = run(w.entry(qty=100))
    run(fill(w, o["_id"], quote(100.0, bid=99.9, ask=100.0, ask_qty=1000)))
    pos = run(w.position_of(o["_id"]))
    t2 = NOW + timedelta(minutes=30)
    w.now = t2
    ex = run(orders.create_exit_order(w.db, position_id=pos["_id"], reason="manual", quantity=30, now=t2))
    run(fill(w, ex["_id"], quote(104.0, bid=104.0, ask=104.1, bid_qty=1000, at=t2), now=t2))
    mid = run(store.get_position(w.db, pos["_id"]))
    assert mid["quantity"] == 70 and mid["state"] == C.POS_PARTIALLY_EXITED
    assert len(w.events("POSITION_PARTIALLY_EXITED")) == 1
    t3 = t2 + timedelta(minutes=30)
    ex2 = run(orders.create_exit_order(w.db, position_id=pos["_id"], reason="manual", now=t3))
    run(fill(w, ex2["_id"], quote(103.0, bid=103.0, ask=103.1, bid_qty=1000, at=t3), now=t3))
    closed = run(store.get_position(w.db, pos["_id"]))
    assert closed["state"] == C.POS_CLOSED and closed["quantity"] == 0 and closed["is_open"] is False

    fills = w.db.docs(store.FILLS)
    entry_value = sum(f["value_rs"] for f in fills if f["purpose"] == "ENTRY")
    exit_value = sum(f["value_rs"] for f in fills if f["purpose"] == "EXIT")
    costs = sum(f["costs"]["total"] for f in fills)
    assert closed["realized_net_rs"] == round(exit_value - entry_value - costs, 2)        # WF §16.3, from the ledger
    assert closed["realized_gross_rs"] == round(exit_value - entry_value, 2)
    # brokerage once per order; slippage is in the price, not a cost
    assert sum(f["costs"]["brokerage"] for f in fills) == 60.0 and all(f["costs"]["slippage"] == 0 for f in fills)

    acc = run(w.account("user_a"))
    assert acc["blocked_rs"] == 0 and acc["reservations"] == [] and acc["open_risk_rs"] == 0
    assert acc["cash_rs"] == round(acct.DEFAULT_CAPITAL + closed["realized_net_rs"], 2)
    rel = w.ledger("user_a", "release")
    assert len(rel) == 1 and rel[0]["trade_id"] == o["_id"] and rel[0]["amount_rs"] == 10000.0
    assert closed["release"]["state"] == "done" and closed["release"]["amount_rs"] == 10000.0
    # replay: syncing every order again and re-running the release moves nothing
    for oid in (o["_id"], ex["_id"], ex2["_id"]):
        run(orders.sync_order(w.db, oid, now=t3))
    assert run(positions.release_once(w.db, closed, now=t3)) is False
    assert len(w.ledger("user_a", "release")) == 1
    assert run(w.account("user_a"))["cash_rs"] == acc["cash_rs"]
    assert len(w.events("POSITION_CLOSED")) == 1


def test_c17b_missing_reservation_is_recorded_not_fixed(w):
    o = run(w.entry(qty=10))
    run(fill(w, o["_id"], quote(100.0, bid=99.9, ask=100.0, ask_qty=1000)))
    pos = run(w.position_of(o["_id"]))
    # someone cancelled the reservation behind the position's back
    run(acct.cancel_reservation(w.db, "user_a", o["risk"]["reservation_id"], reason="test"))
    ex = run(orders.create_exit_order(w.db, position_id=pos["_id"], reason="manual", now=w.now))
    run(fill(w, ex["_id"], quote(101.0, bid=101.0, ask=101.1, bid_qty=1000, at=NOW + timedelta(seconds=1)),
             now=NOW + timedelta(seconds=1)))
    closed = run(store.get_position(w.db, pos["_id"]))
    assert closed["state"] == C.POS_CLOSED and closed["release"]["state"] == "missing_reservation"
    assert w.ledger("user_a", "release") == []
    assert run(w.account("user_a"))["cash_rs"] == acct.DEFAULT_CAPITAL
