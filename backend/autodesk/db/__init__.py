"""Postgres access for the `autodesk` schema: its own asyncpg pool (separate from services.pg_client), the migration
runner, and JSON/Decimal codecs."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

import asyncpg


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def dumps(v: Any) -> str:
    return json.dumps(v, default=_default, separators=(",", ":"), sort_keys=True)


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=dumps, decoder=json.loads, schema="pg_catalog")


_pool: Optional[asyncpg.Pool] = None


async def open_pool(url: str, *, min_size: int = 1, max_size: int = 8) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not url:
            raise RuntimeError("AUTODESK_PG_URL / POSTGRES_URL is not set")
        _pool = await asyncpg.create_pool(url, min_size=min_size, max_size=max_size, init=_init_conn,
                                          statement_cache_size=0, command_timeout=30)
    return _pool


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("autodesk pool is not open")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def set_pool(p: Optional[asyncpg.Pool]) -> None:
    """Tests inject their own pool."""
    global _pool
    _pool = p


async def create_pool_for(url: str) -> asyncpg.Pool:
    """A fresh pool with the autodesk codecs (tests, scripts)."""
    return await asyncpg.create_pool(url, min_size=1, max_size=4, init=_init_conn, statement_cache_size=0)
