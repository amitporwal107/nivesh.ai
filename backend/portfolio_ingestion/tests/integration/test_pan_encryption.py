"""Integration tests for the pgcrypto PAN-encryption path (T2.3)."""
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

    external_id = f"enc-{uuid.uuid4()}"
    pan = "ENCRX" + uuid.uuid4().hex[:5].upper()      # 10 chars

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
async def test_sdk_callback_writes_encrypted_pan(fresh_user) -> None:
    """After the first POST, users.pan_enc is non-null."""
    app, external_id, pan = fresh_user
    body = {
        "checksum": uuid.uuid4().hex,
        "statement_from": "2026-01-01", "statement_to": "2026-01-31",
        "generated_at": "2026-02-01T00:00:00+00:00",
        "source_type": "ECAS_CDSL", "metadata": {"method": "upload"},
        "data": {
            "investor": {"pan": pan},
            "demat_accounts": [], "mutual_funds": [],
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id}, json=body,
        )
        assert r.status_code == 200, r.text

    from portfolio_ingestion.config import get_settings
    from portfolio_ingestion.services.checksum import pan_hash as _hash
    pool = await pg_pool.get_pool()
    async with pool.acquire() as conn, conn.transaction():
        # Same session key the app used when writing
        await conn.execute(
            "SELECT set_config('portfolio_ingestion.pan_encryption_key', $1, true)",
            get_settings().pan_encryption_key or "pi-placeholder-rotate-me",
        )
        row = await conn.fetchrow(
            "SELECT pan_enc IS NOT NULL AS has_enc, length(pan_enc) AS enc_len, "
            "       portfolio_ingestion.pi_decrypt_pan(pan_enc) AS plain "
            "  FROM portfolio_ingestion.users WHERE pan_hash = $1",
            _hash(pan),
        )
    assert row is not None
    assert row["has_enc"] is True
    assert row["enc_len"] > 0
    assert row["plain"] == pan


@pytest.mark.integration
async def test_decrypt_with_wrong_key_fails(fresh_user) -> None:
    """A wrong session key cannot decrypt the stored ciphertext.

    Proves the value is actually encrypted (not just stored as-is).
    """
    app, external_id, pan = fresh_user
    body = {
        "checksum": uuid.uuid4().hex,
        "statement_from": "2026-01-01", "statement_to": "2026-01-31",
        "generated_at": "2026-02-01T00:00:00+00:00",
        "source_type": "ECAS_CDSL", "metadata": {"method": "upload"},
        "data": {"investor": {"pan": pan}, "demat_accounts": [], "mutual_funds": []},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/cas/sdk-callback",
            headers={"X-User-External-Id": external_id}, json=body,
        )
        assert r.status_code == 200

    from portfolio_ingestion.services.checksum import pan_hash as _hash
    pool = await pg_pool.get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT set_config('portfolio_ingestion.pan_encryption_key', $1, true)",
            "totally-wrong-key",
        )
        # pgp_sym_decrypt with the wrong passphrase raises in pgcrypto.
        import asyncpg
        with pytest.raises(asyncpg.PostgresError):
            await conn.fetchval(
                "SELECT portfolio_ingestion.pi_decrypt_pan(pan_enc) "
                "FROM portfolio_ingestion.users WHERE pan_hash = $1",
                _hash(pan),
            )
