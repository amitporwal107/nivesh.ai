"""End-to-end test for POST /api/cas/sdk-callback.

Spins the FastAPI app in-process (TestClient), runs a real Postgres + Mongo
underneath (skipped if PI_POSTGRES_URL or PI_MONGO_URL is unset), and
exercises the full job → archive → builder → activation pipeline.
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
async def app_and_pan():
    """Build the FastAPI app + a unique external_id / pan to identify this test."""
    reset_settings_for_test()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()
    archive_mod.reset_indexes_cache_for_test()

    from portfolio_ingestion.main import create_app

    app = create_app()

    external_id = f"e2e-{uuid.uuid4()}"
    # Real PAN-like 10-char (uppercase letters + digits); deterministic per test
    pan = "TESTE" + uuid.uuid4().hex[:4].upper() + "F"  # 10 chars
    pan = pan[:10]  # safety

    yield app, external_id, pan

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


def _sample_payload(pan: str, *, checksum: str | None = "deadbeef") -> dict:
    return {
        "checksum": checksum,
        "statement_from": "2026-01-01",
        "statement_to": "2026-01-31",
        "generated_at": "2026-02-01T00:00:00+00:00",
        "source_type": "ECAS_CDSL",
        "metadata": {"method": "upload", "cas_type": "cdsl"},
        "data": {
            "investor": {"pan": pan, "name": "Test User"},
            "demat_accounts": [{
                "dp_id": "IN30001",
                "client_id": "ABCD",
                "holdings": [
                    {"isin": "INE002A01018", "name": "RELIANCE",
                     "quantity": "10", "value": "25000",
                     "instrument_type": "equity"},
                    {"isin": "INE090A01021", "name": "ICICI BANK",
                     "quantity": "5", "value": "5000",
                     "instrument_type": "equity"},
                ],
            }],
            # SDK shape: each mutual_funds[] entry is a folio (not an AMC
            # wrapper). The schema's legacy normaliser also accepts the
            # old {amc, folios:[{folio,schemes}]} dict shape, but writing
            # the modern flat shape directly keeps the test close to reality.
            "mutual_funds": [{
                "amc":           "HDFC",
                "folio_number":  "F-001",
                "schemes": [{
                    "scheme_code": "120503", "name": "HDFC Flexi Cap",
                    "units": "100", "value": "10000",
                }],
            }],
        },
    }


@pytest.mark.integration
async def test_sdk_callback_happy_path(app_and_pan) -> None:
    app, external_id, pan = app_and_pan
    body = _sample_payload(pan)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id},
            json=body,
        )

    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["is_new"] is True
    assert out["is_active"] is True
    assert out["status"] == "activated"
    assert uuid.UUID(out["job_id"])
    assert uuid.UUID(out["snapshot_id"])

    p = out["portfolio"]
    assert p["holdings_count"] == 3
    assert Decimal(p["total_value"]) == Decimal("40000.00")
    classes = {a["asset_class"] for a in p["allocation"]}
    assert classes == {"equity", "mutual_fund"}


@pytest.mark.integration
async def test_sdk_callback_idempotent_on_duplicate(app_and_pan) -> None:
    app, external_id, pan = app_and_pan
    body = _sample_payload(pan, checksum="dup-cs")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id}, json=body,
        )
        r2 = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id}, json=body,
        )
    assert r1.status_code == 200 and r2.status_code == 200
    j1, j2 = r1.json(), r2.json()
    assert j1["job_id"] == j2["job_id"]
    assert j1["snapshot_id"] == j2["snapshot_id"]
    assert j1["is_new"] is True and j2["is_new"] is False


@pytest.mark.integration
async def test_sdk_callback_rejects_missing_pan(app_and_pan) -> None:
    app, external_id, _ = app_and_pan
    body = _sample_payload("AAAAA1111A")
    # Strip PAN from investor block
    body["data"]["investor"].pop("pan")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id}, json=body,
        )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_sdk_callback_rejects_missing_source_type(app_and_pan) -> None:
    app, external_id, pan = app_and_pan
    body = _sample_payload(pan)
    body.pop("source_type")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id}, json=body,
        )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_sdk_callback_rejects_missing_header(app_and_pan) -> None:
    app, _, pan = app_and_pan
    body = _sample_payload(pan)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/cas/sdk-callback", json=body)
    assert resp.status_code == 422
    detail_text = resp.text.lower()
    assert "x-user-external-id" in detail_text or "header" in detail_text


@pytest.mark.integration
async def test_sdk_callback_pan_mismatch_returns_403(app_and_pan) -> None:
    app, external_id, pan = app_and_pan
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First call establishes user → pan mapping
        r1 = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id},
            json=_sample_payload(pan, checksum="cs-a"),
        )
        assert r1.status_code == 200
        # Second call: same external_id, different PAN → 403
        other_pan = "OTHRX" + uuid.uuid4().hex[:4].upper() + "F"
        other_pan = other_pan[:10]
        r2 = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id},
            json=_sample_payload(other_pan, checksum="cs-b"),
        )
        assert r2.status_code == 403
        # Cleanup the second PAN's user row if it got created
        panh_other = uuid.uuid4().hex
        try:
            from portfolio_ingestion.services.checksum import pan_hash as _hash
            pool = await pg_pool.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM portfolio_ingestion.users WHERE pan_hash = $1",
                    _hash(other_pan),
                )
        except Exception:
            pass
