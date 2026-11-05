"""SPT slice B — the calls slice C makes into B (integrator's contract notes, 5 Nov ~02:50 IST) and the SPT positions'
P&L B reads from slice C's store (TESTCASES SPT-B-39..44).

    place_entry_order(db, *, user_id, proposal_id, actor_id) -> order        (C's POST /api/v1/paper/orders, ENTRY)
    kill_switch_state(db, user_id=...) -> {entries_blocked, blocking, kill_switch, halted, state, reasons, code, reason}
    create_entry_order returns a REJECTED order (reservation already given back) instead of raising
    spt_positions: realized_net_rs + mark.unrealized_net_rs in B's equity, drawdown and day / week loss
MOCK — not real data: every user, symbol, price, position and order is made up."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi import HTTPException

from services import paper_account as acct
from services import risk_controls as rc
from services.spt import allocation, constants as C, pipeline, risk
from tests.spt_b_fakes import NOW, U1, U2, opportunity, world  # noqa: F401 (world is a fixture)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def setup(world, mode="auto", px=502.0):
    world.store.add(opportunity())
    world.quote("FIXA", px, ask=px)
    run(world.set_mode(U1, mode))


def only(world):
    [p] = world.proposals(U1)
    return p


# ── SPT-B-39 place_entry_order ───────────────────────────────────────────────
def test_spt_b_39_place_entry_order_retries_a_failed_create_with_fresh_risk(world):
    setup(world)
    world.orders.fail = RuntimeError("MOCK slice C down")
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_READY_FOR_ORDER and p["order_error"]["reservation_released"]
    world.orders.fail = None
    later = NOW + timedelta(minutes=1)
    world.quote("FIXA", 502.5, ask=502.5, at=later)
    order = run(pipeline.place_entry_order(world.db, user_id=U1, proposal_id=p["_id"], actor_id=U1, now=later))
    p = only(world)
    assert p["state"] == C.PROP_ORDER_CREATED and order["_id"] == p["order_id"] == p["risk"]["order_id"]
    first, second = world.orders.calls
    assert first["order_id"] != second["order_id"] and second["actor_id"] == U1
    assert second["idempotency_key"] == first["idempotency_key"] == f"spt:{U1}:opp-FIXA:entry"
    [res] = world.account(U1)["reservations"]
    assert res["trade_id"] == order["_id"] and p["order_error"] is None and len(p["risk_history"]) == 2
    again = run(pipeline.place_entry_order(world.db, user_id=U1, proposal_id=p["_id"], actor_id=U1, now=later))
    assert again["_id"] == order["_id"] and again["duplicate"] is True and len(world.orders.calls) == 2


def test_spt_b_39b_place_entry_order_refusals_are_http_errors(world):
    setup(world)
    world.orders.fail = RuntimeError("MOCK slice C down")
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    with pytest.raises(HTTPException) as e:                              # another user's proposal
        run(pipeline.place_entry_order(world.db, user_id=U2, proposal_id=p["_id"], actor_id=U2, now=NOW))
    assert e.value.status_code == 404 and e.value.detail["code"] == "proposal_not_found"
    world.store.opps["opp-FIXA"]["state"] = C.OPP_EXPIRED
    with pytest.raises(pipeline.PipelineError) as e:
        run(pipeline.place_entry_order(world.db, user_id=U1, proposal_id=p["_id"], actor_id=U1, now=NOW))
    assert e.value.status_code == 409 and e.value.detail["code"] == "entry_no_longer_valid"
    assert e.value.detail["reason_codes"] == ["opportunity_not_qualified"]
    p = only(world)
    assert p["state"] == C.PROP_READY_FOR_ORDER and p["last_place_refusal"]["code"] == "approval_expired"
    world.store.opps["opp-FIXA"]["state"] = C.OPP_QUALIFIED
    rc_ = run(rc.set_control(world.db, U1, field="kill_switch", value=True, reason="MOCK", actor=U1, now=NOW))
    assert rc_["kill_switch"]
    with pytest.raises(pipeline.PipelineError) as e:
        run(pipeline.place_entry_order(world.db, user_id=U1, proposal_id=p["_id"], actor_id=U1, now=NOW))
    assert e.value.detail["code"] == "risk_refused" and e.value.detail["decision"] == C.RISK_HALT
    assert not world.account(U1).get("reservations") and len(world.orders.calls) == 1


def test_spt_b_39c_place_entry_order_on_an_awaiting_proposal_is_an_approval(world):
    setup(world, mode="approval")
    run(pipeline.run_round(world.db, NOW))
    p = only(world)
    order = run(pipeline.place_entry_order(world.db, user_id=U1, proposal_id=p["_id"], actor_id=U1, now=NOW))
    assert order["state"] == C.ORD_PENDING and only(world)["state"] == C.PROP_ORDER_CREATED
    assert only(world)["approval"]["decision"] == "approved"
    with pytest.raises(pipeline.PipelineError) as e:                     # a refused proposal gets no order
        world.store.add(opportunity("FIXB", horizon="intraday"))
        world.quote("FIXB", 500.0)
        run(pipeline.run_round(world.db, NOW))
        q = next(x for x in world.proposals(U1) if x["symbol"] == "FIXB")
        run(pipeline.place_entry_order(world.db, user_id=U1, proposal_id=q["_id"], actor_id=U1, now=NOW))
    assert e.value.detail["code"] == "invalid_state" and e.value.detail["state"] == C.PROP_NOT_TRADABLE


# ── SPT-B-40 slice C's REJECTED order ────────────────────────────────────────
def test_spt_b_40_a_rejected_order_ends_the_proposal_and_is_not_released_twice(world):
    setup(world)
    world.orders.reject_reason = "MOCK entries_blocked"
    report = run(pipeline.run_round(world.db, NOW))
    p = only(world)
    assert p["state"] == C.PROP_ORDER_CREATED and p["order_rejected"] is True
    assert p["order"]["state"] == C.ORD_REJECTED and p["order"]["reject_reason"] == "MOCK entries_blocked"
    assert report["orders_rejected"] == 1 and report["orders"] == 0
    actions = [r["action"] for r in world.db.docs(acct.LEDGER)]
    assert actions == ["reserve", "cancel_reservation"]                  # C gave it back once; B did not again
    assert world.account(U1)["reservations"] == [] and world.account(U1)["blocked_rs"] == 0.0


# ── SPT-B-41 kill_switch_state for slice C ───────────────────────────────────
def test_spt_b_41_kill_switch_state_carries_the_keys_slice_c_reads(world):
    run(world.set_mode(U1, "auto"))
    ks = run(risk.kill_switch_state(world.db, user_id=U1))
    assert (ks["state"], ks["entries_blocked"], ks["blocking"], ks["kill_switch"], ks["halted"]) == \
        ("ACTIVE", False, False, False, False)
    assert ks["code"] is None and ks["reason"] is None
    run(rc.set_control(world.db, U1, field="halted", value=True, reason="MOCK halt", actor=U1, now=NOW))
    ks = run(risk.kill_switch_state(world.db, user_id=U1))              # the cached account part, controls re-read
    assert ks["state"] == "TRIGGERED" and ks["entries_blocked"] and ks["halted"] and ks["code"] == "trading_halted"
    assert "MOCK halt" in ks["reason"]


def test_spt_b_41b_the_ladder_and_period_losses_block_entries(world):
    run(world.set_mode(U1, "auto"))
    run(acct.ensure(world.db, U1))
    for dd, state in ((7.5, "RESTRICTED"), (10.5, "TRIGGERED"), (4.0, "ACTIVE")):       # ladder 3.33 / 6.67 / 10
        world.account(U1)["equity_peak_rs"] = round(1_000_000.0 / (1 - dd / 100.0), 2)
        ks = run(risk.kill_switch_state(world.db, U1, now=NOW))
        assert ks["state"] == state and ks["entries_blocked"] is (state != "ACTIVE"), dd


# ── SPT-B-42..44 the SPT positions' P&L ──────────────────────────────────────
def position(sym="FIXP", *, mark=None, opened=NOW - timedelta(hours=1), state=C.POS_MONITORING, realized=0.0,
             closed=None, release=None, qty=100, entry_costs=60.0):
    """MOCK — a slice C position document (services/spt/paper/positions.new_position fields B reads)."""
    return {"_id": f"pos-{sym}", "user_id": U1, "symbol": sym, "state": state, "quantity": qty, "avg_entry_price": 500.0,
            "realized_net_rs": realized, "entry_costs_rs": entry_costs, "opened_at": opened.isoformat(),
            "closed_at": closed.isoformat() if closed else None, "release": release,
            "mark": None if mark is None else {"unrealized_net_rs": mark, "at": (NOW - timedelta(seconds=20)).isoformat()}}


def test_spt_b_42_an_open_spt_loss_today_counts_in_equity_and_the_daily_loss(world):
    run(world.set_mode(U1, "auto"))
    run(world.db[C.POSITIONS].insert_one(position(mark=-30_000.0)))
    s = run(allocation.account_state(world.db, U1, now=NOW))
    assert s["book_equity_rs"] == 1_000_000.0 and s["equity_rs"] == 970_000.0
    assert s["day_pnl_rs"] == -30_000.0 and s["day_start_equity_rs"] == 1_000_000.0
    assert s["drawdown_pct"] == 3.0 and s["ladder"]["band"] == "normal"                 # reduce starts at 3.33
    ks = run(risk.kill_switch_state(world.db, U1, now=NOW, state=s))
    assert ks["state"] == "RESTRICTED" and ks["entries_blocked"] and "daily_loss_halt" in [r["code"] for r in ks["reasons"]]


def test_spt_b_43_positions_held_from_before_the_period_count_losses_only(world):
    run(world.set_mode(U1, "auto"))
    last_friday = NOW - timedelta(days=6)                               # before this ISO week (Monday 2 Nov)
    run(world.db[C.POSITIONS].insert_one(position("LOSS", mark=-5_000.0, opened=last_friday)))
    run(world.db[C.POSITIONS].insert_one(position("GAIN", mark=8_000.0, opened=last_friday)))
    run(world.db[C.POSITIONS].insert_one(position("MON", mark=1_000.0, opened=NOW - timedelta(days=3))))   # this Monday
    sp = run(allocation.spt_pnl(world.db, U1, now=NOW))
    assert sp["equity_adjustment_rs"] == 4_000.0 and sp["day_pnl_rs"] == -5_000.0 and sp["week_pnl_rs"] == -4_000.0
    assert sp["conservative"] == ["LOSS (day)", "LOSS (week)"] and sp["conservative_text"]
    # closed today and paid out: in cash already, and in the day's P&L
    run(world.db[C.POSITIONS].insert_one(position("DONE", state=C.POS_CLOSED, realized=-2_000.0, opened=NOW - timedelta(hours=3),
                                                  closed=NOW - timedelta(hours=1), release={"state": "done"})))
    sp = run(allocation.spt_pnl(world.db, U1, now=NOW))
    assert sp["equity_adjustment_rs"] == 4_000.0 and sp["day_pnl_rs"] == -7_000.0 and sp["week_pnl_rs"] == -6_000.0


@pytest.mark.parametrize("opened_ago, mark_at_ago, unknown", [
    (timedelta(minutes=10), None, True),                     # no mark long after the fill
    (timedelta(minutes=1), None, False),                     # just filled: valued at its fill
    (timedelta(days=6), timedelta(days=5), True),            # a stale mark
])
def test_spt_b_44_an_unmarked_or_stale_spt_position_makes_equity_unknown(world, opened_ago, mark_at_ago, unknown):
    run(world.set_mode(U1, "auto"))
    doc = position(opened=NOW - opened_ago)
    if mark_at_ago is not None:
        doc["mark"] = {"unrealized_net_rs": -100.0, "at": (NOW - mark_at_ago).isoformat()}
    run(world.db[C.POSITIONS].insert_one(doc))
    s = run(allocation.account_state(world.db, U1, now=NOW))
    if unknown:
        assert s["equity_rs"] is None and s["ladder"]["band"] == "unknown"
        assert run(risk.kill_switch_state(world.db, U1, now=NOW, state=s))["entries_blocked"] is True
    else:
        assert s["equity_rs"] == 1_000_000.0 - 60.0 and s["spt_pnl"]["conservative"] == ["FIXP (valued at its fill: no mark yet)"]
