"""SPT slice C — the API (routes/spt_paper.py): auth, ownership, every endpoint, stable error codes, and the P1 event
stream. Test cases SPT-C-32…34.

What is replaced: `route.db` (the in-memory FakeDb of tests/spt_c_fakes.py), `route.get_current_user` (reads the test's
X-Test-User header; 401 without it) and the modification's market reference reader. Everything else runs for real.
MOCK — not real data.
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import timedelta

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import spt_paper as route
from services.spt import constants as C
from services.spt.paper import monitor, store
from tests.spt_c_fakes import NOW, World, quote, reset_module_state

A = {"X-Test-User": "user_a"}
B = {"X-Test-User": "user_b"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env(monkeypatch):
    reset_module_state(monkeypatch)
    monkeypatch.setattr(monitor, "_started_up", False)
    w = World()
    monkeypatch.setattr(route, "db", w.db)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(route, "_quotes", w.read_quotes)
    # the API's own clock is the real one; the fixture's orders are created on it too
    w.now = store.utcnow()
    app = FastAPI()
    app.include_router(route.router)
    return w, TestClient(app)


def filled_position(w: World, user="user_a", sym="FIXA"):
    """An entry filled by the monitor at 10:00 IST (fixed clock), its position open."""
    w.now = NOW
    o = run(w.entry(user, symbol=sym, qty=100))
    w.quotes[sym] = quote(100.0, at=NOW, bid=99.95, ask=100.0, ask_qty=10_000, bid_qty=10_000)
    run(monitor.live_round(NOW, w.deps()))
    return o, run(w.position_of(o["_id"]))


# ── SPT-C-32 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c32_auth_and_ownership(env):
    w, c = env
    for method, url in (("get", "/api/v1/paper/orders"), ("get", "/api/v1/paper/positions"), ("get", "/api/v1/paper/trades"),
                        ("get", "/api/v1/paper/reconcile"), ("post", "/api/v1/paper/orders/x/cancel"),
                        ("get", "/api/v1/paper/positions/x"), ("get", "/api/v1/paper/stream")):
        assert getattr(c, method)(url).status_code == 401, url
    o, pos = filled_position(w)
    assert c.get(f"/api/v1/paper/orders/{o['_id']}", headers=B).json()["detail"]["code"] == "order_not_found"
    assert c.get(f"/api/v1/paper/positions/{pos['_id']}", headers=B).status_code == 404
    assert c.post(f"/api/v1/paper/positions/{pos['_id']}/exit", headers=B, json={}).status_code == 404
    assert c.post(f"/api/v1/paper/orders/{o['_id']}/cancel", headers=B).status_code == 404
    assert c.get("/api/v1/paper/orders", headers=B).json()["count"] == 0
    assert c.get("/api/v1/paper/positions", headers=B).json()["count"] == 0


def test_c32b_orders_endpoints(env):
    w, c = env
    o, pos = filled_position(w)
    pending = run(w.entry(symbol="FIXB", qty=10))
    r = c.get("/api/v1/paper/orders", headers=A, params={"state": "LIVE"})
    assert r.status_code == 200 and [x["order_id"] for x in r.json()["orders"]] == [pending["_id"]]
    assert c.get("/api/v1/paper/orders", headers=A, params={"state": "nope"}).json()["detail"]["code"] == "state_invalid"
    one = c.get(f"/api/v1/paper/orders/{o['_id']}", headers=A).json()["order"]
    assert one["state"] == C.ORD_FILLED and len(one["fills"]) == 1
    cx = c.post(f"/api/v1/paper/orders/{pending['_id']}/cancel", headers=A)
    assert cx.status_code == 200 and cx.json()["order"]["state"] == C.ORD_CANCELLED
    again = c.post(f"/api/v1/paper/orders/{pending['_id']}/cancel", headers=A)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "order_not_live"


def test_c32c_entry_needs_a_ready_proposal_and_b(env, monkeypatch):
    w, c = env
    r = c.post("/api/v1/paper/orders", headers=A, json={"purpose": "ENTRY", "proposal_id": "p1"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "entry_requires_approved_proposal"
    run(w.db[C.PROPOSALS].insert_one({"_id": "p1", "user_id": "user_a", "state": C.PROP_AWAITING_USER}))
    run(w.db[C.PROPOSALS].insert_one({"_id": "p2", "user_id": "user_b", "state": C.PROP_READY_FOR_ORDER}))
    run(w.db[C.PROPOSALS].insert_one({"_id": "p3", "user_id": "user_a", "state": C.PROP_READY_FOR_ORDER}))
    assert c.post("/api/v1/paper/orders", headers=A, json={"purpose": "ENTRY", "proposal_id": "p1"}).status_code == 422
    assert c.post("/api/v1/paper/orders", headers=A, json={"purpose": "ENTRY", "proposal_id": "p2"}).status_code == 422
    monkeypatch.setitem(sys.modules, "services.spt.pipeline", None)
    import services.spt as _spt_pkg                                      # once B's real module is loaded, the package
    monkeypatch.delattr(_spt_pkg, "pipeline", raising=False)             # attribute must go too, or the import finds it
    r3 = c.post("/api/v1/paper/orders", headers=A, json={"purpose": "ENTRY", "proposal_id": "p3"})
    assert r3.status_code == 503 and r3.json()["detail"]["code"] == "entry_pipeline_unavailable"
    calls = []
    fake = types.ModuleType("services.spt.pipeline")

    async def place_entry_order(db, *, user_id, proposal_id, actor_id):
        calls.append((user_id, proposal_id, actor_id))
        return await w.entry(user_id, symbol="FIXP", qty=5, order_id="from-b")

    fake.place_entry_order = place_entry_order
    monkeypatch.setitem(sys.modules, "services.spt.pipeline", fake)
    import services.spt as spt_pkg
    monkeypatch.setattr(spt_pkg, "pipeline", fake, raising=False)
    r4 = c.post("/api/v1/paper/orders", headers=A, json={"purpose": "ENTRY", "proposal_id": "p3"})
    assert r4.status_code == 200 and r4.json()["order"]["order_id"] == "from-b" and calls == [("user_a", "p3", "user_a")]
    assert c.post("/api/v1/paper/orders", headers=A, json={"purpose": "BUY"}).json()["detail"]["code"] == "purpose_invalid"


def test_c32d_positions_modify_trades_reconcile(env):
    w, c = env
    o, pos = filled_position(w)
    lst = c.get("/api/v1/paper/positions", headers=A).json()
    assert lst["count"] == 1 and lst["positions"][0]["position_id"] == pos["_id"]
    det = c.get(f"/api/v1/paper/positions/{pos['_id']}", headers=A).json()
    assert len(det["fills"]) == 1 and det["position"]["quantity"] == 100
    types_ = {e["event_type"] for e in det["events"]}
    assert {"PAPER_ORDER_CREATED", "PAPER_ORDER_FILLED", "POSITION_OPENED"} <= types_
    m = c.post(f"/api/v1/paper/positions/{pos['_id']}/modify", headers=A,
               json={"change": {"kind": "stop_loss", "value": 97.5}, "reason": "tighter"})
    assert m.status_code == 200 and m.json()["position"]["stop_loss"] == 97.5
    bad = c.post(f"/api/v1/paper/positions/{pos['_id']}/modify", headers=A, json={"change": {"kind": "nonsense"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "modification_kind_invalid"
    stale = c.post(f"/api/v1/paper/positions/{pos['_id']}/modify", headers=A,
                   json={"change": {"kind": "target_1", "value": 109}, "expect_version": 0})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "position_changed"
    det = c.get(f"/api/v1/paper/positions/{pos['_id']}", headers=A).json()
    assert det["modifications"][-1]["new"] == 97.5
    # close it through the API and let the monitor fill the exit
    ex = c.post(f"/api/v1/paper/positions/{pos['_id']}/exit", headers=A, json={})
    assert ex.status_code == 200 and ex.json()["order"]["reason"] == "manual"
    t = NOW + timedelta(seconds=15)
    w.quotes["FIXA"] = quote(102.0, at=t, bid=102.0, ask=102.1, bid_qty=10_000)
    run(monitor.live_round(t, w.deps()))
    run(w.db[C.OPPORTUNITIES].insert_one({"_id": "opp-FIXA", "signals": [{"signal_id": "sig:2026-11-05:strong:FIXA"}]}))
    trades = c.get("/api/v1/paper/trades", headers=A).json()
    assert trades["count"] == 1
    tr = trades["trades"][0]
    assert tr["trade_id"] == pos["_id"] and tr["exit_reason"] == "manual" and tr["release_state"] == "done"
    assert tr["signal_ids"] == ["sig:2026-11-05:strong:FIXA"] and tr["opportunity_id"] == "opp-FIXA"
    assert tr["proposal_id"] == f"prop-{o['_id']}" and tr["r_multiple"] is not None and tr["mfe_rs"] is not None
    one = c.get(f"/api/v1/paper/trades/{pos['_id']}", headers=A).json()
    assert one["outcome"]["exit_reason"] == "manual" and one["trade"]["realized_net_rs"] == tr["realized_net_rs"]
    assert c.get(f"/api/v1/paper/trades/{pos['_id']}", headers=B).status_code == 404
    rec = c.get("/api/v1/paper/reconcile", headers=A).json()
    assert rec["ok"] is True and rec["user_id"] == "user_a"
    assert c.get("/api/v1/paper/positions", headers=A, params={"status": "closed"}).json()["count"] == 1


# ── SPT-C-33 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c33_manual_exit_twice_is_one_order(env):
    w, c = env
    o, pos = filled_position(w)
    a = c.post(f"/api/v1/paper/positions/{pos['_id']}/exit", headers=A, json={})
    b = c.post("/api/v1/paper/orders", headers=A, json={"purpose": "EXIT", "position_id": pos["_id"]})
    assert a.status_code == 200 and b.status_code == 200
    assert b.json()["order"]["order_id"] == a.json()["order"]["order_id"] and b.json()["duplicate"] is True
    exits = [x for x in w.db.docs(store.ORDERS) if x["purpose"] == "EXIT"]
    assert len(exits) == 1
    part = c.post(f"/api/v1/paper/positions/{pos['_id']}/exit", headers=A, json={"quantity": 10})
    assert part.status_code == 200 and part.json()["duplicate"] is True        # the live full exit covers it


# ── SPT-C-34 (P1) ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_c34_events_after_sends_only_new_events_of_the_caller(env):
    w, c = env
    o, pos = filled_position(w)
    filled_position(w, user="user_b", sym="FIXB")
    first, cur, seen = run(route.events_after(w.db, "user_a", "", set()))
    assert first and all(e["account_id"] == "user_a" for e in first)
    again, cur2, seen2 = run(route.events_after(w.db, "user_a", cur, seen))
    assert again == [] and cur2 == cur
    assert c.post(f"/api/v1/paper/positions/{pos['_id']}/exit", headers=A, json={}).status_code == 200
    new, _, _ = run(route.events_after(w.db, "user_a", cur, seen))
    assert [e["event_type"] for e in new] == ["PAPER_ORDER_CREATED"]


def test_c34b_stream_endpoint(env, monkeypatch):
    w, c = env
    monkeypatch.setattr(route, "STREAM_MAX_SECONDS", 0.3)
    monkeypatch.setattr(route, "STREAM_POLL_SECONDS", 0.05)
    o, pos = filled_position(w)
    with c.stream("GET", "/api/v1/paper/stream", headers=A, params={"since": "2000-01-01"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert body.startswith("retry: 3000") and "event: POSITION_OPENED" in body and "event: PAPER_ORDER_FILLED" in body
    assert body.count("event: POSITION_OPENED") == 1
