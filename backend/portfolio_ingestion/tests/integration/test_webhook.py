"""Integration tests for the inbound-email webhook (T3.3)."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
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

_WEBHOOK_SECRET = "test-webhook-secret-integration"


def _sig(body: bytes) -> str:
    t = int(time.time())
    payload = f"{t}.".encode() + body
    mac = hmac.new(key=_WEBHOOK_SECRET.encode(), msg=payload, digestmod=hashlib.sha256)
    return f"t={t},v1={mac.hexdigest()}"


@pytest_asyncio.fixture
async def webhook_app():
    reset_settings_for_test()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()
    archive_mod.reset_indexes_cache_for_test()

    os.environ["PI_WEBHOOK_ENABLED"] = "true"
    os.environ["PI_WEBHOOK_SECRET"] = _WEBHOOK_SECRET
    os.environ.setdefault("PI_GCS_STUB", "true")

    from portfolio_ingestion.main import create_app
    app = create_app()

    external_id = f"wh-{uuid.uuid4()}"
    pan = "WBHKX" + uuid.uuid4().hex[:5].upper()

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

    os.environ.pop("PI_WEBHOOK_ENABLED", None)
    os.environ.pop("PI_WEBHOOK_SECRET", None)

    await pg_pool.close_pool()
    await mongo_client.close_client()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()


@pytest.mark.integration
async def test_webhook_disabled_returns_404():
    reset_settings_for_test()
    os.environ.pop("PI_WEBHOOK_ENABLED", None)
    from portfolio_ingestion.main import create_app
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/webhooks/casparser/inbound-email", json={})
    assert r.status_code == 404
    reset_settings_for_test()


@pytest.mark.integration
async def test_webhook_invalid_signature_returns_401(webhook_app):
    app, external_id, pan = webhook_app
    import json
    body = json.dumps({"external_id": external_id, "pan": pan, "source_type": "MF_CAMS"}).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/webhooks/casparser/inbound-email",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Casparser-Signature": "t=1234567890,v1=badhex",
            },
        )
    assert r.status_code == 401


@pytest.mark.integration
async def test_webhook_valid_activates_snapshot(webhook_app):
    app, external_id, pan = webhook_app
    import json
    body_dict = {
        "external_id": external_id,
        "pan": pan,
        "source_type": "MF_CAMS",
        "pdf_url": None,
    }
    body = json.dumps(body_dict).encode()
    sig = _sig(body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/webhooks/casparser/inbound-email",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Casparser-Signature": sig,
            },
        )
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["is_active"] is True
    assert resp["status"] == "activated"
    assert "job_id" in resp
    assert "snapshot_id" in resp
