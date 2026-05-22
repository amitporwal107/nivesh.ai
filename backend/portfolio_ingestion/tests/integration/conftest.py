"""Integration-test fixtures.

These require a live Postgres reachable via ``PI_POSTGRES_URL``. The test
runner inside the staging container hits the running ``nivesh-staging-postgres``
service. Outside the container, set ``PI_POSTGRES_URL`` yourself or skip.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from portfolio_ingestion.config import reset_settings_for_test
from portfolio_ingestion.db import pool as pool_module


PI_POSTGRES_URL = os.environ.get("PI_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not PI_POSTGRES_URL,
    reason="PI_POSTGRES_URL not set; integration tests skipped",
)


@pytest_asyncio.fixture
async def pg_pool() -> AsyncIterator[asyncpg.Pool]:
    """Module-level asyncpg pool used by the snapshot engine."""
    reset_settings_for_test()
    pool_module.reset_pool_for_test()
    pool = await pool_module.get_pool()
    yield pool
    await pool_module.close_pool()
    pool_module.reset_pool_for_test()


@pytest_asyncio.fixture
async def clean_pan(pg_pool: asyncpg.Pool) -> AsyncIterator[tuple[str, uuid.UUID]]:
    """Yield a unique PAN hash + user_id, fully cleaned up after the test.

    Every test gets its own PAN so tests can run concurrently without
    stepping on each other.
    """
    pan_hash = uuid.uuid4().hex + uuid.uuid4().hex      # 64 chars
    external_id = f"itest-{uuid.uuid4()}"
    async with pg_pool.acquire() as conn:
        user_id = await conn.fetchval(
            """
            INSERT INTO portfolio_ingestion.users (external_id, pan_hash)
            VALUES ($1, $2) RETURNING id
            """,
            external_id, pan_hash,
        )
    try:
        yield pan_hash, user_id
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM portfolio_ingestion.holdings WHERE pan_hash = $1",
                pan_hash,
            )
            await conn.execute(
                "DELETE FROM portfolio_ingestion.snapshots WHERE pan_hash = $1",
                pan_hash,
            )
            await conn.execute(
                "DELETE FROM portfolio_ingestion.ingestion_jobs WHERE pan_hash = $1",
                pan_hash,
            )
            await conn.execute(
                "DELETE FROM portfolio_ingestion.users WHERE id = $1",
                user_id,
            )


async def _insert_job(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    pan_hash: str,
    source_type: str,
    method: str,
    checksum: str,
) -> uuid.UUID:
    return await conn.fetchval(
        """
        INSERT INTO portfolio_ingestion.ingestion_jobs
            (user_id, pan_hash, source_type, method, checksum, status)
        VALUES ($1, $2, $3, $4, $5, 'received')
        RETURNING id
        """,
        user_id, pan_hash, source_type, method, checksum,
    )
