"""Integration tests for the read endpoints.

The fixtures stand up a user → run one sdk-callback to seed an active
snapshot → then exercise the GET endpoints. Auth boundary check: a second
user CANNOT see the first user's snapshot.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from portfolio_ingestion.clients import mongo as mongo_client
from portfolio_ingestion.config import reset_settings_for_test
from portfolio_ingestion.db import pool as pg_pool
from portfolio_ingestion.services import parsed_data_archive as archive_mod


pytestmark = pytest.mark.skipif(
    not (os.environ.get("PI_POSTGRES_URL") and os.environ.get("PI_MONGO_URL")),
    reason="needs PI_POSTGRES_URL + PI_MONGO_URL",
)


@pytest_asyncio.fixture
async def app_with_seed():
    reset_settings_for_test()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()
    archive_mod.reset_indexes_cache_for_test()

    from portfolio_ingestion.main import create_app
    app = create_app()

    external_id = f"read-{uuid.uuid4()}"
    pan = "READ" + uuid.uuid4().hex[:6].upper()      # 10 chars

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = {
            "checksum": uuid.uuid4().hex,
            "statement_from": "2026-01-01", "statement_to": "2026-01-31",
            "generated_at": "2026-02-01T00:00:00+00:00",
            "source_type": "ECAS_CDSL",
            "metadata": {"method": "upload", "cas_type": "cdsl"},
            "data": {
                "investor": {"pan": pan},
                "demat_accounts": [{"holdings":[
                    {"isin":"INE002A01018","name":"RELIANCE","quantity":"10","value":"25000","instrument_type":"equity"},
                    {"isin":"INE090A01021","name":"ICICI BANK","quantity":"5","value":"5000","instrument_type":"equity"},
                ]}],
                "mutual_funds": [{"amc":"HDFC","folios":[{"folio":"F-1","schemes":[
                    {"scheme_code":"120503","name":"HDFC Flexi Cap","units":"100","value":"10000"},
                ]}]}],
            },
        }
        r = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id}, json=body,
        )
        assert r.status_code == 200, r.text
        first_snapshot_id = r.json()["snapshot_id"]

    yield app, external_id, pan, first_snapshot_id

    # Cleanup
    from portfolio_ingestion.services.checksum import pan_hash as _hash
    panh = _hash(pan)
    pool = await pg_pool.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM portfolio_ingestion.holdings WHERE pan_hash=$1", panh)
        await conn.execute("DELETE FROM portfolio_ingestion.snapshots WHERE pan_hash=$1", panh)
        await conn.execute("DELETE FROM portfolio_ingestion.ingestion_jobs WHERE pan_hash=$1", panh)
        await conn.execute("DELETE FROM portfolio_ingestion.users WHERE pan_hash=$1", panh)
    db = await mongo_client.get_database()
    await db[archive_mod.COLLECTION].delete_many({"pan_hash": panh})
    await pg_pool.close_pool()
    await mongo_client.close_client()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()


# ── /me ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_get_me_returns_active_snapshot(app_with_seed) -> None:
    app, external_id, _, _ = app_with_seed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/portfolio/me", headers={"X-User-External-Id": external_id}
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot"]["is_active"] is True
    assert body["portfolio"]["holdings_count"] == 3
    assert Decimal(body["portfolio"]["total_value"]) == Decimal("40000.00")


@pytest.mark.integration
async def test_get_me_404_for_unknown_user(app_with_seed) -> None:
    app, _, _, _ = app_with_seed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/portfolio/me",
            headers={"X-User-External-Id": f"ghost-{uuid.uuid4()}"},
        )
    assert r.status_code == 404


# ── /snapshots ───────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_list_snapshots(app_with_seed) -> None:
    app, external_id, _, first_id = app_with_seed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/portfolio/snapshots", headers={"X-User-External-Id": external_id}
        )
    assert r.status_code == 200
    out = r.json()["snapshots"]
    assert len(out) == 1
    assert out[0]["id"] == first_id
    assert out[0]["is_active"] is True
    assert out[0]["holdings_count"] == 3


# ── /snapshots/{id} ─────────────────────────────────────────────────────


@pytest.mark.integration
async def test_get_snapshot_by_id(app_with_seed) -> None:
    app, external_id, _, first_id = app_with_seed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/portfolio/snapshots/{first_id}",
            headers={"X-User-External-Id": external_id},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot"]["id"] == first_id
    assert body["portfolio"]["holdings_count"] == 3


@pytest.mark.integration
async def test_get_snapshot_404_for_unknown_id(app_with_seed) -> None:
    app, external_id, _, _ = app_with_seed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/portfolio/snapshots/{uuid.uuid4()}",
            headers={"X-User-External-Id": external_id},
        )
    assert r.status_code == 404


# ── Auth boundary: user-B cannot see user-A's snapshot ──────────────────


@pytest.mark.integration
async def test_cross_user_read_is_404_not_403(app_with_seed) -> None:
    """A different external_id with a different PAN gets 404 on the same id."""
    app, _, _, snapshot_id = app_with_seed
    # Stand up user-B with their own active snapshot (so /me works for them)
    pan_b = "OTHRX" + uuid.uuid4().hex[:5].upper()
    ext_b = f"read-other-{uuid.uuid4()}"
    body_b = {
        "checksum": uuid.uuid4().hex,
        "statement_from": "2026-02-01", "statement_to": "2026-02-28",
        "generated_at": "2026-03-01T00:00:00+00:00",
        "source_type": "ECAS_CDSL", "metadata": {"method": "upload"},
        "data": {
            "investor": {"pan": pan_b},
            "demat_accounts": [], "mutual_funds": [],
        },
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/cas/sdk-callback",
                headers={"X-User-External-Id": ext_b}, json=body_b,
            )
            assert r.status_code == 200, r.text
            # user-B tries to read user-A's snapshot by id
            r2 = await client.get(
                f"/api/portfolio/snapshots/{snapshot_id}",
                headers={"X-User-External-Id": ext_b},
            )
            assert r2.status_code == 404
    finally:
        from portfolio_ingestion.services.checksum import pan_hash as _hash
        panh = _hash(pan_b)
        pool = await pg_pool.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM portfolio_ingestion.holdings WHERE pan_hash=$1", panh)
            await conn.execute("DELETE FROM portfolio_ingestion.snapshots WHERE pan_hash=$1", panh)
            await conn.execute("DELETE FROM portfolio_ingestion.ingestion_jobs WHERE pan_hash=$1", panh)
            await conn.execute("DELETE FROM portfolio_ingestion.users WHERE pan_hash=$1", panh)
        db = await mongo_client.get_database()
        await db[archive_mod.COLLECTION].delete_many({"pan_hash": panh})
