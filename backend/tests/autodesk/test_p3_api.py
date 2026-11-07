"""AD-P3-75, 76, 77, 88: Phase 3A read APIs and writes through the FastAPI app with the lifecycle wired, over a simulation run by
test-double agents on frozen session rows (TEST DATA, not real market data). Signed-in users are faked with a dependency
override, as in test_p2_api."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from autodesk.db import create_pool_for
from autodesk.execution import adapters as ad
from autodesk.execution.fill_model import DEFAULT_PARAMS
from autodesk.execution.gateway import ExecutionGateway
from autodesk.lifecycle.manager import LifecycleManager
from autodesk.main import build_state, create_app
from autodesk.routers.api import current_user
from tests.autodesk import p2_harness as H
from tests.autodesk import stubs
from tests.autodesk.test_p2_simulation import session_rows

USERS = {"a": {"user_id": "p3-a", "role": "user"}, "b": {"user_id": "p3-b", "role": "user"}}
A, B = ({"X-Test-User": k} for k in ("a", "b"))
BASE = "/api/v1"


@pytest.fixture(scope="module")
def client(pg_pool, pg_dsn):
    pools = []

    async def factory():
        pool = await create_pool_for(pg_dsn)
        pools.append(pool)

        async def next_session(now):
            return date(2026, 11, 5)

        gw = ExecutionGateway(pool, sim=ad.SimulationPaperAdapter(H.FrozenSessionBars(session_rows(shift=-25)), DEFAULT_PARAMS),
                              lifecycle=LifecycleManager(pool))
        st = build_state(pool, agents=stubs.agents(), market_factory=stubs.market_factory,
                         sessions_provider=stubs.sessions_provider, next_session=next_session,
                         load_book=stubs.stub_load_book, scope_builder=stubs.stub_scope, execution=gw)
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


@pytest.fixture(scope="module")
def sim(client):
    r = client.post(f"{BASE}/simulations", headers=A, json={"name": "p3 api", "start_date": "2026-11-04", "end_date": "2026-11-05",
                                                           "max_proposals_per_session": 1})
    assert r.status_code == 201, r.text
    sid = r.json()["simulation_id"]
    assert client.post(f"{BASE}/simulations/{sid}/start", headers=A).status_code == 200
    for _ in range(2):
        r = client.post(f"{BASE}/simulations/{sid}/step", json={"unit": "SESSION"}, headers=A)
        assert r.status_code == 200, r.text
    assert r.json()["status"] == "COMPLETED"
    acc = [a for a in client.get(f"{BASE}/accounts?include_simulation=true", headers=A).json() if a["simulation_id"] == sid][0]
    return {"sid": sid, "account_id": acc["account_id"]}


ROUTES = ["/positions/POS-x/lifecycle", "/trades/closed", "/execution/exit-records", "/lifecycle/events",
          "/accounts/ACC-x/limits", "/accounts/ACC-x/reconciliation", "/lifecycle/controls"]


def test_adp3_75_signed_out_401_and_other_tenant_404(client, sim):
    for path in ROUTES:
        assert client.get(BASE + path).status_code == 401, path
    for path, body in (("/lifecycle/controls/REDUCE_ONLY", {"active": True, "reason": "x"}),
                       ("/execution/cancel-pending-entries", {"reason": "x"}), ("/execution/orders/ORD-x/amend", {"lots": 1}),
                       ("/positions/POS-x/close", {"reason": "x"})):
        assert client.post(BASE + path, json=body).status_code == 401, path
    sid, aid = sim["sid"], sim["account_id"]
    assert client.get(f"{BASE}/accounts/{aid}/limits", headers=B).status_code == 404
    assert client.get(f"{BASE}/accounts/{aid}/reconciliation", headers=B).status_code == 404
    for path in ("trades/closed", "execution/exit-records", "lifecycle/events"):
        assert client.get(f"{BASE}/{path}?simulation_id={sid}", headers=B).json() == [], path
    pid = client.get(f"{BASE}/positions?simulation_id={sid}", headers=A).json()[0]["position_id"]
    assert client.get(f"{BASE}/positions/{pid}/lifecycle", headers=B).status_code == 404
    assert client.post(f"{BASE}/positions/{pid}/close", headers=B, json={"reason": "x"}).status_code == 404


def test_adp3_76_77_shapes_after_a_simulation_with_closings(client, sim):
    sid, aid = sim["sid"], sim["account_id"]
    closed = client.get(f"{BASE}/trades/closed?simulation_id={sid}", headers=A).json()
    recs = client.get(f"{BASE}/execution/exit-records?simulation_id={sid}", headers=A).json()
    assert closed and recs, (closed, recs)                    # rows open 25 below the plan price and trade 8 lower: the level (30 below) closes them
    t = closed[0]
    assert {"gross_realized_rs", "net_realized_rs", "opening_charges_rs", "closing_charges_rs", "close_reason", "legs",
            "reconciled", "sessions_held"} <= set(t) and t["broker_confirmed"] is False and isinstance(t["net_realized_rs"], str)
    pid = t["position_id"]
    lc = client.get(f"{BASE}/positions/{pid}/lifecycle", headers=A).json()
    assert lc["lifecycle_state"] == "SETTLED" and lc["exit_state"]["trigger_key"] and lc["history"][0]["to_state"] == "ACTIVE_POSITION"
    assert lc["closing_orders"] and lc["exit_records"]
    ev = client.get(f"{BASE}/lifecycle/events?simulation_id={sid}", headers=A).json()
    assert [e["to_state"] for e in ev if e["trade_id"] == t["trade_id"]][-1] == "SETTLED"
    lim = client.get(f"{BASE}/accounts/{aid}/limits", headers=A).json()
    assert set(lim["measures"]) == {"daily", "weekly", "drawdown"} and "blocks" in lim
    rc = client.get(f"{BASE}/accounts/{aid}/reconciliation", headers=A).json()
    assert rc["now"]["ok"] and rc["runs"] >= 2 and rc["runs_failed"] == 0
    assert all(k["difference_rs"] == "0.00" for k in rc["now"]["checks"])
    pnl = client.get(f"{BASE}/accounts/{aid}/pnl", headers=A).json()
    assert pnl["closed_trades"] >= 1 and pnl["by_reason"]
    res = client.get(f"{BASE}/simulations/{sid}/results", headers=A).json()
    es = res["execution_summary"]
    assert es["closed_trades"] >= 1 and es["reconciliation_runs"]["failed"] == 0 and es["exits_by_reason"]
    assert any("managed from their fills to closure" in x for x in res["limitations"])           # AD-P3-88


def test_adp3_57_60_controls_routes(client, sim):
    r = client.post(f"{BASE}/lifecycle/controls/SUSPEND_STRATEGY", headers=A, json={"active": True, "reason": "test", "scope": "LONG_EQUITY"})
    assert r.status_code == 200 and r.json()["changed"] is True
    again = client.post(f"{BASE}/lifecycle/controls/SUSPEND_STRATEGY", headers=A, json={"active": True, "reason": "test", "scope": "LONG_EQUITY"})
    assert again.json()["changed"] is False
    assert client.post(f"{BASE}/lifecycle/controls/SUSPEND_STRATEGY", headers=A, json={"active": True, "reason": "x", "scope": "NOPE"}).status_code == 422
    assert client.post(f"{BASE}/lifecycle/controls/SUSPEND_ACCOUNT", headers=A, json={"active": True, "reason": "x"}).status_code == 422
    rows = client.get(f"{BASE}/lifecycle/controls", headers=A).json()
    assert any(x["control"] == "SUSPEND_STRATEGY" and x["scope"] == "LONG_EQUITY" and x["active"] for x in rows)
    assert client.get(f"{BASE}/lifecycle/controls", headers=B).json() == []
    pid = client.get(f"{BASE}/positions?simulation_id={sim['sid']}", headers=A).json()[0]["position_id"]
    assert client.post(f"{BASE}/positions/{pid}/close", headers=A, json={"reason": "x"}).status_code == 409   # a simulation's
