"""SPT slice C — the monitor: stop and target exits on the live bid, the gap through the stop, T1 + breakeven, T2, the
kill switch, restart / replay safety, the evening trail / trend / time pass, gating, and the trade outcome record.
Test cases SPT-C-19…26, 35.

In-memory fakes (tests/spt_c_fakes.py); the paper account and the risk controls run for real on them.
MOCK — not real data: the FIXA / FIXB quotes and bars are made up.
"""
from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta

import pytest

from services import desk_cost_card as cost_card
from services import paper_account as acct
from services import risk_controls as rc
from services.spt import constants as C
from services.spt.paper import config, execution, monitor, orders, positions, store
from tests.spt_c_fakes import NOW, FakeLeader, World, ist, quote, reset_module_state


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def w(monkeypatch):
    reset_module_state(monkeypatch)
    monkeypatch.setattr(monitor, "_started_up", False)
    monkeypatch.setattr(monitor, "_last_evening", float("-inf"))
    return World()


def at(seconds: int):
    return NOW + timedelta(seconds=seconds)


def live(w: World, sym: str, ltp: float, *, t, **kw):
    w.now = t
    w.quotes[sym] = quote(ltp, at=t, **kw)
    return run(monitor.live_round(t, w.deps()))


def open_position(w: World, *, qty=100, sym="FIXA", **kw):
    """An entry filled in full by the monitor at 10:00:00 (ask 100.00 × 1.0005 = 100.05)."""
    o = run(w.entry(qty=qty, symbol=sym, **kw))
    live(w, sym, 100.0, t=NOW, bid=99.95, ask=100.0, ask_qty=10_000, bid_qty=10_000)
    pos = run(w.position_of(o["_id"]))
    assert pos is not None and pos["quantity"] == qty
    return o, pos


# ── SPT-C-19 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c19_stop_on_the_bid_exits_at_the_bid_not_the_stop(w):
    o, pos = open_position(w)
    assert run(store.get_position(w.db, pos["_id"]))["avg_entry_price"] == cost_card.paisa(100.0 * 1.0005)
    live(w, "FIXA", 96.4, t=at(15), bid=96.3, ask=96.5, bid_qty=10_000, ask_qty=10_000)    # above the stop
    assert run(store.get_position(w.db, pos["_id"]))["state"] == C.POS_MONITORING
    live(w, "FIXA", 95.9, t=at(30), bid=95.8, ask=95.9, bid_qty=10_000, ask_qty=10_000, open_=99.0)
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_CLOSED and p["exit_reason"] == "stop" and p["exit_gap"] is False
    exits = [f for f in w.db.docs(store.FILLS) if f["purpose"] == "EXIT"]
    assert len(exits) == 1 and exits[0]["price"] == cost_card.paisa(95.8 * 0.9995) and exits[0]["price"] != 96.0
    assert len(w.events("STOP_TRIGGERED")) == 1
    ex = run(store.get_order(w.db, exits[0]["order_id"]))
    assert ex["order_type"] == "MARKET" and ex["quantity"] == 100 and ex["trigger"]["basis"] == "bid"
    assert len(w.ledger("user_a", "release")) == 1
    # the next rounds see a closed position: nothing more
    live(w, "FIXA", 95.0, t=at(45), bid=94.9, ask=95.0, bid_qty=10_000)
    assert len([f for f in w.db.docs(store.FILLS) if f["purpose"] == "EXIT"]) == 1


# ── SPT-C-20 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c20_gap_through_the_stop_exits_at_the_first_live_bid(w):
    o, pos = open_position(w)
    nxt = ist(9, 15, 5, day=date(2026, 11, 6))
    live(w, "FIXA", 92.0, t=nxt, bid=91.9, ask=92.1, bid_qty=10_000, open_=92.0)
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_CLOSED and p["exit_reason"] == "stop" and p["exit_gap"] is True
    exit_fill = [f for f in w.db.docs(store.FILLS) if f["purpose"] == "EXIT"][0]
    assert exit_fill["gap"] is True and exit_fill["price"] == cost_card.paisa(91.9 * 0.9995)
    assert w.events("STOP_TRIGGERED")[0]["payload"]["gap"] is True


# ── SPT-C-21 / SPT-C-22 / SPT-C-35 ───────────────────────────────────────────────────────────────────────────────────
def test_c21_c22_c35_t1_breakeven_then_t2_and_the_outcome(w):
    o, pos = open_position(w)
    live(w, "FIXA", 108.2, t=at(15), bid=108.1, ask=108.2, bid_qty=10_000, ask_qty=10_000)
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["quantity"] == 50 and p["t1_done"] is True and p["state"] == C.POS_PARTIALLY_EXITED
    eq_costs_per_share = p["entry_costs_rs"] / 100
    exit_est = execution.exit_costs_per_share(p["avg_entry_price"], 50, p["cost_model"])
    be = math.ceil((p["avg_entry_price"] + eq_costs_per_share + exit_est) * 100 - 1e-6) / 100
    assert p["stop_loss"] == be and p["stop_loss"] > p["avg_entry_price"]
    assert p["stop_history"][-1]["reason"] == "breakeven_after_t1"
    assert p["modifications"][-1]["requested_by"] == positions.SERVICE_ACTOR
    assert len(w.events("STOP_MOVED")) == 1 and len(w.events("TARGET_TRIGGERED")) == 1
    # not triggered twice
    live(w, "FIXA", 109.0, t=at(30), bid=108.9, ask=109.0, bid_qty=10_000)
    assert run(store.get_position(w.db, pos["_id"]))["quantity"] == 50
    live(w, "FIXA", 116.5, t=at(45), bid=116.4, ask=116.5, bid_qty=10_000)
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_CLOSED and p["exit_reason"] == "target_2" and p["quantity"] == 0
    assert len(w.ledger("user_a", "release")) == 1
    acc = run(w.account("user_a"))
    assert acc["cash_rs"] == round(acct.DEFAULT_CAPITAL + p["realized_net_rs"], 2) and acc["blocked_rs"] == 0
    out = p["outcome"]
    assert out["exit_reason"] == "target_2" and out["quantity"] == 100 and len(out["entry_fills"]) == 1
    assert len(out["exit_fills"]) == 2 and out["realized_net_rs"] == p["realized_net_rs"]
    assert out["r_multiple"] == round(p["realized_net_rs"] / p["initial_risk_rs"], 3)
    assert out["entry_vs_plan_rs"] == round((p["avg_entry_price"] - 100.0) * 100, 2)
    assert out["planned_risk_rs"] == 400.0 and out["versions"]["execution"] == C.EXECUTION_VERSION
    assert out["holding_seconds"] == 45 and out["mfe_rs"] > 0 and out["costs_rs"]["total"] > 0
    assert len(w.events("TRADE_ANALYTICS_COMPLETED")) == 1 and len(w.events("POSITION_CLOSED")) == 1


def test_c21b_stop_after_t1_is_the_breakeven(w):
    o, pos = open_position(w)
    live(w, "FIXA", 108.2, t=at(15), bid=108.1, ask=108.2, bid_qty=10_000)
    be = run(store.get_position(w.db, pos["_id"]))["stop_loss"]
    live(w, "FIXA", be - 0.5, t=at(30), bid=be - 0.6, ask=be - 0.5, bid_qty=10_000)
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_CLOSED and p["exit_reason"] == "stop"
    assert p["realized_net_rs"] > 0                       # T1 profit kept; the rest out near breakeven


# ── SPT-C-23 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c23_kill_switch_cancels_entries_but_exits_still_fill(w):
    o, pos = open_position(w)
    pending = run(w.entry(symbol="FIXB", qty=50))
    run(rc.set_control(w.db, "user_a", field="kill_switch", value=True, reason="test halt", actor="tester"))
    w.quotes["FIXB"] = quote(100.0, at=at(15), bid=99.9, ask=100.0, ask_qty=10_000)
    live(w, "FIXA", 95.0, t=at(15), bid=94.9, ask=95.0, bid_qty=10_000)
    e = run(store.get_order(w.db, pending["_id"]))
    assert e["state"] == C.ORD_CANCELLED and e["cancel_reason"] == "kill_switch_on" and e["filled_quantity"] == 0
    assert e["reservation_state"] == "released"
    assert not [f for f in w.db.docs(store.FILLS) if f["order_id"] == pending["_id"]]
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_CLOSED and p["exit_reason"] == "stop"            # the exit still filled
    acc = run(w.account("user_a"))
    assert acc["blocked_rs"] == 0 and acc["reservations"] == []


# ── SPT-C-24 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c24_replaying_a_round_never_double_fills(w):
    o = run(w.entry(qty=100))
    w.quotes["FIXA"] = quote(100.0, at=NOW, bid=99.9, ask=100.0, ask_qty=40)
    for _ in range(3):
        run(monitor.live_round(NOW, w.deps()))
    assert run(store.get_order(w.db, o["_id"]))["filled_quantity"] == 40
    assert len(w.db.docs(store.FILLS)) == 1 and run(w.position_of(o["_id"]))["quantity"] == 40


def test_c24b_crash_after_the_fill_is_recovered_once(w):
    o = run(w.entry(qty=100))
    w.db[store.POSITIONS].fail_next["insert_one"] = RuntimeError("process died")
    w.db[store.FILLS].fail_next["insert_one"] = RuntimeError("process died")
    w.quotes["FIXA"] = quote(100.0, at=NOW, bid=99.9, ask=100.0, ask_qty=1000)
    out = run(monitor.live_round(NOW, w.deps()))
    assert out["counts"]["errors"] >= 1
    od = run(store.get_order(w.db, o["_id"]))
    assert od["filled_quantity"] == 100 and od["fills_seq"] == 1 and od["position_seq"] == 0
    assert w.db.docs(store.FILLS) == [] and run(w.position_of(o["_id"])) is None
    # restart: the next pass finishes it, once
    run(monitor.live_round(at(15), w.deps()))
    run(monitor.live_round(at(30), w.deps()))
    assert len(w.db.docs(store.FILLS)) == 1
    pos = run(w.position_of(o["_id"]))
    assert pos["quantity"] == 100 and len(pos["fill_ids"]) == 1
    assert len(w.events("POSITION_OPENED")) == 1 and len(w.events("PAPER_ORDER_FILLED")) == 1


def test_c24c_concurrent_writer_loses_cleanly(w):
    o = run(w.entry(qty=100))
    stale = run(store.get_order(w.db, o["_id"]))
    run(execution.execute_order(w.db, stale, quote(100.0, at=NOW, bid=99.9, ask=100.0, ask_qty=30), NOW,
                                session_open=True))
    # a second worker still holding the old version records nothing
    sim = execution.simulate(stale, quote(100.0, at=at(1), bid=99.9, ask=100.0, ask_qty=30), at(1), session_open=True)
    assert run(orders.record_fills(w.db, stale, sim, at(1))) is None
    assert run(store.get_order(w.db, o["_id"]))["filled_quantity"] == 30


# ── SPT-C-25 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def weekdays(start: date, n: int):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars_for(days, closes, *, spread=1.0, lows=None):
    """MOCK bars: high = close + spread, low = close − spread (unless given), open = close."""
    out = []
    for i, (d, c) in enumerate(zip(days, closes)):
        lo = lows[i] if lows and lows[i] is not None else c - spread
        out.append({"date": d, "open": c, "high": c + spread, "low": lo, "close": c, "volume": 100000})
    return out


def test_c25_evening_trail_raises_only_and_waits_for_todays_bar(w):
    o, pos = open_position(w, trail={"rule": "trail-atr-v1", "k": 2})
    before = weekdays(date(2026, 9, 24), 30)
    before = [d for d in before if d <= date(2026, 11, 5)][-30:]
    after = weekdays(date(2026, 11, 6), 3)                                 # 6, 9, 10 Nov
    w.bars["FIXA"] = bars_for(before + after, [100.0] * len(before) + [104.0, 107.0, 110.0])
    eve = ist(19, 0, day=date(2026, 11, 11))                               # today 11 Nov: no bar yet
    r = run(monitor.evening_round(eve, w.deps()))
    assert r["pending"] == ["FIXA"] and run(store.get_position(w.db, pos["_id"]))["stop_loss"] == 96.0
    eve = ist(19, 0, day=date(2026, 11, 10))
    r = run(monitor.evening_round(eve, w.deps()))
    p = run(store.get_position(w.db, pos["_id"]))
    # ATR seeded at 2.0 (flat bars, high − low = 2) → highest high 111 − 2 × ATR
    assert p["stop_loss"] > 96.0 and p["stop_history"][-1]["reason"] == "trailing_atr"
    assert p["sessions_held"] == 3 and p["evening_day"] == "2026-11-10" and p["state"] != C.POS_EXIT_PENDING
    raised = p["stop_loss"]
    assert run(monitor.evening_round(eve, w.deps()))["ran"] is False          # done for the day
    # a later, lower series never lowers the stop
    more = weekdays(date(2026, 11, 11), 1)
    w.bars["FIXA"] = w.bars["FIXA"] + bars_for(more, [108.5])
    run(monitor.evening_round(ist(19, 0, day=more[0]), w.deps()))
    assert run(store.get_position(w.db, pos["_id"]))["stop_loss"] >= raised
    # a stop hit after the trail is a `trailing` exit
    t = ist(9, 20, day=date(2026, 11, 12))
    live(w, "FIXA", raised - 1, t=t, bid=raised - 1.1, ask=raised - 1, bid_qty=10_000)
    assert run(store.get_position(w.db, pos["_id"]))["exit_reason"] == "trailing"


def test_c25b_trend_exit_pending_then_next_session_first_quote(w):
    o, pos = open_position(w, trend={"rule": "close_below_sma20"})
    before = [d for d in weekdays(date(2026, 9, 24), 40) if d <= date(2026, 11, 5)][-25:]
    after = weekdays(date(2026, 11, 6), 1)
    w.bars["FIXA"] = bars_for(before + after, [102.0] * len(before) + [99.5])
    run(monitor.evening_round(ist(19, 0, day=after[0]), w.deps()))
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_EXIT_PENDING and p["pending_exit"]["reason"] == "trend"
    assert p["pending_exit"]["sma20"] > 99.5
    assert w.db.docs(store.FILLS)[-1]["purpose"] == "ENTRY"                 # no fill from a bar
    t = ist(9, 15, 10, day=date(2026, 11, 9))
    live(w, "FIXA", 99.8, t=t, bid=99.7, ask=99.8, bid_qty=10_000)
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_CLOSED and p["exit_reason"] == "trend"


def test_c25c_time_exit_and_missed_stop(w):
    o, pos = open_position(w, max_hold=2)
    o2, pos2 = open_position(w, sym="FIXB")
    before = [d for d in weekdays(date(2026, 10, 1), 30) if d <= date(2026, 11, 5)][-20:]
    after = weekdays(date(2026, 11, 6), 2)
    w.bars["FIXA"] = bars_for(before + after, [100.0] * len(before) + [101.0, 101.5])
    w.bars["FIXB"] = bars_for(before + after, [100.0] * len(before) + [101.0, 97.0], lows=[None] * (len(before) + 1) + [95.5])
    run(monitor.evening_round(ist(19, 0, day=after[-1]), w.deps()))
    a = run(store.get_position(w.db, pos["_id"]))
    b = run(store.get_position(w.db, pos2["_id"]))
    assert a["state"] == C.POS_EXIT_PENDING and a["pending_exit"]["reason"] == "time" and a["sessions_held"] == 2
    assert b["state"] == C.POS_EXIT_PENDING and b["pending_exit"]["reason"] == "stop"
    assert b["pending_exit"]["note"] == "stop_breached_without_live_exit"


# ── SPT-C-26 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c26_gating_leader_and_robustness(w, monkeypatch):
    assert config.enabled({"APP_ENV": "staging"}) is True
    assert config.enabled({"APP_ENV": "staging", "SPT_C_ENABLED": "0"}) is False
    assert config.enabled({"APP_ENV": "production"}) is False
    assert config.enabled({"APP_ENV": "production", "SPT_C_ENABLED": "1"}) is True
    o = run(w.entry(qty=10))
    w.quotes["FIXA"] = quote(100.0, at=NOW, bid=99.9, ask=100.0, ask_qty=1000)
    follower = FakeLeader(me_is_leader=False)
    assert run(monitor.loop_once(NOW, w.deps(), leader_store=follower)) == "not_leader"
    assert run(store.get_order(w.db, o["_id"]))["filled_quantity"] == 0 and w.db.docs(store.STATE) == []

    async def broken(symbols, now):
        raise ConnectionError("feed down")

    deps = w.deps()
    deps.quotes = broken
    assert run(monitor.loop_once(NOW, deps, leader_store=FakeLeader())) == "live"
    st = run(store.read_state(w.db))
    assert st["live"]["feed_why"] == "unreadable" and st["live"]["counts"]["errors"] == 1
    assert st["startup"]["reconcile_ok"] is True
    assert run(store.get_order(w.db, o["_id"]))["last_attempt"]["reason"] == "quote_missing"
    # out of session: housekeeping only (expiry), no quote read
    w.quote_calls.clear()
    assert run(monitor.loop_once(ist(16, 0), w.deps(), leader_store=FakeLeader())) == "housekeeping"
    assert w.quote_calls == [] and run(store.get_order(w.db, o["_id"]))["state"] == C.ORD_EXPIRED


def test_c26b_start_respects_the_flag(monkeypatch):
    monkeypatch.setenv("SPT_C_ENABLED", "0")
    assert monitor.start() is False


def test_c25d_a_low_below_only_a_stop_raised_later_that_day_is_not_a_missed_stop(w):
    o, pos = open_position(w, max_hold=2.0)                                # a float from B still counts
    # 6 Nov: a dip to 97.0 in the morning (stop 96), then T1 at 108 moves the stop to breakeven (~100.4)
    d6 = date(2026, 11, 6)
    live(w, "FIXA", 97.1, t=ist(9, 30, day=d6), bid=97.0, ask=97.1, bid_qty=10_000)
    live(w, "FIXA", 108.2, t=ist(11, 0, day=d6), bid=108.1, ask=108.2, bid_qty=10_000)
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["t1_done"] and p["stop_loss"] > 100.0
    before = [d for d in weekdays(date(2026, 10, 1), 30) if d <= date(2026, 11, 5)][-20:]
    w.bars["FIXA"] = bars_for(before + [d6], [100.0] * len(before) + [107.0], lows=[None] * len(before) + [97.0])
    assert monitor.lowest_stop_today(p, d6) == 96.0
    run(monitor.evening_round(ist(19, 0, day=d6), w.deps()))
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] != C.POS_EXIT_PENDING and p["sessions_held"] == 1
    d9 = date(2026, 11, 9)
    w.bars["FIXA"] = w.bars["FIXA"] + bars_for([d9], [107.5])
    run(monitor.evening_round(ist(19, 0, day=d9), w.deps()))
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_EXIT_PENDING and p["pending_exit"]["reason"] == "time"
