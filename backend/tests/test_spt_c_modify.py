"""SPT slice C — position modifications (WF §14) and reconciliation (WF §20.3). Test cases SPT-C-27…31.

Slice B's `services.spt.risk.check_modification` is replaced by a FAKE module put in sys.modules (B's code is not in
this branch); the fake records every call and answers what the test says. In-memory fakes otherwise
(tests/spt_c_fakes.py). MOCK — not real data.
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import timedelta

import pytest

from services import paper_account as acct
from services import risk_controls as rc
from services.spt import constants as C
from services.spt.paper import modify, monitor, orders, positions, reconcile, store
from tests.spt_c_fakes import NOW, World, quote, reset_module_state


def run(coro):
    return asyncio.run(coro)


class FakeRisk(types.ModuleType):
    """MOCK slice B: services.spt.risk with check_modification answering `self.answer`."""

    def __init__(self):
        super().__init__("services.spt.risk")
        self.calls = []
        self.answer = {"decision": C.RISK_APPROVE, "reason_codes": [], "explanations": [], "decision_id": "dec-1"}

    async def check_modification(self, db, *, user_id, position, change):
        self.calls.append({"user_id": user_id, "position_id": position["position_id"], "change": change})
        return dict(self.answer)


@pytest.fixture
def w(monkeypatch):
    reset_module_state(monkeypatch)
    monkeypatch.setattr(monitor, "_started_up", False)
    return World()


@pytest.fixture
def b(monkeypatch):
    fake = FakeRisk()
    monkeypatch.setitem(sys.modules, "services.spt.risk", fake)
    import services.spt as spt_pkg
    monkeypatch.setattr(spt_pkg, "risk", fake, raising=False)
    return fake


def opened(w: World, **kw):
    o = run(w.entry(qty=100, **kw))
    w.quotes["FIXA"] = quote(100.0, at=NOW, bid=99.95, ask=100.0, ask_qty=10_000, bid_qty=10_000)
    run(monitor.live_round(NOW, w.deps()))
    return o, run(w.position_of(o["_id"]))


def mod(w, pos, change, **kw):
    return run(modify.modify_position(w.db, user_id=kw.pop("user_id", "user_a"), position_id=pos["_id"], change=change,
                                      reason=kw.pop("reason", "test"), requested_by="user_a", quotes=w.read_quotes,
                                      now=kw.pop("now", NOW + timedelta(seconds=5)), **kw))


# ── SPT-C-27 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c27_reducing_changes_apply_without_b_also_under_the_kill_switch(w, b):
    o, pos = opened(w)
    run(rc.set_control(w.db, "user_a", field="kill_switch", value=True, reason="halt", actor="tester"))
    out = mod(w, pos, {"kind": "stop_loss", "value": 98.0})
    p = out["position"]
    assert p["stop_loss"] == 98.0 and p["stop_version"] == 2 and b.calls == []
    rec = p["modifications"][-1]
    assert rec["previous"] == 96.0 and rec["new"] == 98.0 and rec["risk_class"] == "reducing"
    assert rec["requested_by"] == "user_a" and rec["reason"] == "test" and rec["risk_decision"] is None
    assert rec["market_ref"]["available"] is True and rec["market_ref"]["bid"] == 99.95
    assert rec["position_id"] == pos["_id"] and rec["at"]
    assert len(w.events("POSITION_MODIFIED")) == 1 and len(w.events("STOP_MOVED")) == 1
    t = mod(w, pos, {"kind": "target_1", "value": 110.0})
    assert t["position"]["target_1"] == 110.0 and t["modification"]["risk_class"] == "neutral"
    tr = mod(w, pos, {"kind": "trailing", "enabled": True, "k": 3})
    assert tr["position"]["trail"] == {"rule": "trail-atr-v1", "k": 3.0}
    assert b.calls == []


# ── SPT-C-28 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c28_increasing_changes_go_to_b(w, b):
    o, pos = opened(w, trail={"rule": "trail-atr-v1", "k": 2})
    b.answer = {"decision": C.RISK_REJECT, "reason_codes": ["open_risk_exceeded"], "explanations": ["x"], "decision_id": "d9"}
    with pytest.raises(modify.ModifyRefused) as e:
        mod(w, pos, {"kind": "stop_loss", "value": 94.0})
    assert e.value.code == "modification_rejected_by_risk" and e.value.status == 409
    assert e.value.detail["reason_codes"] == ["open_risk_exceeded"]
    assert b.calls[-1]["change"] == {"kind": "stop_loss", "field": "stop_loss", "previous": 96.0, "new": 94.0}
    assert run(store.get_position(w.db, pos["_id"]))["stop_loss"] == 96.0            # nothing changed
    b.answer = {"decision": C.RISK_APPROVE, "reason_codes": [], "decision_id": "d10"}
    out = mod(w, pos, {"kind": "stop_loss", "value": 94.0})
    assert out["position"]["stop_loss"] == 94.0
    assert out["modification"]["risk_decision"] == {"decision": C.RISK_APPROVE, "reason_codes": [], "decision_id": "d10"}
    assert out["position"]["initial_stop"] == 96.0                                   # R stays on the plan's stop
    off = mod(w, pos, {"kind": "trailing", "enabled": False})
    assert off["position"]["trail"] is None and len(b.calls) == 3
    rm = mod(w, pos, {"kind": "stop_loss", "value": None})
    assert rm["position"]["stop_loss"] is None and rm["modification"]["risk_class"] == "increasing"


def test_c28b_increasing_refused_under_kill_switch_and_without_b(w, monkeypatch):
    o, pos = opened(w)
    monkeypatch.setitem(sys.modules, "services.spt.risk", None)          # B's module not importable
    with pytest.raises(modify.ModifyRefused) as e:
        mod(w, pos, {"kind": "stop_loss", "value": 95.0})
    assert e.value.code == "risk_check_unavailable" and e.value.status == 503
    run(rc.set_control(w.db, "user_a", field="kill_switch", value=True, reason="halt", actor="tester"))
    with pytest.raises(modify.ModifyRefused) as e2:
        mod(w, pos, {"kind": "stop_loss", "value": 95.0})
    assert e2.value.code == "risk_increase_blocked"
    with pytest.raises(modify.ModifyRefused) as e3:
        mod(w, pos, {"kind": "stop_loss", "value": 120.0})              # above the target
    assert e3.value.code == "stop_not_below_target" and e3.value.status == 422


# ── SPT-C-29 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c29_target_reached_while_the_stop_is_being_modified(w, b):
    o, pos = opened(w)
    seen = run(store.get_position(w.db, pos["_id"]))["version"]
    # the monitor reaches T1 between the user's read and the user's write
    w.quotes["FIXA"] = quote(108.5, at=NOW + timedelta(seconds=15), bid=108.4, ask=108.5, bid_qty=10_000)
    run(monitor.live_round(NOW + timedelta(seconds=15), w.deps()))
    after_t1 = run(store.get_position(w.db, pos["_id"]))
    assert after_t1["t1_done"] is True and after_t1["version"] > seen
    with pytest.raises(modify.ModifyRefused) as e:
        mod(w, pos, {"kind": "stop_loss", "value": 99.0}, expect_version=seen)
    assert e.value.code == "position_changed" and e.value.status == 409
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["stop_loss"] == after_t1["stop_loss"]                      # the breakeven move is not lost


# ── SPT-C-30 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c30_reduce_and_close_work_under_the_kill_switch(w, b):
    o, pos = opened(w)
    run(rc.set_control(w.db, "user_a", field="kill_switch", value=True, reason="halt", actor="tester"))
    red = mod(w, pos, {"kind": "reduce_quantity", "quantity": 40})
    assert red["order"]["purpose"] == "EXIT" and red["order"]["quantity"] == 40 and red["order"]["reason"] == "manual"
    w.quotes["FIXA"] = quote(101.0, at=NOW + timedelta(seconds=15), bid=101.0, ask=101.1, bid_qty=10_000)
    run(monitor.live_round(NOW + timedelta(seconds=15), w.deps()))
    assert run(store.get_position(w.db, pos["_id"]))["quantity"] == 60
    c1 = mod(w, pos, {"kind": "close"}, now=NOW + timedelta(seconds=20))
    c2 = run(orders.create_exit_order(w.db, position_id=pos["_id"], reason="manual", now=NOW + timedelta(seconds=21)))
    assert c2["_id"] == c1["order"]["_id"] and c2["duplicate"] is True
    w.quotes["FIXA"] = quote(101.0, at=NOW + timedelta(seconds=30), bid=101.0, ask=101.1, bid_qty=10_000)
    run(monitor.live_round(NOW + timedelta(seconds=30), w.deps()))
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_CLOSED and p["exit_reason"] == "manual" and b.calls == []
    assert len(w.ledger("user_a", "release")) == 1


# ── SPT-C-31 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c31_reconciliation_report_and_startup_marks(w):
    o, pos = opened(w)
    clean = run(reconcile.report(w.db, user_id="user_a", now=NOW))
    assert clean["ok"] is True and clean["counts"]["orders"] == 1 and clean["counts"]["fills"] == 1
    # break things the way a bug or a manual edit would
    run(w.db[store.ORDERS].update_one({"_id": o["_id"]}, {"$set": {"filled_quantity": 90, "remaining_quantity": 10}}))
    run(w.db[store.POSITIONS].update_one({"_id": pos["_id"]}, {"$set": {"quantity": 120}}))
    leak = run(w.reserve("user_a", "ghost-order", qty=5, entry=50.0, stop=45.0, symbol="FIXZ"))
    closed = dict(run(store.get_position(w.db, pos["_id"])), _id="closed-1", entry_order_id="gone", state=C.POS_CLOSED,
                  is_open=False, quantity=0, release={"state": "missing_reservation"})
    run(w.db[store.POSITIONS].insert_one(closed))
    run(w.db[store.ORDERS].insert_one(dict(run(store.get_order(w.db, o["_id"])), _id="orph", idempotency_key="k-orph",
                                           filled_quantity=10, remaining_quantity=0, quantity=10,
                                           fills=[{"quantity": 10}])))
    rep = run(reconcile.report(w.db, user_id="user_a", now=NOW))
    codes = {m["code"] for m in rep["mismatches"]}
    assert {"order_fill_mismatch", "position_quantity_mismatch", "reservation_without_order_or_position",
            "closed_without_release", "fill_without_position"} <= codes
    assert rep["ok"] is False
    cash_before = run(w.account("user_a"))["cash_rs"]
    blocked_before = run(w.account("user_a"))["blocked_rs"]
    run(reconcile.startup_check(w.db, now=NOW))
    p = run(store.get_position(w.db, pos["_id"]))
    assert p["state"] == C.POS_RECONCILIATION_REQUIRED and "position_quantity_mismatch" in p["reconciliation"]["codes"]
    assert p["reconciliation"]["state_before"] == C.POS_MONITORING or p["reconciliation"]["state_before"] == C.POS_OPEN
    assert run(store.get_position(w.db, "closed-1"))["reconciliation"]["codes"] == ["closed_without_release"]
    acc = run(w.account("user_a"))
    assert acc["cash_rs"] == cash_before and acc["blocked_rs"] == blocked_before        # no money moved
    assert any(r["id"] == leak["reservation_id"] for r in acc["reservations"])
    # no automatic exit for it; a manual exit is still allowed
    w.quotes["FIXA"] = quote(90.0, at=NOW + timedelta(seconds=15), bid=90.0, ask=90.1, bid_qty=10_000)
    run(monitor.live_round(NOW + timedelta(seconds=15), w.deps()))
    assert run(store.get_position(w.db, pos["_id"]))["state"] == C.POS_RECONCILIATION_REQUIRED
    ex = run(orders.create_exit_order(w.db, position_id=pos["_id"], reason="manual", now=NOW + timedelta(seconds=16)))
    assert ex["state"] == C.ORD_PENDING
