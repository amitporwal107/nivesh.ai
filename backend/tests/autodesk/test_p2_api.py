"""AD-P2-80..84, 92: the Phase 2 read APIs and the cancel route, over a simulation that filled one plan (test-double agents,
frozen session rows: TEST DATA, not real market data). Signed-in users are faked with a dependency override."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from autodesk.db import create_pool_for
from autodesk.execution import adapters as ad
from autodesk.execution.fill_model import DEFAULT_PARAMS
from autodesk.execution.gateway import ExecutionGateway
from autodesk.main import build_state, create_app
from autodesk.routers.api import current_user
from tests.autodesk import p2_harness as H
from tests.autodesk import stubs
from tests.autodesk.test_p2_simulation import session_rows

USERS = {"a": {"user_id": "p2-a", "role": "user"}, "b": {"user_id": "p2-b", "role": "user"}}
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

        gw = ExecutionGateway(pool, sim=ad.SimulationPaperAdapter(H.FrozenSessionBars(session_rows()), DEFAULT_PARAMS))
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
    r = client.post(f"{BASE}/simulations", headers=A, json={"name": "p2 api", "start_date": "2026-11-04", "end_date": "2026-11-05",
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


ROUTES = ["/accounts/ACC-x/capital", "/accounts/ACC-x/capital/ledger", "/accounts/ACC-x/reservations", "/accounts/ACC-x/pnl",
          "/execution/intents", "/execution/intents/INT-x", "/execution/orders", "/execution/orders/ORD-x", "/execution/fills",
          "/positions", "/positions/POS-x", "/journal"]


def test_adp2_80_signed_out_is_401(client):
    for path in ROUTES:
        assert client.get(BASE + path).status_code == 401, path
    assert client.post(f"{BASE}/execution/orders/ORD-x/cancel").status_code == 401


def test_adp2_81_other_tenant_gets_404_or_nothing(client, sim):
    sid, aid = sim["sid"], sim["account_id"]
    assert client.get(f"{BASE}/accounts/{aid}/capital", headers=B).status_code == 404
    assert client.get(f"{BASE}/accounts/{aid}/pnl", headers=B).status_code == 404
    assert client.get(f"{BASE}/accounts/{aid}/capital/ledger", headers=B).status_code == 404
    assert client.get(f"{BASE}/accounts/{aid}/reservations", headers=B).status_code == 404
    for path in ("execution/intents", "execution/orders", "execution/fills", "positions", "journal"):
        assert client.get(f"{BASE}/{path}?simulation_id={sid}", headers=B).json() == [], path
    oid = client.get(f"{BASE}/execution/orders?simulation_id={sid}", headers=A).json()[0]["order_id"]
    assert client.get(f"{BASE}/execution/orders/{oid}", headers=B).status_code == 404
    assert client.post(f"{BASE}/execution/orders/{oid}/cancel", headers=B).status_code == 404


def test_adp2_82_shapes_after_a_simulation(client, sim):
    sid, aid = sim["sid"], sim["account_id"]
    cap = client.get(f"{BASE}/accounts/{aid}/capital", headers=A).json()
    for k in ("cash_balance_rs", "used_margin_rs", "available_cash_rs", "reserved_capital_rs", "available_buying_power_rs",
              "deployed_notional_rs", "open_risk_rs", "pending_risk_rs", "pending_order_commitment_rs", "realized_gross_rs",
              "fees_rs", "net_realized_rs", "unrealized_gross_rs", "net_pnl_rs", "equity_rs", "reconciliation", "marks"):
        assert k in cap, k
    assert isinstance(cap["equity_rs"], str) and cap["reconciliation"]["difference_rs"] == "0.00" and "stale_legs" in cap["marks"]
    ledger = client.get(f"{BASE}/accounts/{aid}/capital/ledger", headers=A).json()
    assert ledger[0]["entry_type"] == "CAPITAL_AVAILABLE" and [e["seq"] for e in ledger] == sorted(e["seq"] for e in ledger)
    types = {e["entry_type"] for e in ledger}
    assert {"CAPITAL_RESERVED", "POSITION_FUNDS", "FEES_BOOKED", "CAPITAL_RESERVATION_CONSUMED"} <= types
    nxt = client.get(f"{BASE}/accounts/{aid}/capital/ledger?after_seq={ledger[0]['seq']}&limit=2", headers=A).json()
    assert len(nxt) == 2 and nxt[0]["seq"] > ledger[0]["seq"]
    res = client.get(f"{BASE}/accounts/{aid}/reservations", headers=A).json()
    assert res and res[0]["status"] == "CONSUMED"
    pnl = client.get(f"{BASE}/accounts/{aid}/pnl", headers=A).json()
    for k in ("gross_realized_rs", "gross_unrealized_rs", "charges_rs", "charges_by_component", "slippage_rs", "spread_rs",
              "net_realized_rs", "net_unrealized_rs", "by_strategy", "daily", "max_drawdown_rs", "max_drawdown_pct"):
        assert k in pnl, k
    intents = client.get(f"{BASE}/execution/intents?simulation_id={sid}", headers=A).json()
    assert intents and intents[0]["controls"] and intents[0]["order_spec"]
    assert client.get(f"{BASE}/execution/intents/{intents[0]['intent_id']}", headers=A).json()["status"] == "COMPLETED"
    orders = client.get(f"{BASE}/execution/orders?simulation_id={sid}&state=FILLED", headers=A).json()
    o = client.get(f"{BASE}/execution/orders/{orders[0]['order_id']}", headers=A).json()
    assert [h["to_state"] for h in o["history"]][-1] == "FILLED" and o["fills"] and o["fills"][0]["price"]
    pos = client.get(f"{BASE}/positions?simulation_id={sid}", headers=A).json()
    assert pos and pos[0]["legs"] and "mark_age_s" in pos[0]["legs"][0]
    assert client.get(f"{BASE}/positions/{pos[0]['position_id']}", headers=A).json()["position_id"] == pos[0]["position_id"]
    jr = client.get(f"{BASE}/journal?trade_id={pos[0]['trade_id']}", headers=A).json()
    assert [j["kind"] for j in jr][:1] == ["SIGNAL"] or "SIGNAL" in [j["kind"] for j in jr]
    assert {"PLAN_VERSION", "RISK_ASSESSMENT", "APPROVAL", "EXECUTION_INTENT", "RESERVATION", "ORDER", "FILL", "POSITION"} <= {j["kind"] for j in jr}
    # lists without simulation_id show desk rows only
    assert client.get(f"{BASE}/execution/orders", headers=A).json() == []
    results = client.get(f"{BASE}/simulations/{sid}/results", headers=A).json()
    assert results["execution_summary"]["trades"] == 2 and isinstance(results["execution"], str)


def test_adp2_83_cancel_route(client, sim):
    oid = client.get(f"{BASE}/execution/orders?simulation_id={sim['sid']}&state=FILLED", headers=A).json()[0]["order_id"]
    assert client.post(f"{BASE}/execution/orders/{oid}/cancel", headers=A).status_code == 409         # terminal


def test_adp2_92_fills_are_labelled_simulated(client, sim):
    fills = client.get(f"{BASE}/execution/fills?simulation_id={sim['sid']}", headers=A).json()
    assert fills and all(f["fill_kind"] == "SIMULATED" and f["broker_confirmed"] is False for f in fills)
    o = client.get(f"{BASE}/execution/orders?simulation_id={sim['sid']}", headers=A).json()[0]
    full = client.get(f"{BASE}/execution/orders/{o['order_id']}", headers=A).json()
    assert all(f["broker_confirmed"] is False for f in full["fills"])
