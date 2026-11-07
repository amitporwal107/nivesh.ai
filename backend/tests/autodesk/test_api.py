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


def test_adfx14_blocked_cycle_then_again_over_the_api(client):
    """AD-FX-14: POST /desk/workflows after a BLOCKED pre-market opens a new workflow; both are listed (newest first)."""
    from autodesk import contracts as C
    ts = client.app.state.desk.orchestrator.agents[C.AgentKey.TECH_SUPPORT]
    acc = _account(client)
    body = {"kind": "SESSION_CYCLE", "account_id": acc["account_id"], "max_proposals": 1, "wait": True}
    ts.status = C.HealthStatus.BLOCKED
    try:
        r1 = client.post("/api/v1/desk/workflows", json=body, headers=A)
        assert r1.status_code == 202 and r1.json()["state"] == "BLOCKED", r1.text
        assert r1.json()["outcome"]["result"] == "BLOCKED_NO_NEW_RISK"
        r2 = client.post("/api/v1/desk/workflows", json=body, headers=A)
        assert r2.status_code == 202 and r2.json()["state"] == "BLOCKED", r2.text
        assert r2.json()["workflow_id"] != r1.json()["workflow_id"]
        assert r2.json()["idempotency_key"].endswith(":cycle:attempt-2")
        ts.status = C.HealthStatus.READY
        r3 = client.post("/api/v1/desk/workflows", json=body, headers=A)
        assert r3.json()["state"] == "COMPLETED" and r3.json()["idempotency_key"].endswith(":attempt-3"), r3.text
        r4 = client.post("/api/v1/desk/workflows", json=body, headers=A)       # a finished cycle stays final
        assert r4.json()["workflow_id"] == r3.json()["workflow_id"]
    finally:
        ts.status = C.HealthStatus.READY
    wfs = client.get(f"/api/v1/desk/workflows?account_id={acc['account_id']}&kind=SESSION_CYCLE", headers=A).json()
    assert [w["workflow_id"] for w in wfs] == [r3.json()["workflow_id"], r2.json()["workflow_id"],
                                               r1.json()["workflow_id"]]          # newest first (AD-FX-43)
    two = client.get(f"/api/v1/desk/workflows?account_id={acc['account_id']}&kind=SESSION_CYCLE&limit=2", headers=A).json()
    assert [w["workflow_id"] for w in two] == [r3.json()["workflow_id"], r2.json()["workflow_id"]]   # the newest two
    kids = client.get(f"/api/v1/desk/workflows/{r3.json()['workflow_id']}", headers=A).json()["children"]
    assert [k["kind"] for k in kids] == ["PREMARKET_CHECK", "MARKET_SCAN", "TRADE_PROPOSAL"]         # children: creation order


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
    assert len(p["plan_hash"]) == 64 and p["approvals"][0]["body"]["scope"]["plan_hash"] == p["plan_hash"]  # AD-98
    r = client.post(f"/api/v1/trade-plans/{tid}/validate", headers=A)
    assert r.status_code == 201 and r.json()["trade_id"] == tid
    assert client.post(f"/api/v1/trade-plans/{tid}/validate", headers=B).status_code == 404


def test_adfx35_41_42_newest_rows_and_the_plan_approval_lookup(client):
    """AD-FX-41/42: /events and the timeline return the NEWEST rows without a cursor and walk forward with one;
    AD-FX-35: the approvals of one simulated plan, newest first (what the studio's "Open full plan" links to)."""
    body = {"name": "fx sim", "start_date": "2026-11-04", "end_date": "2026-11-05", "operating_mode": "ASSISTED",
            "max_proposals_per_session": 1}
    sid = client.post("/api/v1/simulations", json=body, headers=A).json()["simulation_id"]
    client.post(f"/api/v1/simulations/{sid}/start", headers=A)
    for _ in range(3):
        assert client.post(f"/api/v1/simulations/{sid}/step", json={"unit": "PHASE"}, headers=A).status_code == 200
    seqs = lambda rows: [e["seq"] for e in rows]   # noqa: E731
    full = client.get(f"/api/v1/simulations/{sid}/timeline?limit=5000", headers=A).json()
    ev = full["events"]
    assert len(ev) > 12 and seqs(ev) == sorted(seqs(ev))
    for url in (f"/api/v1/simulations/{sid}/timeline", f"/api/v1/events?simulation_id={sid}"):
        pick = (lambda r: r.json()["events"]) if "timeline" in url else (lambda r: r.json())
        newest = pick(client.get(f"{url}{'&' if '?' in url else '?'}limit=5", headers=A))
        assert seqs(newest) == seqs(ev)[-5:]                                        # no cursor: the newest, ascending
        first = pick(client.get(f"{url}{'&' if '?' in url else '?'}after_seq=0&limit=5", headers=A))
        assert seqs(first) == seqs(ev)[:5]                                          # cursor 0: from the first event
        nxt = pick(client.get(f"{url}{'&' if '?' in url else '?'}after_seq={seqs(ev)[4]}&limit=5", headers=A))
        assert seqs(nxt) == seqs(ev)[5:10]
    assert full["clock"] == client.get(f"/api/v1/simulations/{sid}/timeline?limit=2", headers=A).json()["clock"]
    assert [c["phase"] for c in full["clock"]] == ["PREMARKET", "SCAN", "PROPOSALS"]    # clock rows are never limited
    # AD-FX-35
    [pend] = client.get(f"/api/v1/approvals?pending=true&simulation_id={sid}", headers=A).json()
    tid = pend["trade_id"]
    r = client.post(f"/api/v1/approvals/{pend['approval_id']}/decision", json={"decision": "APPROVE", "reason": "ok"},
                    headers=A)
    assert r.status_code == 201
    rows = client.get(f"/api/v1/approvals?simulation_id={sid}&trade_id={tid}", headers=A).json()
    assert [x["status"] for x in rows] == ["APPROVED", "NEEDS_HUMAN_APPROVAL"]            # newest first
    assert rows[0]["approval_id"] == r.json()["approval_id"] and rows[0]["supersedes_id"] == pend["approval_id"]
    assert client.get(f"/api/v1/approvals?simulation_id={sid}&trade_id={tid}", headers=B).json() == []


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


def test_ad93_ad94_ad97_stop_new_entries_api(client):
    assert client.get("/api/v1/desk/controls").status_code == 401
    [c0] = client.get("/api/v1/desk/controls", headers=B).json()
    assert c0["control"] == "STOP_NEW_ENTRIES" and c0["active"] is False
    assert client.post("/api/v1/desk/controls/STOP_EVERYTHING", json={"active": True, "reason": "x"},
                       headers=B).status_code == 422
    r1 = client.post("/api/v1/desk/controls/STOP_NEW_ENTRIES", json={"active": True, "reason": "drill"}, headers=B)
    r2 = client.post("/api/v1/desk/controls/STOP_NEW_ENTRIES", json={"active": True, "reason": "again"}, headers=B)
    assert r1.status_code == 200 and r1.json()["changed"] is True and r2.json()["changed"] is False
    st = client.get("/api/v1/desk/status", headers=B).json()
    assert st["controls"][0]["active"] is True
    assert client.get("/api/v1/desk/status", headers=A).json()["controls"][0]["active"] is False   # per tenant
    try:
        acc = _account(client, headers=B)
        cyc = client.post("/api/v1/desk/workflows", json={"kind": "SESSION_CYCLE", "account_id": acc["account_id"],
                                                          "max_proposals": 1, "wait": True}, headers=B).json()
        assert cyc["state"] == "COMPLETED" and cyc["outcome"]["proposals"]["proposed"] == 0, cyc
        sig = client.get("/api/v1/signals", headers=B).json()[0]
        r = client.post("/api/v1/desk/workflows", json={"kind": "TRADE_PROPOSAL", "signal_id": sig["signal_id"],
                                                        "wait": True}, headers=B)
        assert r.status_code == 409 and "stopped" in r.text
        bad = client.post("/api/v1/approvals/APR-x/decision", json={"decision": "APPROVE", "plan_hash": "zz"},
                          headers=B)
        assert bad.status_code == 422
    finally:
        r3 = client.post("/api/v1/desk/controls/STOP_NEW_ENTRIES", json={"active": False, "reason": "done"},
                         headers=B)
        assert r3.json()["changed"] is True and r3.json()["active"] is False


def test_adsc13_scoring_versions(client):
    """AD-SC-13: which scoring version selects, which shadow (scoring/registry.py)."""
    assert client.get("/api/v1/scoring/versions").status_code == 401
    r = client.get("/api/v1/scoring/versions", headers=A)
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == "v1"
    by = {v["version"]: v for v in body["versions"]}
    assert by["v1"]["selects_signals"] and not by["v2-positional"]["selects_signals"]
    assert by["v3-intraday"]["status"] == "DISABLED"
    assert set(by["v2-positional"]["weights"]) == {"signal_quality", "trend_confirmation", "relative_strength",
                                                   "supporting_evidence"}

