"""DaaS API tests — auth, envelope shape, rate-limit wiring.

These tests do NOT require a live Postgres. We monkey-patch the auth +
ratelimit + key-lookup paths and stub the asyncpg pool with an in-memory
fake. Goal is to verify the FastAPI surface itself: routing, auth, error
shape, header propagation, pagination defaults."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient


# ── Stub asyncpg pool ──────────────────────────────────────────────
class _FakeConn:
    def __init__(self, store: Dict[str, List[Dict[str, Any]]]):
        self._store = store

    async def fetch(self, query: str, *args):
        return self._store.get("fetch", [])

    async def fetchrow(self, query: str, *args):
        rows = self._store.get("fetchrow", [])
        return rows[0] if rows else None

    async def fetchval(self, query: str, *args):
        return self._store.get("fetchval", 1)

    async def execute(self, query: str, *args):
        return "OK"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, store: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self._store = store or {}

    def acquire(self):
        # Return an async-context-manager that yields a _FakeConn.
        store = self._store
        class _CM:
            async def __aenter__(self_inner):
                return _FakeConn(store)
            async def __aexit__(self_inner, *a):
                return False
        return _CM()


@pytest.fixture
def fake_pool(monkeypatch):
    pool = _FakePool({})

    async def _get_pool():
        return pool

    async def _close_pool():
        return None

    import nidp.shared.storage.pg as pg_mod
    monkeypatch.setattr(pg_mod, "get_pool", _get_pool)
    monkeypatch.setattr(pg_mod, "close_pool", _close_pool)
    return pool


@pytest.fixture
def stub_auth(monkeypatch):
    """Stub key lookup + rate-limit so the app accepts our test token
    and never touches the DB for auth bookkeeping."""
    from nidp.services.daas_api import auth, keys, ratelimit

    rec = keys.KeyRecord(
        key_id="00000000-0000-0000-0000-000000000001",
        key_prefix="nvd_test123",
        name="test",
        owner_email="test@nivesh",
        plan="pro",
        rate_limit_rpm=1500,
        daily_quota=None,
        status="active",
        expires_at=None,
    )

    async def _resolve(_token):
        return rec

    monkeypatch.setattr(auth, "_resolve", _resolve)

    async def _consume(key_id, *, limit_rpm, daily_quota):
        return ratelimit.LimitDecision(
            allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1,
            reset_seconds=60, daily_quota=daily_quota,
            daily_used=1, daily_remaining=None, reason=None,
        )

    monkeypatch.setattr(ratelimit, "consume", _consume)
    return rec


@pytest.fixture
def client(fake_pool, stub_auth):
    # Disable usage logging so middleware doesn't try to insert.
    import nidp.services.daas_api.middleware as mw
    mw._LOG_REQUESTS = False
    from nidp.services.daas_api.app import app
    with TestClient(app) as c:
        yield c


# ── Tests ──────────────────────────────────────────────────────────
def test_health_no_auth_required(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "nidp-daas-api"


def test_v1_requires_api_key(client):
    r = client.get("/v1/me")
    assert r.status_code == 401
    assert r.json()["error"]["status"] == 401


def test_v1_accepts_xapikey(client):
    r = client.get("/v1/me", headers={"X-API-Key": "nvd_test_doesnt_matter"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key_id"] == "00000000-0000-0000-0000-000000000001"
    assert body["plan"] == "pro"
    assert body["rate_limit"]["limit_rpm"] == 1500


def test_v1_accepts_bearer(client):
    r = client.get("/v1/me", headers={"Authorization": "Bearer nvd_test_token"})
    assert r.status_code == 200


def test_response_headers_set(client):
    r = client.get("/v1/me", headers={"X-API-Key": "nvd_test"})
    assert r.headers["X-Service"] == "nidp-daas-api"
    assert "X-Request-Id" in r.headers
    assert r.headers["X-RateLimit-Limit"] == "1500"


def test_prices_eod_envelope_shape(client):
    r = client.get("/v1/prices/eod/RELIANCE", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert "pagination" in body
    assert body["pagination"]["limit"] == 100
    assert body["pagination"]["offset"] == 0
    assert body["symbol"] == "RELIANCE"


def test_pagination_limit_caps(client):
    r = client.get("/v1/prices/eod/TCS?limit=99999", headers={"X-API-Key": "k"})
    # Pydantic validation kicks in via FastAPI's Query(le=5000)
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["message"] == "validation_error"


def test_invalid_date_400(client):
    r = client.get("/v1/prices/eod/INFY?start=not-a-date", headers={"X-API-Key": "k"})
    assert r.status_code == 400


def test_symbol_normalisation(client):
    r = client.get("/v1/prices/eod/reliance", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.json()["symbol"] == "RELIANCE"


def test_catalog_lists_datasets(client):
    r = client.get("/v1/catalog", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert "datasets" in body
    assert len(body["datasets"]) >= 18
    # Every dataset must declare at least one endpoint.
    for ds in body["datasets"]:
        assert ds["endpoints"]


def test_openapi_includes_v1_routes(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    paths = set(spec["paths"].keys())
    must = {"/v1/me", "/v1/catalog", "/v1/prices/eod/{symbol}",
            "/v1/corporate-actions", "/v1/fno/{symbol}/chain",
            "/v1/announcements", "/v1/macro/rbi-yields"}
    assert must <= paths


def test_404_uses_error_envelope(client):
    r = client.get("/v1/nope", headers={"X-API-Key": "k"})
    assert r.status_code == 404
    body = r.json()
    assert "error" in body
    assert body["error"]["status"] == 404


# ── Rate-limit module unit tests (no app — pure logic) ─────────────
def test_ratelimit_minute_window():
    from nidp.services.daas_api import ratelimit
    ratelimit.reset_buckets_for_tests()

    async def _go():
        # First 3 requests at limit=3 must pass; 4th must fail.
        for _ in range(3):
            d = await ratelimit._check_minute("k", limit_rpm=3)
            assert d[0] is True
        d = await ratelimit._check_minute("k", limit_rpm=3)
        assert d[0] is False
        assert d[2] >= 1

    asyncio.run(_go())


# ── Key-issuance helpers (no DB required) ──────────────────────────
def test_token_format_and_hash_stability():
    from nidp.services.daas_api import keys
    t1 = keys._generate_token()
    t2 = keys._generate_token()
    assert t1.startswith("nvd_") and len(t1) == 4 + 32
    assert t1 != t2
    h = keys.hash_token(t1)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert keys.hash_token(t1) == h          # deterministic


def test_known_plans_complete():
    from nidp.services.daas_api import keys
    assert {"free", "standard", "pro", "internal"} == set(keys.known_plans())
