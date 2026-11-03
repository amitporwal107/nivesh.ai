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
    # MOCK: the underlying's bars (the risk service reads FIXU's last close on the server) and an F&O history read that
    # answers with no rows yet (an open structure with no session since it was recorded is valued at its entry).
    import copy
    from tests.test_desk_strategy_trades import UNDERLYING
    world.rows["FIXU"] = copy.deepcopy(UNDERLYING[:1])          # only the sessions up to the test's clock (12 Oct)
    from services.copilot_tools import daas_client
    prices_get = daas_client._get

    async def fake_get(path, params=None, timeout=10.0, *, creds=None):
        if path.startswith("/fno/"):
            return {"data": [], "count": 0, "pagination": {"next_offset": None}}
        return await prices_get(path, params, timeout, creds=creds)
    monkeypatch.setattr(daas_client, "_get", fake_get)
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
def test_flag_off_the_desk_still_runs_the_core_risk_service(capi, gate):
    """Phase 1 (criteria 1.1): the flag no longer decides WHETHER an entry is judged. With it off the universal risk
    service still judges, records and reserves; the flag only adds the F&O structure checks (skipped here)."""
    gate.gate_on = False
    r = capi.post(TRADES_URL, json=trade_body(), headers={**A, "X-Correlation-ID": "corr-off"})
    assert r.status_code == 201, r.text
    (doc,) = gate.db.trades.docs
    (row,) = decisions(gate)
    assert doc["correlation_id"] == "corr-off" and doc["risk_decision_id"] == row["_id"]
    assert doc["risk_reservation_id"] == row["_id"] and row["source"] == "risk_service"
    assert row["outcome"] == "allowed" and row["detail"]["fno_additional"] is False


def test_flag_on_a_cash_paper_trade_is_judged_recorded_and_stamped(capi, gate):
    r = capi.post(TRADES_URL, json=trade_body(), headers={**A, "X-Correlation-ID": "corr-desk-1"})
    assert r.status_code == 201, r.text
    (doc,) = gate.db.trades.docs
    (row,) = decisions(gate)
    assert doc["correlation_id"] == "corr-desk-1" and doc["risk_decision_id"] == row["_id"]
    assert (row["path"], row["mode"], row["outcome"], row["requested_qty"]) == ("desk_paper_trade", "paper",
                                                                                "allowed", 10)
    assert row["budget"]["funding_rs"] == 1000.0 and row["source"] == "risk_service"     # 10 x Rs 100
    assert row["actor_id"] == "user_a" and row["correlation_id"] == "corr-desk-1"


def test_flag_on_an_allowed_spread_is_stamped(capi, gate):
    r = capi.post(TRADES_URL, json=strategy_body(), headers=A)
    assert r.status_code == 201, r.text
    (doc,) = gate.db.trades.docs
    (row,) = decisions(gate)
    assert doc["risk_decision_id"] == row["_id"] and row["outcome"] == "allowed"
    assert row["estimated_risk_rs"]["gross"] == 6250.0                 # maximum loss: debit (40 - 15) x 250


def test_flag_on_a_structure_the_desk_accepts_but_the_gate_refuses_writes_nothing(capi, gate):
    body = strategy_body(family="long_future", legs=[future("buy", 1220)])
    r = capi.post(TRADES_URL, json=body, headers={**A, "X-Correlation-ID": "corr-fut"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert {"code", "reasons", "decision_id", "correlation_id", "estimated_risk_rs", "budget"} <= set(detail)
    assert detail["code"] == "risk_blocked" and detail["correlation_id"] == "corr-fut"
    # The flag's ADDITIONAL checks (fno_additional): futures-only refused, and over the gate's fixed cap, since a long
    # future can lose its full 250 x Rs 1,220 = Rs 3,05,000. The core checks passed it.
    assert [(x["code"], x["check"]) for x in detail["reasons"]] == [("futures_only", "fno_additional"),
                                                                     ("capital_at_risk_exceeded", "fno_additional")]
    (row,) = decisions(gate)
    assert row["_id"] == detail["decision_id"] and row["outcome"] == "blocked"
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_flag_on_the_kill_switch_answers_in_the_gates_shape(capi, gate):
    run(rc.set_control(gate.db, "user_a", field="kill_switch", value=True, reason="gap risk", actor="user_a"))
    r = capi.post(TRADES_URL, json=trade_body(), headers=A)
    assert r.status_code == 409
    assert [x["code"] for x in r.json()["detail"]["reasons"]] == ["kill_switch_on"]
    assert [row["source"] for row in decisions(gate)] == ["risk_service"]   # not the legacy RISK_CONTROL row
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
    # The desk's own exchange-lot check now runs whatever the flag says (422, its own code), before the service; the
    # service checks the lot again on every path (core check lot_size).
    assert r.status_code == 422 and r.json()["detail"]["code"] == "lot_size_unverified"
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_flag_on_a_bad_body_is_still_the_desks_422(capi, gate):
    assert capi.post(TRADES_URL, json=trade_body(quantity=-1), headers={**A, "X-Correlation-ID": "corr-bad"}).status_code == 422
    # The gate never judged it (no gate row). The desk's own refusal is now recorded (TESTCASES A-1): before, a
    # validator 422 left no trace in risk_decisions.
    (row,) = decisions(gate)
    assert row["source"] == "desk_validation" and row["path"] == "desk_paper_trade" and row["outcome"] == "blocked"
    assert row["policy_version"] == "universal-risk-v2"
    assert row["reasons"][0]["code"] == "invalid_quantity" and row["correlation_id"] == "corr-bad"


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
    # MOCK: FIXA's bars (the risk service reads the last close and the traded value on the server) and the loosest
    # allowed risk profile for u1 (tests/risk_helpers.py): this suite tests the wiring, not the limits.
    from datetime import timedelta
    from services import data_freshness as fresh
    from services.risk_gate import inputs as risk_inputs
    from tests.risk_helpers import loose_profile_doc, mock_bars
    db["risk_profiles"].docs.append(loose_profile_doc("u1"))
    state["price"] = 100.0

    async def instrument(symbol, today):
        last = fresh.previous_session(today)
        days = sorted({last - timedelta(days=k) for k in range(0, 28) if (last - timedelta(days=k)).weekday() < 5})
        bars = mock_bars(state["price"], days=days)
        return {"bars": bars, "last_close": state["price"], "last_close_as_of": last.isoformat(),
                "adv_rs": state["price"] * 1_000_000, "adv_sessions": 20, "source": "MOCK bars", "error": None}
    monkeypatch.setattr(risk_inputs, "instrument", instrument)
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)
    app.include_router(journal.router)
    client = TestClient(app)
    return db, state, client


def _trade(tid="t1", user="u1", status="OPEN"):
    """MOCK: a journal trade recorded before Phase 1 (no risk plan), with the stop and target the policy needs."""
    return {"_id": tid, "user_id": user, "nse_symbol": "FIXA", "capital_alloc_rs": 50000.0, "fills": [],
            "stop_loss": 95.0, "target": 115.0, "status": status, "opened_at": "2026-10-20T04:00:00+00:00"}


PLAN = {"nse_symbol": "fixa", "capital_alloc_rs": 50000, "stop_loss": 95, "target": 115}


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
    (allowed,) = db[rc.DECISIONS].docs                                  # judged with the flag off too (Phase 1)
    assert r.json()["added_fill"]["risk_decision_id"] == allowed["_id"] and allowed["outcome"] == "allowed"
    # FLIPPED (TESTCASES K-5, K-13). This test used to stop here, which locked in the bypass: with the flag off an
    # ENTRY fill never consulted the kill switch (study A, R24: a Rs 1 crore fill answered 200 with the switch on).
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="stop", actor="u1"))
    blocked = client.post(f"{JOURNAL}/t1/fill", json=dict(FILL, qty=100000, price=100),
                          headers={**U1, "X-Correlation-ID": "corr-fill"})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "risk_blocked"
    assert len(db["trade_journal"].docs[0]["fills"]) == 1 and len(db["trade_journal"].update_filters) == 1
    row = db[rc.DECISIONS].docs[-1]
    assert (row["path"], row["symbol"], row["requested_qty"], row["correlation_id"], row["outcome"]) == (
        "journal_fill", "FIXA", 100000, "corr-fill", "blocked")
    assert "kill_switch_on" in [x["code"] for x in row["reasons"]]


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
    (account,) = db["paper_accounts"].docs                        # the fill's reservation went back, exactly once
    assert account["reservations"] == [] and account["blocked_rs"] == 0 and account["open_risk_rs"] == 0


def test_flag_off_a_journal_entry_is_judged_too(jh):
    db, _, client = jh
    r = client.post(JOURNAL, json=PLAN, headers=U1)
    assert r.status_code == 200, r.text
    (allowed,) = db[rc.DECISIONS].docs
    assert r.json()["risk_decision_id"] == allowed["_id"] and allowed["source"] == "risk_service"
    # FLIPPED (TESTCASES K-4, K-13): "as before" must still mean the kill switch is consulted with the flag off, and
    # its refusal is now recorded with the path, the symbol and the correlation id (it had neither).
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="stop", actor="u1"))
    blocked = client.post(JOURNAL, json=PLAN, headers={**U1, "X-Correlation-ID": "corr-create"})
    assert blocked.status_code == 409 and len(db["trade_journal"].docs) == 1
    row = db[rc.DECISIONS].docs[-1]
    assert (row["path"], row["symbol"], row["correlation_id"]) == ("journal_create", "FIXA", "corr-create")


def test_flag_on_a_journal_entry_is_judged_and_stamped(jh):
    db, state, client = jh
    state["gate_on"] = True
    r = client.post(JOURNAL, json=PLAN, headers={**U1, "X-Correlation-ID": "corr-j"})
    assert r.status_code == 200, r.text
    (row,) = db[rc.DECISIONS].docs
    assert r.json()["correlation_id"] == "corr-j" and r.json()["risk_decision_id"] == row["_id"]
    # The plan: Rs 50,000 at the last close Rs 100 is 500 shares, reserved in full.
    assert (row["path"], row["outcome"], row["requested_qty"], row["budget"]["funding_rs"]) == (
        "journal_create", "allowed", 500, 50000.0)
    assert db["trade_journal"].docs[0]["risk_plan"]["planned_qty"] == 500
    assert db["trade_journal"].docs[0]["risk_decision_id"] == row["_id"]


def test_a_journal_plan_above_the_budget_is_reduced_and_writes_nothing(jh):
    """Under the owner's default profile (the loose MOCK profile removed): Rs 2,50,000 at Rs 100 is 2,500 shares, over
    the 10% position limit and the 0.5% per-trade risk budget. 409 risk_reduce with the capital that fits."""
    db, state, client = jh
    db["risk_profiles"].docs.clear()
    r = client.post(JOURNAL, json=dict(PLAN, capital_alloc_rs=250000), headers=U1)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "risk_reduce", r.text
    detail = r.json()["detail"]
    assert detail["requested_qty"] == 2500 and 0 < detail["approved_qty"] < 2500
    assert detail["approved_notional_rs"] == detail["approved_qty"] * 100.0
    assert db["trade_journal"].docs == [] and (db["paper_accounts"].docs == [] or db["paper_accounts"].docs[0]["blocked_rs"] == 0)


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
    assert r.status_code == 409 and "quantity_invalid" in [x["code"] for x in r.json()["detail"]["reasons"]]
    assert db["trade_journal"].docs[0]["fills"] == []
