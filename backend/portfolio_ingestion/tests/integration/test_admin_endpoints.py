"""Integration tests for /api/admin/jobs/* (T4.3)."""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from portfolio_ingestion.clients import mongo as mongo_client
from portfolio_ingestion.config import reset_settings_for_test
from portfolio_ingestion.db import pool as pg_pool


pytestmark = pytest.mark.skipif(
    not os.environ.get("PI_POSTGRES_URL"),
    reason="needs PI_POSTGRES_URL",
)

ADMIN_TOKEN = "test-admin-token-" + uuid.uuid4().hex[:8]


@pytest_asyncio.fixture
async def admin_app():
    reset_settings_for_test()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()
    os.environ["PI_ADMIN_TOKEN"] = ADMIN_TOKEN
    from portfolio_ingestion.main import create_app
    yield create_app()
    os.environ.pop("PI_ADMIN_TOKEN", None)
    await pg_pool.close_pool()
    pg_pool.reset_pool_for_test()


@pytest.mark.integration
async def test_admin_requires_token(admin_app):
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        r = await c.get("/api/admin/jobs/summary")
    assert r.status_code == 401


@pytest.mark.integration
async def test_admin_rejects_wrong_token(admin_app):
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        r = await c.get(
            "/api/admin/jobs/summary",
            headers={"X-Admin-Token": "wrong"},
        )
    assert r.status_code == 401


@pytest.mark.integration
async def test_admin_summary_returns_counts(admin_app):
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        r = await c.get(
            "/api/admin/jobs/summary",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    # Each row has status + count
    for row in body:
        assert "status" in row
        assert "count" in row
        assert row["count"] >= 0


@pytest.mark.integration
async def test_admin_stale_endpoint_returns_list(admin_app):
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        r = await c.get(
            "/api/admin/jobs/stale?min_age_minutes=1",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)


@pytest.mark.integration
async def test_admin_503_when_token_unconfigured():
    reset_settings_for_test()
    pg_pool.reset_pool_for_test()
    os.environ.pop("PI_ADMIN_TOKEN", None)
    from portfolio_ingestion.main import create_app
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            "/api/admin/jobs/summary",
            headers={"X-Admin-Token": "anything"},
        )
    assert r.status_code == 503
    await pg_pool.close_pool()
    pg_pool.reset_pool_for_test()
