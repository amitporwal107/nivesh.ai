"""Integration tests for the signed-URL upload flow (T3.1 / T3.2)."""
from __future__ import annotations

import os
import uuid

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

PAN = "UPLDA" + uuid.uuid4().hex[:5].upper()  # 10 chars, module-level so stable


@pytest_asyncio.fixture
async def fresh_upload_user():
    reset_settings_for_test()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()
    archive_mod.reset_indexes_cache_for_test()

    os.environ.setdefault("PI_GCS_STUB", "true")

    from portfolio_ingestion.main import create_app
    app = create_app()
    external_id = f"upld-{uuid.uuid4()}"
    pan = "UPLDA" + uuid.uuid4().hex[:5].upper()

    yield app, external_id, pan

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


@pytest.mark.integration
async def test_uploads_init_creates_pending_upload_job(fresh_upload_user):
    app, external_id, pan = fresh_upload_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/cas/uploads/init",
            headers={
                "X-User-External-Id": external_id,
                "X-User-Pan": pan,
            },
            json={"source_type": "ECAS_CDSL", "filename": "cas.pdf"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "upload_id" in body
    assert "upload_url" in body
    assert body["stub"] is True
    assert "cas-uploads/" in body["object_key"]

    # Verify the job row is in pending_upload state
    from portfolio_ingestion.services.checksum import pan_hash as _hash
    panh = _hash(pan)
    pool = await pg_pool.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, pdf_status, pdf_gcs_key FROM portfolio_ingestion.ingestion_jobs "
            "WHERE pan_hash = $1 ORDER BY created_at DESC LIMIT 1",
            panh,
        )
    assert row is not None
    assert row["status"] == "pending_upload"
    assert row["pdf_status"] == "pending"
    assert row["pdf_gcs_key"] is not None


@pytest.mark.integration
async def test_uploads_complete_activates_snapshot(fresh_upload_user):
    app, external_id, pan = fresh_upload_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        init_r = await c.post(
            "/api/cas/uploads/init",
            headers={"X-User-External-Id": external_id, "X-User-Pan": pan},
            json={"source_type": "ECAS_CDSL"},
        )
        assert init_r.status_code == 200, init_r.text
        upload_id = init_r.json()["upload_id"]

        # Stub: skip actual PUT to GCS; complete immediately
        complete_r = await c.post(
            "/api/cas/uploads/complete",
            headers={"X-User-External-Id": external_id, "X-User-Pan": pan},
            json={"upload_id": upload_id},
        )
    assert complete_r.status_code == 200, complete_r.text
    body = complete_r.json()
    assert body["job_id"] == upload_id
    assert body["is_active"] is True
    assert body["status"] == "activated"
    assert body["raw_pdf_available"] is True
