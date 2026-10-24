"""The F&O risk gate wired into the desk paper trade and the journal, and the journal add_fill fix: TESTCASES W-1 to
W-8 and S-1 to S-3.

The desk tests reuse tests/test_desk_trading.py's `world` and `api` harness (the desk's own fakes and clock); the
journal has no harness of its own, so it runs on tests.test_risk_gate.FakeDB. In both, `risk_gate.enabled_for` is
replaced to switch the flag per test, and `reference.lookup` serves the exchange lot and listed expiry.

MOCK — not real data: FIXA / FIXU, their prices, lots and expiries are made up (the desk suites' fixtures).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from core.correlation import CorrelationMiddleware
from routes import desk_trading as desk_route
from routes import positional_journal as journal
from services import paper_account as acct
from services import risk_controls as rc
from services import risk_gate
from services.risk_gate import reference
from tests.test_desk_strategy_trades import EXPIRY, future, strategy_body
from tests.test_desk_trading import (  # noqa: F401  (`world` and `api` are fixtures)
    A, TRADES_URL, FakeCollection, api, trade_body, world,
)
from tests.test_risk_gate import FakeDB, run


def _listed(lot):
    return {"listed": True, "lot_size": lot, "source": reference.BHAVCOPY_SOURCE, "as_of": "2026-10-09",
            "error": None if lot else "the bhavcopy has no single lot size for that contract"}


@pytest.fixture
def gate(world, monkeypatch):
    """The desk world with the gate switchable (on by default) and the exchange reference faked."""
    world.db.cols["live_authorizations"] = FakeCollection()          # asked for by the gate's index setup
    world.gate_on = True
    world.refs = {EXPIRY: _listed(250)}
    monkeypatch.setattr(rc, "_indexes_ready", False)
    monkeypatch.setattr(rc, "utcnow", lambda: world.now)              # the gate's clock is the desk's

    async def enabled_for(_db, user):
        return world.gate_on
    monkeypatch.setattr(risk_gate, "enabled_for", enabled_for)

    async def lookup(underlying, expiries, today):
        return {e: world.refs.get(e, {"listed": False, "lot_size": None, "source": reference.BHAVCOPY_SOURCE,
                                      "as_of": "2026-10-09", "error": "no contract"}) for e in expiries}
    monkeypatch.setattr(reference, "lookup", lookup)
    return world


@pytest.fixture
def capi(gate):
    """The desk router behind the real correlation middleware, so X-Correlation-ID reaches the gate."""
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)
    app.include_router(desk_route.router)
    return TestClient(app)


def decisions(world):
    return world.db.cols[rc.DECISIONS].docs


def untouched_account(world):
    return world.db.cols[acct.ACCOUNTS].docs == [] and world.db.cols[acct.LEDGER].docs == []


# ── desk ─────────────────────────────────────────────────────────────────────
def test_flag_off_the_desk_is_as_before(capi, gate):
    gate.gate_on = False
    r = capi.post(TRADES_URL, json=trade_body(), headers={**A, "X-Correlation-ID": "corr-off"})
    assert r.status_code == 201, r.text
    (doc,) = gate.db.trades.docs
    assert "correlation_id" not in doc and "risk_decision_id" not in doc
    assert decisions(gate) == []


def test_flag_on_a_cash_paper_trade_is_judged_recorded_and_stamped(capi, gate):
    r = capi.post(TRADES_URL, json=trade_body(), headers={**A, "X-Correlation-ID": "corr-desk-1"})
    assert r.status_code == 201, r.text
    (doc,) = gate.db.trades.docs
    (row,) = decisions(gate)
    assert doc["correlation_id"] == "corr-desk-1" and doc["risk_decision_id"] == row["_id"]
    assert (row["path"], row["mode"], row["outcome"], row["requested_qty"]) == ("desk_paper_trade", "paper",
                                                                                "allowed", 10)
    assert row["detail"]["capital_at_risk_rs"] == 1000.0               # 10 x Rs 100
    assert row["actor_id"] == "user_a" and row["correlation_id"] == "corr-desk-1"


def test_flag_on_an_allowed_spread_is_stamped(capi, gate):
    r = capi.post(TRADES_URL, json=strategy_body(), headers=A)
    assert r.status_code == 201, r.text
    (doc,) = gate.db.trades.docs
    (row,) = decisions(gate)
    assert doc["risk_decision_id"] == row["_id"] and row["outcome"] == "allowed"
    assert row["detail"]["capital_at_risk_rs"] == 6250.0               # debit (40 - 15) x 250


def test_flag_on_a_structure_the_desk_accepts_but_the_gate_refuses_writes_nothing(capi, gate):
    body = strategy_body(family="long_future", legs=[future("buy", 1220)])
    r = capi.post(TRADES_URL, json=body, headers={**A, "X-Correlation-ID": "corr-fut"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert set(detail) == {"code", "reasons", "decision_id", "correlation_id"}
    assert detail["code"] == "risk_blocked" and detail["correlation_id"] == "corr-fut"
    # Every reason is reported: also over the cap, since a long future can lose its full 250 x Rs 1,220 = Rs 3,05,000.
    assert [x["code"] for x in detail["reasons"]] == ["futures_only", "capital_at_risk_exceeded"]
    (row,) = decisions(gate)
    assert row["_id"] == detail["decision_id"] and row["outcome"] == "blocked"
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_flag_on_the_kill_switch_answers_in_the_gates_shape(capi, gate):
    run(rc.set_control(gate.db, "user_a", field="kill_switch", value=True, reason="gap risk", actor="user_a"))
    r = capi.post(TRADES_URL, json=trade_body(), headers=A)
    assert r.status_code == 409
    assert [x["code"] for x in r.json()["detail"]["reasons"]] == ["kill_switch_on"]
    assert [row["source"] for row in decisions(gate)] == ["risk_gate"]   # not the legacy RISK_CONTROL row
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_flag_on_an_unrecorded_decision_is_503_and_nothing_is_written(capi, gate, monkeypatch):
    async def down(doc):
        raise RuntimeError("write concern timeout")
    monkeypatch.setattr(gate.db.cols[rc.DECISIONS], "insert_one", down)
    r = capi.post(TRADES_URL, json=trade_body(), headers=A)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "risk_decision_unrecorded"
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_flag_on_an_unverifiable_lot_is_409(capi, gate):
    gate.refs[EXPIRY] = _listed(None)
    r = capi.post(TRADES_URL, json=strategy_body(), headers=A)
    assert r.status_code == 409
    assert {x["code"] for x in r.json()["detail"]["reasons"]} == {"lot_size_unverified"}
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_flag_on_a_bad_body_is_still_the_desks_422(capi, gate):
    assert capi.post(TRADES_URL, json=trade_body(quantity=-1), headers=A).status_code == 422
    assert decisions(gate) == []


# ── journal ──────────────────────────────────────────────────────────────────
JOURNAL = "/api/positional/journal"


@pytest.fixture
def jh(monkeypatch):
    db = FakeDB()
    state = {"gate_on": False}
    monkeypatch.setattr(journal, "db", db)
    monkeypatch.setattr(rc, "_indexes_ready", False)

    async def current_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    async def enabled_for(_db, user):
        return state["gate_on"]
    monkeypatch.setattr(journal, "get_current_user", current_user)
    monkeypatch.setattr(risk_gate, "enabled_for", enabled_for)
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)
    app.include_router(journal.router)
    client = TestClient(app)
    return db, state, client


def _trade(tid="t1", user="u1", status="OPEN"):
    return {"_id": tid, "user_id": user, "nse_symbol": "FIXA", "capital_alloc_rs": 50000.0, "fills": [],
            "status": status, "opened_at": "2026-10-20T04:00:00+00:00"}


U1 = {"X-Test-User": "u1"}
FILL = {"stage": "PILOT", "qty": 10, "price": 100, "kind": "ENTRY"}


def test_a_fill_on_another_users_trade_is_404_and_writes_nothing(jh):
    db, _, client = jh
    db["trade_journal"].docs.append(_trade(user="u2"))
    assert client.post(f"{JOURNAL}/t1/fill", json=FILL, headers=U1).status_code == 404
    assert db["trade_journal"].docs[0]["fills"] == [] and db["trade_journal"].update_filters == []


@pytest.mark.parametrize("status", ["CLOSED", "STOPPED"])
def test_a_fill_on_a_trade_that_is_not_open_is_409(jh, status):
    db, _, client = jh
    db["trade_journal"].docs.append(_trade(status=status))
    r = client.post(f"{JOURNAL}/t1/fill", json=dict(FILL, kind="EXIT"), headers=U1)
    assert (r.status_code, r.json()["detail"]) == (409, "trade_not_open")
    assert db["trade_journal"].docs[0]["fills"] == [] and db["trade_journal"].update_filters == []


def test_the_fill_write_is_filtered_on_owner_and_status(jh):
    db, _, client = jh
    db["trade_journal"].docs.append(_trade())
    r = client.post(f"{JOURNAL}/t1/fill", json=FILL, headers=U1)
    assert r.status_code == 200, r.text
    assert db["trade_journal"].update_filters == [{"_id": "t1", "user_id": "u1", "status": "OPEN"}]
    assert len(db["trade_journal"].docs[0]["fills"]) == 1
    assert "risk_decision_id" not in r.json()["added_fill"] and db[rc.DECISIONS].docs == []      # flag off


def test_a_trade_closed_between_the_read_and_the_write_takes_no_fill(jh, monkeypatch):
    db, _, client = jh
    db["trade_journal"].docs.append(_trade())
    col = db["trade_journal"]
    real = col.update_one

    async def close_first(query, update, upsert=False):
        col.docs[0]["status"] = "CLOSED"
        return await real(query, update, upsert)
    monkeypatch.setattr(col, "update_one", close_first)
    r = client.post(f"{JOURNAL}/t1/fill", json=FILL, headers=U1)
    assert (r.status_code, r.json()["detail"]) == (409, "trade_not_open") and col.docs[0]["fills"] == []


def test_flag_off_a_journal_entry_is_as_before(jh):
    db, _, client = jh
    r = client.post(JOURNAL, json={"nse_symbol": "fixa", "capital_alloc_rs": 50000}, headers=U1)
    assert r.status_code == 200 and "risk_decision_id" not in r.json() and db[rc.DECISIONS].docs == []


def test_flag_on_a_journal_entry_is_judged_and_stamped(jh):
    db, state, client = jh
    state["gate_on"] = True
    r = client.post(JOURNAL, json={"nse_symbol": "fixa", "capital_alloc_rs": 50000},
                    headers={**U1, "X-Correlation-ID": "corr-j"})
    assert r.status_code == 200, r.text
    (row,) = db[rc.DECISIONS].docs
    assert r.json()["correlation_id"] == "corr-j" and r.json()["risk_decision_id"] == row["_id"]
    assert (row["path"], row["outcome"], row["detail"]["capital_at_risk_rs"]) == ("journal_create", "allowed", 50000.0)
    assert db["trade_journal"].docs[0]["risk_decision_id"] == row["_id"]


def test_flag_on_a_journal_entry_above_the_cap_writes_nothing(jh):
    db, state, client = jh
    state["gate_on"] = True
    r = client.post(JOURNAL, json={"nse_symbol": "FIXA", "capital_alloc_rs": 250000}, headers=U1)
    assert r.status_code == 409
    assert [x["code"] for x in r.json()["detail"]["reasons"]] == ["capital_at_risk_exceeded"]
    assert db["trade_journal"].docs == []


def test_flag_on_an_entry_fill_is_judged_and_an_exit_fill_is_not(jh):
    db, state, client = jh
    state["gate_on"] = True
    db["trade_journal"].docs.append(_trade())
    ok = client.post(f"{JOURNAL}/t1/fill", json=FILL, headers=U1)
    assert ok.status_code == 200, ok.text
    (row,) = db[rc.DECISIONS].docs
    assert ok.json()["added_fill"]["risk_decision_id"] == row["_id"] and row["path"] == "journal_fill"
    assert row["detail"]["action"] == "add" and row["requested_qty"] == 10

    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="stop", actor="u1"))
    blocked = client.post(f"{JOURNAL}/t1/fill", json=FILL, headers=U1)
    assert blocked.status_code == 409 and len(db["trade_journal"].docs[0]["fills"]) == 1
    # Selling out reduces risk: an EXIT fill is not gated, even with the kill switch on.
    out = client.post(f"{JOURNAL}/t1/fill", json=dict(FILL, kind="EXIT", stage="EXIT"), headers=U1)
    assert out.status_code == 200 and len(db["trade_journal"].docs[0]["fills"]) == 2
    assert len(db[rc.DECISIONS].docs) == 2


def test_flag_on_a_fractional_entry_fill_is_blocked(jh):
    db, state, client = jh
    state["gate_on"] = True
    db["trade_journal"].docs.append(_trade())
    r = client.post(f"{JOURNAL}/t1/fill", json=dict(FILL, qty=2.5), headers=U1)
    assert r.status_code == 409 and [x["code"] for x in r.json()["detail"]["reasons"]] == ["quantity_invalid"]
    assert db["trade_journal"].docs[0]["fills"] == []
