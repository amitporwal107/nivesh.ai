"""AD-52 (API part), AD-80..AD-87: the HTTP API with TEST-DOUBLE agents and crafted market data (tests/autodesk/stubs.py).
Signed-in users are faked with a dependency override (header X-Test-User); real sign-in is covered by the staging run."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from autodesk.db import create_pool_for
from autodesk.main import build_state, create_app
from autodesk.routers.api import current_user
from tests.autodesk import stubs

USERS = {"a": {"user_id": "api-a", "role": "user"}, "b": {"user_id": "api-b", "role": "user"},
         "admin": {"user_id": "api-admin", "role": "admin"}}
A, B, ADMIN = ({"X-Test-User": k} for k in ("a", "b", "admin"))


@pytest.fixture(scope="module")
def client(pg_pool, pg_dsn):
    pools = []

    async def factory():
        pool = await create_pool_for(pg_dsn)
        pools.append(pool)

        async def next_session(now):
            return date(2026, 11, 5)

        st = build_state(pool, agents=stubs.agents(), market_factory=stubs.market_factory,
                         sessions_provider=stubs.sessions_provider, next_session=next_session,
                         load_book=stubs.stub_load_book, scope_builder=stubs.stub_scope)
        st.orchestrator.task_deadline_s = 1.0
        await st.orchestrator.register_agents()
        return st

    app = create_app(factory)

    async def fake_user(request: Request):
        who = request.headers.get("X-Test-User")
        if who not in USERS:
            raise HTTPException(401, "Not authenticated")
        return USERS[who]

    app.dependency_overrides[current_user] = fake_user
    with TestClient(app) as c:
        yield c
        for p in pools:
            c.portal.call(p.close)


def _account(client, headers=A, mode="AUTONOMOUS_PAPER"):
    r = client.post("/api/v1/accounts", json={"name": "desk", "operating_mode": mode}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["db"] is True and "001_autodesk_core.sql" in r.json()["migrations"]


def test_ad80_unauthenticated(client):
    for method, path in (("GET", "/api/v1/desk/status"), ("GET", "/api/v1/accounts"), ("POST", "/api/v1/accounts"),
                         ("GET", "/api/v1/agents"), ("GET", "/api/v1/signals"), ("GET", "/api/v1/trade-plans"),
                         ("GET", "/api/v1/approvals"), ("POST", "/api/v1/desk/workflows"),
                         ("POST", "/api/v1/simulations"), ("GET", "/api/v1/simulations"), ("GET", "/api/v1/events"),
                         ("GET", "/api/v1/policies")):
        r = client.request(method, path, json={})
        assert r.status_code == 401, (method, path, r.status_code)


def test_ad81_ad82_accounts_isolation_and_mode(client):
    acc = _account(client)
    assert acc["kind"] == "PAPER" and acc["operating_mode"] == "AUTONOMOUS_PAPER"
    assert [a["account_id"] for a in client.get("/api/v1/accounts", headers=A).json()].count(acc["account_id"]) == 1
    assert client.get(f"/api/v1/accounts/{acc['account_id']}", headers=B).status_code == 404
    assert client.get("/api/v1/accounts", headers=B).json() == []
    r = client.post(f"/api/v1/accounts/{acc['account_id']}/mode", json={"mode": "ASSISTED", "reason": "test"},
                    headers=A)
    assert r.status_code == 200 and r.json()["operating_mode"] == "ASSISTED"
    evs = client.get("/api/v1/events", headers=A).json()
    assert any(e["event_type"] == "ACCOUNT_MODE_CHANGED" and e["account_id"] == acc["account_id"] for e in evs)
    assert client.post(f"/api/v1/accounts/{acc['account_id']}/mode", json={"mode": "ASSISTED", "reason": "x"},
                       headers=B).status_code == 404


def test_ad83_ad84_desk_session_cycle(client):
    acc = _account(client)
    r = client.post("/api/v1/desk/workflows", json={"kind": "SESSION_CYCLE", "account_id": acc["account_id"],
                                                    "max_proposals": 1, "wait": True}, headers=A)
    assert r.status_code == 202, r.text
    cyc = r.json()
    assert cyc["state"] == "COMPLETED", cyc
    d = client.get(f"/api/v1/desk/workflows/{cyc['workflow_id']}", headers=A).json()
    kinds = sorted(ch["kind"] for ch in d["children"])
    assert kinds == ["MARKET_SCAN", "PREMARKET_CHECK", "TRADE_PROPOSAL"]
    prop = [ch for ch in d["children"] if ch["kind"] == "TRADE_PROPOSAL"][0]
    pd = client.get(f"/api/v1/desk/workflows/{prop['workflow_id']}", headers=A).json()
    assert [t["to_agent"] for t in pd["tasks"]] == ["TRADING_ASSISTANT", "RISK_OPS", "MIDDLE_OFFICE"]
    assert len(pd["handoffs"]) == 3
    assert client.get(f"/api/v1/desk/workflows/{cyc['workflow_id']}", headers=B).status_code == 404
    sigs = client.get("/api/v1/signals", headers=A).json()
    assert len(sigs) >= 2 and all(s["simulation_id"] is None for s in sigs)
    agents = client.get("/api/v1/agents", headers=A).json()
    assert {a["agent_key"] for a in agents} == {"AI_TRADER", "TRADING_ASSISTANT", "RISK_OPS", "MIDDLE_OFFICE",
                                                "TECH_SUPPORT"}
    act = client.get("/api/v1/agents/AI_TRADER/activity", headers=A).json()
    assert act and act[0]["task_type"] == "SCAN_MARKET" and act[0]["state"] == "COMPLETED"
    plans = client.get("/api/v1/trade-plans", headers=A).json()
    tid = plans[0]["trade_id"]
    p = client.get(f"/api/v1/trade-plans/{tid}", headers=A).json()
    assert p["latest_risk_assessment"]["verdict"] == "PASS" and p["approvals"]
    r = client.post(f"/api/v1/trade-plans/{tid}/validate", headers=A)
    assert r.status_code == 201 and r.json()["trade_id"] == tid
    assert client.post(f"/api/v1/trade-plans/{tid}/validate", headers=B).status_code == 404


def test_ad85_ad86_simulation_and_human_decision(client):
    body = {"name": "api sim", "start_date": "2026-11-04", "end_date": "2026-11-05", "operating_mode": "ASSISTED",
            "max_proposals_per_session": 1}
    r = client.post("/api/v1/simulations", json=body, headers=A)
    assert r.status_code == 201, r.text
    sid = r.json()["simulation_id"]
    assert client.post("/api/v1/simulations", json={**body, "mode": "LIVE_SHADOW"}, headers=A).status_code == 422
    assert client.post(f"/api/v1/simulations/{sid}/step", json={}, headers=A).status_code == 409    # not started
    assert client.post(f"/api/v1/simulations/{sid}/start", headers=A).json()["status"] == "RUNNING"
    for _ in range(3):
        r = client.post(f"/api/v1/simulations/{sid}/step", json={"unit": "PHASE"}, headers=A)
        assert r.status_code == 200, r.text
    assert r.json()["clock_phase"] == "PROPOSALS"
    pend = client.get(f"/api/v1/approvals?pending=true&simulation_id={sid}", headers=A).json()
    assert len(pend) == 1
    aid = pend[0]["approval_id"]
    assert client.post(f"/api/v1/approvals/{aid}/decision", json={"decision": "APPROVE"}, headers=B).status_code == 404
    r = client.post(f"/api/v1/approvals/{aid}/decision", json={"decision": "APPROVE", "reason": "ok"}, headers=A)
    assert r.status_code == 201 and r.json()["status"] == "APPROVED", r.text
    assert client.post(f"/api/v1/approvals/{aid}/decision", json={"decision": "REJECT"}, headers=A).status_code == 409
    tl = client.get(f"/api/v1/simulations/{sid}/timeline", headers=A).json()
    assert [c["phase"] for c in tl["clock"]] == ["PREMARKET", "SCAN", "PROPOSALS"]
    assert any(e["event_type"] == "APPROVAL_GRANTED" for e in tl["events"])
    assert client.post(f"/api/v1/simulations/{sid}/pause", headers=A).status_code == 200
    assert client.post(f"/api/v1/simulations/{sid}/step", json={}, headers=A).status_code == 409
    assert client.post(f"/api/v1/simulations/{sid}/resume", headers=A).status_code == 200
    r = client.post(f"/api/v1/simulations/{sid}/step", json={"unit": "SESSION"}, headers=A)
    assert [s["phase"] for s in r.json()["steps"]] == ["OPEN", "CLOSE", "EOD"]
    r = client.post(f"/api/v1/simulations/{sid}/step", json={"unit": "SESSION"}, headers=A)
    assert r.json()["status"] == "COMPLETED"
    res = client.get(f"/api/v1/simulations/{sid}/results", headers=A).json()
    assert res["sessions_total"] == 2 and res["phases_run"] == 12 and res["limitations"]
    assert res["approvals"]["by_decider"].get("user") == 1
    ag = client.get(f"/api/v1/simulations/{sid}/agents", headers=A).json()
    assert set(ag["agents"]) == {"AI_TRADER", "TRADING_ASSISTANT", "RISK_OPS", "MIDDLE_OFFICE", "TECH_SUPPORT"}
    assert client.get(f"/api/v1/simulations/{sid}", headers=B).status_code == 404
    assert client.get(f"/api/v1/simulations/{sid}/results", headers=B).status_code == 404


def test_ad87_desk_status(client):
    _account(client)
    s = client.get("/api/v1/desk/status", headers=A).json()
    assert s["accounts"] and len(s["agents"]) == 5 and "pending_approvals" in s
    assert s["market_data"].get("latest_cash_session") and "Phase 1" in s["execution"]


def test_ad52_policy_changes(client):
    pols = client.get("/api/v1/policies", headers=A).json()
    pid = pols[0]["policy_id"]
    r = client.post(f"/api/v1/policies/{pid}/versions",
                    json={"changes": {"per_trade_risk_pct": "0.3"}, "reason": "tighter"}, headers=A)
    assert r.status_code == 201 and r.json()["version"] == 2
    r = client.post(f"/api/v1/policies/{pid}/versions",
                    json={"changes": {"per_trade_risk_pct": "1.0"}, "reason": "looser"}, headers=A)
    assert r.status_code == 403
    assert client.post(f"/api/v1/policies/{pid}/versions", json={"changes": {"per_trade_risk_pct": "0.2"},
                                                                 "reason": "x"}, headers=B).status_code == 404
    r = client.post(f"/api/v1/policies/{pid}/versions",
                    json={"changes": {"max_legs": 9}, "reason": "bad"}, headers=A)
    assert r.status_code == 422
