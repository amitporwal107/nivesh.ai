"""v1 answers of POST /api/strategy-builder/strategies do not change with the v2 store (TC-13 of
test_reports/strategy_store_v2_20261028.md).

The route now reads its body itself so it can tell a v2 document (`definition.schema_version == "2"`) from a v1 one. For
every v1 body FastAPI used to refuse, the answer must stay byte-identical. The reference here is the route's old
signature, `body: StrategyCreate`, mounted on its own app: the same model, validated the way FastAPI did before.

No network, no database: the user resolver is replaced (MOCK) and no request below reaches the pool.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import strategy_builder as route

URL = "/api/strategy-builder/strategies"
USER = {"X-Test-User": "user_a"}                             # MOCK user


@pytest.fixture
def clients(monkeypatch):
    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    async def no_pool():
        raise AssertionError("a refused v1 body must not reach the database")

    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(route.pg_client, "get_pool", no_pool)

    reference = FastAPI()

    @reference.post(URL)
    async def old_create(request: Request, body: route.StrategyCreate):   # the signature before Phase 1.1
        await fake_user(request)
        return {}

    real = FastAPI()
    real.include_router(route.router)
    return TestClient(reference), TestClient(real)


V1_DEF = {"version": "1", "asset_class": "STOCK", "name": "x", "universe": {"type": "index", "ref": "NIFTY50"}}

BODIES = {
    "missing name": {"asset_class": "STOCK", "definition": V1_DEF},
    "empty name": {"name": "", "asset_class": "STOCK", "definition": V1_DEF},
    "FNO on a v1 document": {"name": "x", "asset_class": "FNO", "definition": V1_DEF},
    "MIXED on a v1 document": {"name": "x", "asset_class": "MIXED", "definition": V1_DEF},
    "no definition": {"name": "x", "asset_class": "STOCK"},
    "definition not an object": {"name": "x", "asset_class": "STOCK", "definition": [1, 2]},
    "schema_version as a number": {"name": "x", "asset_class": "FNO", "definition": {"schema_version": 2}},
    "a list body": [{"name": "x"}],
    "a string body": "hello",
    "an empty object": {},
    "name too long": {"name": "y" * 101, "asset_class": "MF", "definition": V1_DEF},
}


@pytest.mark.parametrize("label", list(BODIES))
@pytest.mark.parametrize("headers", [USER, {}], ids=["signed-in", "no-session"])
def test_tc13_refused_v1_bodies_answer_exactly_as_before(clients, label, headers):
    reference, real = clients
    old = reference.post(URL, json=BODIES[label], headers=headers)
    new = real.post(URL, json=BODIES[label], headers=headers)
    assert old.status_code == 422, (label, old.text)
    assert (new.status_code, new.content) == (old.status_code, old.content), label


@pytest.mark.parametrize("raw", [b"", b"{not json", b"null"])
def test_tc13_missing_or_broken_json_answers_exactly_as_before(clients, raw):
    reference, real = clients
    hdrs = {**USER, "Content-Type": "application/json"}
    old = reference.post(URL, content=raw, headers=hdrs)
    new = real.post(URL, content=raw, headers=hdrs)
    assert (new.status_code, new.content) == (old.status_code, old.content), raw
