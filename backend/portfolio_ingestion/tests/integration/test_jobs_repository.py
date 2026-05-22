"""Integration tests for the ingestion-jobs repository (idempotency)."""
from __future__ import annotations

import uuid

import asyncpg
import pytest

from portfolio_ingestion.db.repositories import jobs


# ── AC1 + AC2: same (pan_hash, checksum) → same id, is_new=False ──────────


@pytest.mark.integration
async def test_upsert_returns_is_new_true_on_first_call(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        job_id, is_new = await jobs.upsert(
            conn,
            user_id=user_id, pan_hash=pan_hash,
            source_type="ECAS_CDSL", method="upload", checksum="c1",
        )
    assert is_new is True
    assert isinstance(job_id, uuid.UUID)


@pytest.mark.integration
async def test_upsert_second_call_with_same_checksum_returns_existing_id(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        first_id, first_new = await jobs.upsert(
            conn,
            user_id=user_id, pan_hash=pan_hash,
            source_type="ECAS_CDSL", method="upload", checksum="dup",
        )
        second_id, second_new = await jobs.upsert(
            conn,
            user_id=user_id, pan_hash=pan_hash,
            source_type="ECAS_CDSL", method="upload", checksum="dup",
        )
    assert first_new is True
    assert second_new is False
    assert first_id == second_id

    async with pg_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM portfolio_ingestion.ingestion_jobs "
            "WHERE pan_hash=$1 AND checksum=$2",
            pan_hash, "dup",
        )
    assert count == 1


# ── AC3: null checksum (cdsl_fetch) → every call is a new row ─────────────


@pytest.mark.integration
async def test_upsert_null_checksum_creates_new_row_every_time(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        a_id, a_new = await jobs.upsert(
            conn,
            user_id=user_id, pan_hash=pan_hash,
            source_type="ECAS_CDSL", method="cdsl_fetch", checksum=None,
        )
        b_id, b_new = await jobs.upsert(
            conn,
            user_id=user_id, pan_hash=pan_hash,
            source_type="ECAS_CDSL", method="cdsl_fetch", checksum=None,
        )
    assert a_new is True and b_new is True
    assert a_id != b_id


# ── get + mark round-trip ─────────────────────────────────────────────────


@pytest.mark.integration
async def test_get_and_mark_terminal_state(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        job_id, _ = await jobs.upsert(
            conn,
            user_id=user_id, pan_hash=pan_hash,
            source_type="ECAS_CDSL", method="upload", checksum="cg",
        )
        await jobs.mark(conn, job_id, status="activated",
                        raw_data_ref="mongo:abc123")
        fetched = await jobs.get(conn, job_id)

    assert fetched is not None
    assert fetched.status == "activated"
    assert fetched.raw_data_ref == "mongo:abc123"
    assert fetched.completed_at is not None


@pytest.mark.integration
async def test_mark_rejects_unknown_status(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash, user_id = clean_pan
    async with pg_pool.acquire() as conn:
        job_id, _ = await jobs.upsert(
            conn,
            user_id=user_id, pan_hash=pan_hash,
            source_type="ECAS_CDSL", method="upload", checksum="cz",
        )
    with pytest.raises(ValueError, match="Invalid status"):
        async with pg_pool.acquire() as conn:
            await jobs.mark(conn, job_id, status="bogus")


# ── Two PANs with same checksum should both be allowed ────────────────────


@pytest.mark.integration
async def test_same_checksum_different_pan_is_not_duplicate(
    pg_pool: asyncpg.Pool, clean_pan: tuple[str, uuid.UUID]
) -> None:
    pan_hash_a, user_a = clean_pan
    # Create a second user with a different pan_hash but reuse the checksum.
    pan_hash_b = uuid.uuid4().hex + uuid.uuid4().hex
    async with pg_pool.acquire() as conn:
        user_b = await conn.fetchval(
            "INSERT INTO portfolio_ingestion.users (external_id, pan_hash) "
            "VALUES ($1, $2) RETURNING id",
            f"itest-{uuid.uuid4()}", pan_hash_b,
        )
    try:
        async with pg_pool.acquire() as conn:
            a, a_new = await jobs.upsert(
                conn, user_id=user_a, pan_hash=pan_hash_a,
                source_type="ECAS_CDSL", method="upload", checksum="shared",
            )
            b, b_new = await jobs.upsert(
                conn, user_id=user_b, pan_hash=pan_hash_b,
                source_type="ECAS_CDSL", method="upload", checksum="shared",
            )
        assert a_new is True and b_new is True
        assert a != b
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM portfolio_ingestion.ingestion_jobs WHERE pan_hash = $1",
                pan_hash_b,
            )
            await conn.execute(
                "DELETE FROM portfolio_ingestion.users WHERE id = $1", user_b,
            )
