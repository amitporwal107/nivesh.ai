"""Integration tests for /api/readyz (T4.1)."""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from portfolio_ingestion.clients import mongo as mongo_client
from portfolio_ingestion.config import reset_settings_for_test
from portfolio_ingestion.db import pool as pg_pool


pytestmark = pytest.mark.skipif(
    not (os.environ.get("PI_POSTGRES_URL") and os.environ.get("PI_MONGO_URL")),
    reason="needs PI_POSTGRES_URL + PI_MONGO_URL",
)


@pytest_asyncio.fixture
async def app_with_deps():
    reset_settings_for_test()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()
    from portfolio_ingestion.main import create_app
    yield create_app()
    await pg_pool.close_pool()
    await mongo_client.close_client()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()


@pytest.mark.integration
async def test_readyz_reports_ok_when_deps_reachable(app_with_deps):
    async with AsyncClient(transport=ASGITransport(app=app_with_deps), base_url="http://test") as c:
        r = await c.get("/api/readyz")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "ok"
    assert body["mongo"] == "ok"
    assert body["pg_pool_size"] is not None and body["pg_pool_size"] >= 1
    # We've applied 001..004; latest by applied_at should be one of them.
    assert body["migration_version"] is not None
    assert body["migration_version"].endswith(".sql")
