"""Query API portfolio ingest endpoints (POST /portfolio/ingest-*).

The sync services' ``ingest_records`` functions are stubbed, so nothing here
touches a database. All users and figures are made up.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nidp.services.query_api import auth
from nidp.services.query_api.routers import portfolio
from nidp.services.portfolio_holdings_sync import service as holdings_sync
from nidp.services.portfolio_transactions_sync import service as txn_sync
from nidp.services.portfolio_goals_sync import service as goals_sync

TOKEN = "unit-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "_TOKEN", TOKEN)
    app = FastAPI()
    app.include_router(portfolio.router)
    return TestClient(app)


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    async def holdings(records, sync_run_id=None):
        seen["holdings"] = records
        return {"synced": len(records), "skipped": 0, "errors": 0,
                "holdings": sum(len(r["holdings"]) for r in records), "sync_run_id": "run-h"}

    async def txns(records, sync_run_id=None):
        seen["transactions"] = records
        return {"users": 1, "txns_seen": len(records), "txns_upserted": len(records), "errors": 0, "sync_run_id": "run-t"}

    async def goals(records, target_date=None, sync_run_id=None):
        seen["goals"] = (records, target_date)
        return {"users": 1, "goals_seen": len(records), "goals_upserted": len(records), "errors": 0, "sync_run_id": "run-g"}

    monkeypatch.setattr(holdings_sync, "ingest_records", holdings)
    monkeypatch.setattr(txn_sync, "ingest_records", txns)
    monkeypatch.setattr(goals_sync, "ingest_records", goals)
    return seen


def _holding(user, isin, **kw):
    return {"external_user_id": user, "client_id": f"id-{user}", "display_name": user.title(),
            "asset_class": "EQUITY", "isin": isin, "instrument_name": f"Co {isin}",
            "quantity": 10.0, "avg_buy_price": 5.0, "market_value_inr": 60.0, "weight_pct": 50.0,
            "source_system": "nivesh_cas", **kw}


@pytest.mark.parametrize("path", ["/portfolio/ingest-holdings", "/portfolio/ingest-transactions", "/portfolio/ingest-goals"])
def test_requires_the_bearer_token(client, captured, path):
    assert client.post(path, json={"records": []}).status_code == 401
    assert client.post(path, json={"records": []}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert captured == {}


def test_holdings_are_grouped_per_user_and_snapshot_date(client, captured):
    body = {"snapshot_date": "2026-01-09", "records": [
        _holding("a@example.invalid", "INE000A01011"),
        _holding("a@example.invalid", "INE000B01019", snapshot_date="2026-01-09"),
        _holding("b@example.invalid", "INE000A01011"),
    ]}
    r = client.post("/portfolio/ingest-holdings", json=body, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "upserted": 3, "users": 2, "synced": 2, "skipped": 0,
                        "errors": 0, "sync_run_id": "run-h"}
    by_user = {c["external_user_id"]: c for c in captured["holdings"]}
    assert set(by_user) == {"a@example.invalid", "b@example.invalid"}
    a = by_user["a@example.invalid"]
    assert a["snapshot_date"] == "2026-01-09" and a["client_id"] == "id-a@example.invalid"
    assert [h["isin"] for h in a["holdings"]] == ["INE000A01011", "INE000B01019"]
    # per-holding fields only: user-level keys are not repeated inside each holding
    assert "external_user_id" not in a["holdings"][0] and a["holdings"][0]["quantity"] == 10.0


def test_holding_without_user_or_date_is_rejected(client, captured):
    r = client.post("/portfolio/ingest-holdings", headers=AUTH,
                    json={"records": [_holding("a@example.invalid", "INE000A01011")]})   # no snapshot date anywhere
    assert r.status_code == 422
    bad = _holding("", "INE000A01011")
    assert client.post("/portfolio/ingest-holdings", headers=AUTH,
                       json={"snapshot_date": "2026-01-09", "records": [bad]}).status_code == 422
    assert captured == {}


@pytest.mark.parametrize("body", [{}, {"records": "nope"}, {"records": [1, 2]}, {"records": [], "snapshot_date": "09/01/2026"}])
def test_malformed_bodies_are_rejected(client, captured, body):
    assert client.post("/portfolio/ingest-holdings", json=body, headers=AUTH).status_code == 422


def test_too_many_records_is_rejected(client, captured, monkeypatch):
    monkeypatch.setattr(portfolio, "MAX_RECORDS", 2)
    body = {"snapshot_date": "2026-01-09", "records": [_holding("a@example.invalid", f"INE00000000{i}") for i in range(3)]}
    assert client.post("/portfolio/ingest-holdings", json=body, headers=AUTH).status_code == 413


def test_empty_push_does_not_call_the_sync_service(client, captured):
    r = client.post("/portfolio/ingest-transactions", json={"records": []}, headers=AUTH)
    assert r.status_code == 200 and r.json()["upserted"] == 0
    assert captured == {}


def test_transactions_and_goals_pass_records_through(client, captured):
    txn = {"external_user_id": "a@example.invalid", "txn_date": "2026-01-05", "txn_type": "PURCHASE",
           "isin": "INF000A01AA1", "asset_class": "MF", "units": 10.0, "amount_inr": 1000.0, "nav_or_price": 100.0}
    r = client.post("/portfolio/ingest-transactions", json={"records": [txn], "snapshot_date": "2026-01-09"}, headers=AUTH)
    assert r.json() == {"ok": True, "upserted": 1, "users": 1, "seen": 1, "errors": 0, "sync_run_id": "run-t"}
    assert captured["transactions"] == [txn]

    goal = {"external_user_id": "a@example.invalid", "goal_id": "00000000-0000-0000-0000-000000000001", "goal_name": "Test"}
    r = client.post("/portfolio/ingest-goals", json={"records": [goal], "snapshot_date": "2026-01-09"}, headers=AUTH)
    assert r.json()["upserted"] == 1 and r.json()["sync_run_id"] == "run-g"
    records, target = captured["goals"]
    assert records == [goal] and str(target) == "2026-01-09"


def test_errors_from_the_sync_service_make_ok_false(client, monkeypatch):
    async def holdings(records, sync_run_id=None):
        return {"synced": 0, "skipped": 0, "errors": 1, "holdings": 0, "sync_run_id": "run-x"}
    monkeypatch.setattr(holdings_sync, "ingest_records", holdings)
    r = client.post("/portfolio/ingest-holdings", headers=AUTH,
                    json={"snapshot_date": "2026-01-09", "records": [_holding("a@example.invalid", "INE000A01011")]})
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["errors"] == 1


# ── JSON-borne dates must be bound as date/datetime objects ────────────────

class _Conn:
    def __init__(self):
        self.args = None

    async def execute(self, sql, *args):
        self.args = args
        return "INSERT 0 1"


def test_transaction_date_string_is_bound_as_a_date():
    import asyncio, datetime
    conn = _Conn()
    asyncio.run(txn_sync._upsert_transaction(conn, {
        "external_user_id": "a@example.invalid", "txn_date": "2026-01-05", "txn_type": "PURCHASE",
        "asset_class": "MF", "units": 10.0, "amount_inr": 1000.0}))
    assert conn.args[2] == datetime.date(2026, 1, 5)


def test_goal_timestamp_strings_are_bound_as_datetimes():
    import asyncio, datetime
    conn = _Conn()
    asyncio.run(goals_sync._upsert_goal(conn, {
        "goal_id": "00000000-0000-0000-0000-000000000001", "external_user_id": "a@example.invalid",
        "last_simulated_at": "2026-01-09T10:00:00+00:00", "upstream_created_at": "2026-01-01T00:00:00Z",
        "upstream_updated_at": None}))
    stamps = [a for a in conn.args if isinstance(a, datetime.datetime)]
    assert len(stamps) == 2 and all(s.tzinfo is not None for s in stamps)
    assert not any(isinstance(a, str) and a.startswith("2026-01-0") for a in conn.args)
