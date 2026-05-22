"""Integration tests for the audit_log table (T2.4)."""
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


@pytest_asyncio.fixture
async def fresh_user():
    reset_settings_for_test()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()
    archive_mod.reset_indexes_cache_for_test()

    from portfolio_ingestion.main import create_app
    app = create_app()

    external_id = f"audit-{uuid.uuid4()}"
    pan = "AUDIT" + uuid.uuid4().hex[:5].upper()  # 10 chars

    yield app, external_id, pan

    from portfolio_ingestion.services.checksum import pan_hash as _hash
    panh = _hash(pan)
    pool = await pg_pool.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM portfolio_ingestion.audit_log WHERE pan_hash = $1", panh
        )
        await conn.execute(
            "DELETE FROM portfolio_ingestion.holdings WHERE pan_hash=$1", panh
        )
        await conn.execute(
            "DELETE FROM portfolio_ingestion.snapshots WHERE pan_hash=$1", panh
        )
        await conn.execute(
            "DELETE FROM portfolio_ingestion.ingestion_jobs WHERE pan_hash=$1", panh
        )
        await conn.execute(
            "DELETE FROM portfolio_ingestion.users WHERE pan_hash=$1", panh
        )
    db = await mongo_client.get_database()
    await db[archive_mod.COLLECTION].delete_many({"pan_hash": panh})
    await pg_pool.close_pool()
    await mongo_client.close_client()
    pg_pool.reset_pool_for_test()
    mongo_client.reset_client_for_test()


def _body(pan: str, checksum: str | None = None) -> dict:
    return {
        "checksum": checksum or uuid.uuid4().hex,
        "statement_from": "2026-01-01",
        "statement_to": "2026-01-31",
        "generated_at": "2026-02-01T00:00:00+00:00",
        "source_type": "ECAS_CDSL",
        "metadata": {"method": "upload"},
        "data": {
            "investor": {"pan": pan},
            "demat_accounts": [],
            "mutual_funds": [],
        },
    }


@pytest.mark.integration
async def test_sdk_callback_writes_audit_entries(fresh_user) -> None:
    """A complete sdk-callback POST leaves USER_CREATED, JOB_STATUS (*3), and
    SNAPSHOT_ACTIVATED rows in audit_log."""
    app, external_id, pan = fresh_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id},
            json=_body(pan),
        )
    assert r.status_code == 200, r.text

    from portfolio_ingestion.services.checksum import pan_hash as _hash
    panh = _hash(pan)
    pool = await pg_pool.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_type, entity_type FROM portfolio_ingestion.audit_log "
            "WHERE pan_hash = $1 ORDER BY occurred_at",
            panh,
        )

    event_types = [r["event_type"] for r in rows]
    assert "USER_CREATED" in event_types
    assert "SNAPSHOT_ACTIVATED" in event_types
    job_status_events = [e for e in event_types if e == "JOB_STATUS"]
    assert len(job_status_events) == 3, f"Expected 3 JOB_STATUS events, got: {event_types}"


@pytest.mark.integration
async def test_audit_log_is_immutable(fresh_user) -> None:
    """UPDATE and DELETE on audit_log raise a Postgres error."""
    app, external_id, pan = fresh_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id},
            json=_body(pan),
        )
    assert r.status_code == 200

    from portfolio_ingestion.services.checksum import pan_hash as _hash
    import asyncpg
    panh = _hash(pan)
    pool = await pg_pool.get_pool()
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                "UPDATE portfolio_ingestion.audit_log SET actor = 'tampered' "
                "WHERE pan_hash = $1",
                panh,
            )
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                "DELETE FROM portfolio_ingestion.audit_log WHERE pan_hash = $1",
                panh,
            )


@pytest.mark.integration
async def test_audit_job_status_transitions(fresh_user) -> None:
    """JOB_STATUS entries follow received → parsing → activated in order."""
    app, external_id, pan = fresh_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id},
            json=_body(pan),
        )
    assert r.status_code == 200

    from portfolio_ingestion.services.checksum import pan_hash as _hash
    panh = _hash(pan)
    pool = await pg_pool.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT payload FROM portfolio_ingestion.audit_log "
            "WHERE pan_hash = $1 AND event_type = 'JOB_STATUS' "
            "ORDER BY occurred_at",
            panh,
        )
    import json
    transitions = [json.loads(r["payload"]) for r in rows]
    assert transitions[0]["from"] is None
    assert transitions[0]["to"] == "received"
    assert transitions[1]["from"] == "received"
    assert transitions[1]["to"] == "parsing"
    assert transitions[2]["from"] == "parsing"
    assert transitions[2]["to"] == "activated"
