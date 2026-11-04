"""SPT slice C — the execution model spt-exec-v1 (DESIGN.md §6): which quote, which price, how much, which order types,
costs per fill, and that nothing is ever filled from a missing or stale quote. Test cases SPT-C-07…14.

Pure tests on `execution.simulate` plus a few through `execute_order` on the in-memory fakes (tests/spt_c_fakes.py).
MOCK — not real data: the quotes are made up.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from services import desk_cost_card as cost_card
from services.spt import constants as C
from services.spt.paper import execution, store
from tests.spt_c_fakes import NOW, World, quote, reset_module_state


def run(coro):
    return asyncio.run(coro)


def order(**kw):
    base = {"_id": "o1", "purpose": "ENTRY", "side": "BUY", "order_type": "MARKET", "quantity": 100,
            "remaining_quantity": 100, "limit_price": None, "trigger_price": None, "triggered_at": None,
            "planned_entry_price": 100.0, "exit_plan": {"stop_loss": 96.0}, "cost_model": execution.card_snapshot(),
            "last_quote_at": None}
    base.update(kw)
    return base


def sim(o, q, *, now=NOW, session_open=True, max_qty=None):
    return execution.simulate(o, q, now, session_open=session_open, max_qty=max_qty)


@pytest.fixture
def w(monkeypatch):
    reset_module_state(monkeypatch)
    return World()


# ── SPT-C-07 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c07_buy_at_ask_plus_slippage_capped_at_displayed_qty():
    r = sim(order(), quote(100.0, bid=99.95, ask=100.05, ask_qty=40))
    assert [f["quantity"] for f in r["fills"]] == [40]
    f = r["fills"][0]
    assert f["price"] == cost_card.paisa(100.05 * 1.0005) and f["ref_price"] == 100.05
    assert f["basis"] == "top_of_book" and f["depth_unknown"] is False
    assert f["slippage_rs"] == cost_card.paisa((f["price"] - 100.05) * 40)


def test_c07b_sell_at_bid_minus_slippage():
    r = sim(order(purpose="EXIT", side="SELL", exit_plan=None, planned_entry_price=None),
            quote(100.0, bid=99.95, ask=100.05, bid_qty=1000))
    assert r["fills"][0]["price"] == cost_card.paisa(99.95 * 0.9995) and r["fills"][0]["quantity"] == 100


def test_c07c_partial_fill_then_rest_on_a_new_quote(w):
    o = run(w.entry(qty=100))
    run(execution.execute_order(w.db, o, quote(100.0, bid=99.9, ask=100.0, ask_qty=30), w.now, session_open=True))
    a = run(store.get_order(w.db, o["_id"]))
    assert a["state"] == C.ORD_PARTIAL and a["filled_quantity"] == 30 and a["remaining_quantity"] == 70
    t2 = NOW + timedelta(seconds=15)
    run(execution.execute_order(w.db, a, quote(100.1, bid=100.0, ask=100.1, ask_qty=500, at=t2), t2, session_open=True))
    b = run(store.get_order(w.db, o["_id"]))
    assert b["state"] == C.ORD_FILLED and b["filled_quantity"] == 100 and b["remaining_quantity"] == 0
    fills = sorted(w.db.docs(store.FILLS), key=lambda f: f["seq"])
    assert [(f["_id"], f["seq"], f["quantity"]) for f in fills] == [(f"{o['_id']}:1", 1, 30), (f"{o['_id']}:2", 2, 70)]
    assert len(w.events("PAPER_ORDER_PARTIALLY_FILLED")) == 1 and len(w.events("PAPER_ORDER_FILLED")) == 1
    assert b["avg_fill_price"] == round((fills[0]["value_rs"] + fills[1]["value_rs"]) / 100, 4)


# ── SPT-C-08 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c08_five_level_depth_fills_level_by_level():
    depth = {"buy": [{"price": 99.9, "quantity": 10}],
             "sell": [{"price": 100.2, "quantity": 30}, {"price": 100.0, "quantity": 20}, {"price": 100.1, "quantity": 25},
                      {"price": 100.3, "quantity": 50}, {"price": 100.4, "quantity": 50}]}
    r = sim(order(quantity=90, remaining_quantity=90), quote(100.0, bid=99.9, ask=100.0, ask_qty=20, depth=depth))
    assert [(f["ref_price"], f["quantity"]) for f in r["fills"]] == [(100.0, 20), (100.1, 25), (100.2, 30), (100.3, 15)]
    assert all(f["basis"] == "depth" and not f["depth_unknown"] for f in r["fills"])
    assert r["fills"][2]["price"] == cost_card.paisa(100.2 * 1.0005)


# ── SPT-C-09 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c09_no_bid_ask_fills_at_most_a_quarter_of_the_order_at_ltp_plus_spread():
    r = sim(order(), quote(100.0))
    assert len(r["fills"]) == 1
    f = r["fills"][0]
    assert f["quantity"] == 25 and f["depth_unknown"] is True and f["basis"] == "ltp_spread"
    assert f["price"] == cost_card.paisa(100.0 * 1.0005 * 1.0005)
    # the second round on a new quote: again at most a quarter of the ORDER (never the whole order on a guess)
    r2 = sim(order(remaining_quantity=75, last_quote_at="x"), quote(100.0, at=NOW + timedelta(seconds=15)),
             now=NOW + timedelta(seconds=15))
    assert r2["fills"][0]["quantity"] == 25
    tiny = sim(order(quantity=3, remaining_quantity=3), quote(100.0))
    assert tiny["fills"][0]["quantity"] == 1


def test_c09b_ask_without_quantity_is_depth_unknown():
    r = sim(order(), quote(100.0, bid=99.9, ask=100.0))
    assert r["fills"][0]["quantity"] == 25 and r["fills"][0]["basis"] == "top_of_book_no_qty"
    assert r["fills"][0]["ref_price"] == 100.0


# ── SPT-C-10 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("q,why", [
    (None, "quote_missing"),
    ({"ltp": None, "received_at": NOW.isoformat()}, "quote_missing"),
    ({"ltp": 100.0, "received_at": None}, "quote_stale"),
    ({"ltp": 100.0, "received_at": "not a time"}, "quote_stale"),
    ("stale", "quote_stale"),
])
def test_c10_no_fill_without_a_fresh_quote(q, why):
    if q == "stale":
        q = quote(100.0, bid=99.9, ask=100.0, ask_qty=1000, at=NOW - timedelta(seconds=121))
    r = sim(order(), q)
    assert r["fills"] == [] and r["reason"] == why


def test_c10b_out_of_session_and_feed_not_live(w):
    assert sim(order(), quote(100.0, ask=100.0, ask_qty=10), session_open=False)["reason"] == "out_of_session"
    assert sim(order(), quote(100.0, ask=100.0, ask_qty=10, at=NOW - timedelta(seconds=120)))["fills"]   # 120 s is still fresh
    o = run(w.entry())
    res = run(execution.execute_order(w.db, o, None, w.now, session_open=True))
    assert res == {"order_id": o["_id"], "filled": 0, "reason": "quote_missing"}
    after = run(store.get_order(w.db, o["_id"]))
    assert after["last_attempt"]["reason"] == "quote_missing" and after["filled_quantity"] == 0
    assert w.db.docs(store.FILLS) == []
    # a day of stale quotes ends with the order expired and its reservation released (DESIGN §6)
    from services.spt.paper import orders
    run(orders.expire_due(w.db, NOW.replace(hour=10)))
    assert run(store.get_order(w.db, o["_id"]))["reservation_state"] == "released"


# ── SPT-C-11 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c11_limit_buy_never_above_its_limit():
    o = order(order_type="LIMIT", limit_price=100.0)
    assert sim(o, quote(100.2, bid=100.1, ask=100.2, ask_qty=1000))["reason"] == "limit_not_marketable"
    r = sim(o, quote(100.0, bid=99.9, ask=99.98, ask_qty=1000))
    assert r["fills"][0]["price"] == 100.0                   # 99.98 × 1.0005 = 100.03 > limit → filled AT the limit
    r2 = sim(o, quote(99.0, bid=98.9, ask=99.0, ask_qty=1000))
    assert r2["fills"][0]["price"] == cost_card.paisa(99.0 * 1.0005)


def test_c11b_stop_orders_trigger_on_ltp_crossing():
    slm = order(order_type="SL_M", trigger_price=101.0)
    assert sim(slm, quote(100.5, ask=100.6, ask_qty=1000))["reason"] == "not_triggered"
    r = sim(slm, quote(101.0, ask=101.05, ask_qty=1000))
    assert r["triggered_at"] == store.iso(NOW) and r["fills"][0]["quantity"] == 100
    sl = order(order_type="SL", trigger_price=101.0, limit_price=101.1, triggered_at="2026-11-05T04:00:00+00:00")
    assert sim(sl, quote(101.3, ask=101.3, ask_qty=1000))["reason"] == "limit_not_marketable"
    sell = order(purpose="EXIT", side="SELL", order_type="SL_M", trigger_price=95.0, exit_plan=None, planned_entry_price=None)
    assert sim(sell, quote(95.5, bid=95.4, bid_qty=1000))["reason"] == "not_triggered"
    assert sim(sell, quote(94.9, bid=94.85, bid_qty=1000))["fills"][0]["ref_price"] == 94.85


# ── SPT-C-12 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c12_costs_per_fill_from_the_desk_card(w):
    o = run(w.entry(qty=100))
    run(execution.execute_order(w.db, o, quote(100.0, bid=99.9, ask=100.0, ask_qty=60), w.now, session_open=True))
    t2 = NOW + timedelta(seconds=15)
    run(execution.execute_order(w.db, run(store.get_order(w.db, o["_id"])),
                                quote(100.0, bid=99.9, ask=100.0, ask_qty=60, at=t2), t2, session_open=True))
    f1, f2 = sorted(w.db.docs(store.FILLS), key=lambda f: f["seq"])
    m = dict(cost_card.SNAPSHOT, slippage_pct_per_side=0.0)
    assert f1["costs"] == cost_card.order_side("equity_delivery", "BUY", f1["value_rs"], m)
    assert f2["costs"] == cost_card.order_side("equity_delivery", "BUY", f2["value_rs"], dict(m, brokerage_rs_per_side=0.0))
    assert f1["costs"]["brokerage"] == 20.0 and f2["costs"]["brokerage"] == 0.0
    assert f1["costs"]["stt"] == cost_card.paisa(f1["value_rs"] * 0.001) and f1["costs"]["slippage"] == 0.0
    od = run(store.get_order(w.db, o["_id"]))
    assert od["costs"]["total"] == cost_card.paisa(f1["costs"]["total"] + f2["costs"]["total"])
    assert od["cost_model"]["version"] == "desk-cost-v2"


# ── SPT-C-13 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c13_one_quote_is_consumed_once(w):
    o = run(w.entry(qty=100))
    q = quote(100.0, bid=99.9, ask=100.0, ask_qty=30)
    run(execution.execute_order(w.db, o, q, w.now, session_open=True))
    res = run(execution.execute_order(w.db, run(store.get_order(w.db, o["_id"])), q, w.now + timedelta(seconds=15),
                                      session_open=True))
    assert res["filled"] == 0 and res["reason"] == "quote_already_used"
    assert run(store.get_order(w.db, o["_id"]))["filled_quantity"] == 30


# ── SPT-C-14 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c14_entry_guard_against_the_plan():
    assert sim(order(), quote(103.0, bid=102.9, ask=103.0, ask_qty=1000))["reason"] == "price_beyond_plan"
    assert sim(order(), quote(101.9, bid=101.8, ask=101.9, ask_qty=1000))["fills"]      # 101.95 ≤ 102
    assert sim(order(), quote(95.0, bid=94.9, ask=95.0, ask_qty=1000))["reason"] == "price_through_stop"
    # an exit has no guard
    assert sim(order(purpose="EXIT", side="SELL", exit_plan=None), quote(90.0, bid=90.0, bid_qty=1000))["fills"]


def test_c14b_exit_never_sells_more_than_held():
    r = sim(order(purpose="EXIT", side="SELL", exit_plan=None), quote(100.0, bid=100.0, bid_qty=1000), max_qty=40)
    assert sum(f["quantity"] for f in r["fills"]) == 40
    assert sim(order(purpose="EXIT", side="SELL"), quote(100.0, bid=100.0, bid_qty=1000), max_qty=0)["reason"] == "nothing_to_fill"
