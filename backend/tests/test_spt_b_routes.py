"""SPT slice B — the /api/v1 routes (routes/spt_accounts.py, routes/spt_risk.py) over HTTP (TESTCASES
test_reports/spt_b_TESTCASES.md SPT-B-02..04 over HTTP, 31 over HTTP, 34, 35, 36, 38).

`get_current_user` reads the test's X-Test-User header (none → 401); `db` is the in-memory store (tests/spt_b_fakes.py).
MOCK — not real data: every user, symbol, price, opportunity and ledger row is made up."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from services.spt import constants as C, pipeline
from tests.spt_b_fakes import NOW, U1, U2, opportunity, world  # noqa: F401 (world is a fixture)

A = {"X-Test-User": U1}
B = {"X-Test-User": U2}


@pytest.fixture
def client(world, monkeypatch):
    from routes import spt_accounts, spt_risk
    monkeypatch.setattr(spt_accounts, "db", world.db)
    monkeypatch.setattr(spt_risk, "db", world.db)

    async def user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}
    monkeypatch.setattr(spt_accounts, "get_current_user", user)
    monkeypatch.setattr(spt_risk, "get_current_user", user)
    app = FastAPI()
    app.include_router(spt_accounts.router)
    app.include_router(spt_risk.router)
    c = TestClient(app)
    c.world = world
    return c


def ready(client, mode="approval"):
    w = client.world
    w.store.add(opportunity())
    w.quote("FIXA", 502.0, ask=502.0)
    r = client.put(f"/api/v1/paper/accounts/{U1}/config", json={"mode": mode, "reason": "MOCK opt in"}, headers=A)
    assert r.status_code == 200, r.text
    return w


# ── SPT-B-04 auth ────────────────────────────────────────────────────────────
ROUTES = [("get", "/api/v1/paper/accounts", None), ("get", f"/api/v1/paper/accounts/{U1}", None),
          ("put", f"/api/v1/paper/accounts/{U1}/config", {"mode": "auto"}), ("get", f"/api/v1/paper/accounts/{U1}/ledger", None),
          ("post", "/api/v1/risk/calculate-position-size", {}), ("post", "/api/v1/risk/validate-trade", {}),
          ("get", f"/api/v1/risk/account/{U1}", None), ("get", f"/api/v1/risk/exposures/{U1}", None),
          ("get", f"/api/v1/risk/stress-test/{U1}", None), ("get", f"/api/v1/allocation/recommendations/{U1}", None),
          ("post", f"/api/v1/allocation/recalculate/{U1}", None), ("get", "/api/v1/proposals", None),
          ("get", "/api/v1/proposals/x", None), ("post", "/api/v1/opportunities/opp-FIXA/approve", None),
          ("post", "/api/v1/opportunities/opp-FIXA/reject", {"reason": "x"})]


@pytest.mark.parametrize("method, url, body", ROUTES)
def test_spt_b_04_every_route_needs_a_session(client, method, url, body):
    r = getattr(client, method)(url, **({"json": body} if body is not None else {}))
    assert r.status_code == 401


@pytest.mark.parametrize("method, url, body", [x for x in ROUTES if f"/{U1}" in x[1]])
def test_spt_b_04b_another_users_account_is_403(client, method, url, body):
    r = getattr(client, method)(url, headers=B, **({"json": body} if body is not None else {}))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_your_account"


# ── SPT-B-02, 03 config over HTTP ────────────────────────────────────────────
def test_spt_b_02_03_config_over_http(client):
    r = client.get("/api/v1/paper/accounts", headers=A)
    body = r.json()
    assert r.status_code == 200 and body["count"] == 1
    acc = body["accounts"][0]
    assert acc["account_id"] == U1 and acc["config"]["mode"] == "off" and acc["account"]["available_rs"] == 1_000_000.0
    for payload, status, code in (({"mode": "yolo"}, 422, "invalid_mode"),
                                  ({"extras": {"risk_pct": {"positional": 1.0}}}, 403, "admin_required"),
                                  ({"mode": "auto", "colour": "red"}, 422, "unknown_field")):
        r = client.put(f"/api/v1/paper/accounts/{U1}/config", json=payload, headers=A)
        assert r.status_code == status and r.json()["detail"]["code"] == code
    r = client.put(f"/api/v1/paper/accounts/{U1}/config", content=b"{not json", headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_body"
    r = client.put(f"/api/v1/paper/accounts/{U1}/config",
                   json={"mode": "approval", "extras": {"max_positions": 6}, "reason": "MOCK"}, headers=A)
    assert r.status_code == 200 and r.json()["config"]["version"] == 1 and r.json()["config"]["extras"]["max_positions"] == 6
    r = client.put(f"/api/v1/paper/accounts/{U1}/config", json={"mode": "auto", "expected_version": 0}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "concurrent_change"
    got = client.get(f"/api/v1/paper/accounts/{U1}", headers=A).json()
    assert [v["version"] for v in got["config_versions"]] == [1] and got["config_versions"][0]["actor"] == U1


def test_spt_b_36_ledger_is_paginated_newest_first(client):
    w = client.world
    for i in range(5):                                           # MOCK ledger rows (ObjectId-less, as fakes insert them)
        w.db["paper_account_ledger"].docs.append({"_id": f"row{i}", "user_id": U1, "at": f"2026-11-05T04:0{i}:00+00:00",
                                                  "action": "reserve", "amount_rs": 100.0 * i})
    w.db["paper_account_ledger"].docs.append({"_id": "other", "user_id": U2, "at": "2026-11-05T04:09:00+00:00"})
    r = client.get(f"/api/v1/paper/accounts/{U1}/ledger?limit=2", headers=A).json()
    assert [x["entry_id"] for x in r["items"]] == ["row4", "row3"] and r["next_before"] == "2026-11-05T04:03:00+00:00"
    r = client.get(f"/api/v1/paper/accounts/{U1}/ledger?limit=10&before={r['next_before']}", headers=A).json()
    assert [x["entry_id"] for x in r["items"]] == ["row2", "row1", "row0"] and r["next_before"] is None


# ── SPT-B-34 pure sizing over HTTP ───────────────────────────────────────────
def test_spt_b_34_calculate_position_size_is_pure(client):
    r = client.post("/api/v1/risk/calculate-position-size", headers=A,
                    json={"equity_rs": 1_000_000, "risk_pct": 0.5, "entry": 500, "stop": 480, "cost_per_share": 0.5})
    body = r.json()
    assert r.status_code == 200 and body["quantity"] == 243 and body["capital_required"] == 121_500.0
    assert body["planned_risk"] == 4981.5 and body["pure"] is True
    assert all(not c.docs for c in client.world.db.cols.values())          # read nothing back, wrote nothing
    for payload, code in (({"equity_rs": 1e6, "risk_pct": 0.5, "entry": 500}, "invalid_input"),
                          ({"equity_rs": 1e6, "risk_pct": 0.5, "entry": 500, "stop": 480, "foo": 1}, "unknown_field"),
                          ({"equity_rs": 1e6, "risk_pct": 0.5, "entry": 500, "stop": 480, "lot_size": 0}, "invalid_input")):
        r = client.post("/api/v1/risk/calculate-position-size", headers=A, json=payload)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code


# ── SPT-B-35 dry-run validation ──────────────────────────────────────────────
def test_spt_b_35_validate_trade_is_a_dry_run(client):
    w = ready(client, mode="auto")
    before = {k: len(c.docs) for k, c in w.db.cols.items()}
    r = client.post("/api/v1/risk/validate-trade", headers=A, json={"opportunity_id": "opp-FIXA"})
    body = r.json()
    assert r.status_code == 200 and body["dry_run"] is True and body["decision"] == C.RISK_APPROVE
    assert body["risk"]["dry_run"] is True and body["risk"]["risk_service_decision_id"] is None
    assert body["sizing"]["quantity"] > 0 and body["allocation"]["decision"] == "ALLOCATION_APPROVED"
    r = client.post("/api/v1/risk/validate-trade", headers=A,
                    json={"symbol": "FIXA", "entry": 502, "stop_loss": 480, "target": 580, "quantity": 50})
    assert r.status_code == 200 and r.json()["decision"] == C.RISK_APPROVE and r.json()["risk"]["requested_qty"] == 50
    after = {k: len(c.docs) for k, c in w.db.cols.items()}
    for k in ("risk_decisions", C.PROPOSALS, C.EVENTS, "paper_accounts", "paper_account_ledger"):
        assert after.get(k, 0) == before.get(k, 0), k
    r = client.post("/api/v1/risk/validate-trade", headers=A, json={"symbol": "FIXA", "entry": 502, "stop_loss": 510,
                                                                     "target": 580})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_input"
    r = client.post("/api/v1/risk/validate-trade", headers=A, json={"opportunity_id": "nope"})
    assert r.status_code == 404


# ── SPT-B-36 account risk, exposures, recommendations, recalculate, proposals ─
def test_spt_b_36_risk_account_and_exposures(client):
    w = ready(client, mode="auto")
    pipeline_report = __import__("asyncio").new_event_loop().run_until_complete(pipeline.run_round(w.db, NOW))
    assert pipeline_report["orders"] == 1
    r = client.get(f"/api/v1/risk/account/{U1}", headers=A)
    body = r.json()
    assert r.status_code == 200 and body["equity_rs"] == 1_000_000.0 and body["mode"] == "auto"
    q = w.proposals(U1)[0]["risk"]["approved_qty"]
    assert body["reserved_rs"] == round(q * 502.0, 2) and body["deployed_rs"] == 0.0         # the order is PENDING
    assert body["kill_switch"]["state"] == "ACTIVE" and body["drawdown"]["ladder"]["band"] == "normal"
    assert body["daily_loss"]["breached"] is False and body["open_risk"]["cap_rs"] == 30_000.0
    assert body["spt_risk"]["entries"] == 1 and body["spt_risk"]["planned_rs"] > 0
    assert body["utilisation"]["positions"] == {"open": 1, "max": 10} and body["utilisation"]["new_today"]["count"] == 1
    r = client.get(f"/api/v1/risk/exposures/{U1}", headers=A).json()
    assert r["by_instrument"][0]["symbol"] == "FIXA" and r["by_sector"][0]["sector"] == "MOCK Sector"
    assert next(c for c in r["by_category"] if c["category"] == "equity_positional")["used_rs"] == round(q * 502.0, 2)
    r = client.get(f"/api/v1/risk/stress-test/{U1}", headers=A).json()
    assert r["totals"]["planned_rs"] == body["spt_risk"]["planned_rs"] and r["version"] == "spt-stress-v1"


def test_spt_b_36b_recommendations_write_nothing_and_rank(client):
    w = client.world
    w.store.add(opportunity("FIXA", score=60.0, scanner_score=99.0), opportunity("FIXB", score=85.0))
    w.quote("FIXA", 502.0, ask=502.0)
    w.quote("FIXB", 502.0, ask=502.0)
    r = client.get(f"/api/v1/allocation/recommendations/{U1}", headers=A).json()
    assert [i["symbol"] for i in r["items"]] == ["FIXB", "FIXA"] and r["writes"] == "none"
    assert r["items"][0]["allocation"]["decision"] == "ALLOCATION_APPROVED" and r["items"][0]["sizing"]["quantity"] > 0
    for k in (C.PROPOSALS, C.EVENTS, "risk_decisions", "paper_accounts"):
        assert not w.db[k].docs, k


def test_spt_b_31_36_approve_reject_and_proposals_over_http(client):
    w = ready(client, mode="approval")
    loop = __import__("asyncio").new_event_loop()
    loop.run_until_complete(pipeline.run_round(w.db, NOW))
    w.store.add(opportunity("FIXB"))
    w.quote("FIXB", 501.0, ask=501.0)
    loop.run_until_complete(pipeline.run_round(w.db, NOW))
    loop.close()
    r = client.get("/api/v1/proposals", headers=A).json()
    assert r["count"] == 2 and {p["state"] for p in r["items"]} == {C.PROP_AWAITING_USER}
    assert client.get("/api/v1/proposals", headers=B).json()["count"] == 0
    pid = r["items"][0]["proposal_id"]
    assert client.get(f"/api/v1/proposals/{pid}", headers=A).json()["proposal_id"] == pid
    assert client.get(f"/api/v1/proposals/{pid}", headers=B).status_code == 404
    assert client.get("/api/v1/proposals?state=NOPE", headers=A).status_code == 422
    rc = client.post(f"/api/v1/allocation/recalculate/{U1}", headers=A).json()
    assert len(rc["recalculated"]) == 2 and all(x["recorded"] for x in rc["recalculated"])
    r = client.post("/api/v1/opportunities/opp-FIXA/approve", headers=B)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "proposal_not_found"
    r = client.post("/api/v1/opportunities/opp-FIXA/approve", headers=A)
    assert r.status_code == 200 and r.json()["proposal"]["state"] == C.PROP_ORDER_CREATED
    assert client.post("/api/v1/opportunities/opp-FIXA/approve", headers=A).json()["idempotent"] is True
    r = client.post("/api/v1/opportunities/opp-FIXB/reject", headers=A, json={})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reason_required"
    r = client.post("/api/v1/opportunities/opp-FIXB/reject", headers=A, json={"reason": "MOCK: not today"})
    assert r.status_code == 200 and r.json()["proposal"]["state"] == C.PROP_USER_REJECTED
    r = client.post("/api/v1/opportunities/opp-FIXB/approve", headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "invalid_state"
