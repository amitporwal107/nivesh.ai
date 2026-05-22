"""Asyncpg connection pool, lifespan-managed by the FastAPI app.

The pool is opened lazily on first acquire (so the migration runner can use
this module without standing up the FastAPI process) and closed by the app's
shutdown hook.

Sizing follows PRD §12.1: a small per-instance pool (default max=4) so that
N container instances × pool_size stays under Postgres ``max_connections``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg  # for type checking only

from ..config import Settings, get_settings

log = logging.getLogger(__name__)

_pool: "asyncpg.Pool | None" = None
_pool_lock = asyncio.Lock()


async def get_pool(settings: Settings | None = None) -> "asyncpg.Pool":
    """Return a process-wide asyncpg pool, opening it on first call."""
    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is not None:
            return _pool

        import asyncpg  # local import keeps cold start cheap

        s = settings or get_settings()
        if not s.postgres_url:
            raise RuntimeError(
                "PI_POSTGRES_URL is not set; cannot open Postgres pool."
            )

        _pool = await asyncpg.create_pool(
            dsn=s.postgres_url,
            min_size=1,
            max_size=4,
            command_timeout=15,
            server_settings={"application_name": s.service_name},
        )
        log.info(
            "postgres pool opened",
            extra={"eventType": "DB_POOL_OPEN", "pool_max": 4},
        )
        return _pool


async def close_pool() -> None:
    """Close the pool on app shutdown."""
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None
    log.info("postgres pool closed", extra={"eventType": "DB_POOL_CLOSE"})


def reset_pool_for_test() -> None:
    """Drop the module-level reference (used by tests + migration runner CLI)."""
    global _pool
    _pool = None
