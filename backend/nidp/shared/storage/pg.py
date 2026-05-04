"""NIDP Postgres connection.

Owns its own asyncpg pool so NIDP does not import the existing
backend.services.pg_client. Same DB host (NIDP_POSTGRES_URL or, as
fallback, POSTGRES_URL) but a separate pool — lets us tear down NIDP
cleanly without disturbing live services.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


def _resolve_url() -> Optional[str]:
    return (
        os.environ.get("NIDP_POSTGRES_URL")
        or os.environ.get("POSTGRES_URL")
        or "postgresql://postgres:postgres@localhost:5432/nivesh"
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    url = _resolve_url()
    _pool = await asyncpg.create_pool(
        url,
        min_size=1,
        max_size=4,
        command_timeout=30,
        statement_cache_size=0,
        server_settings={"search_path": "nidp,public"},
    )
    logger.info("NIDP pg pool initialized")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
