"""Apply autodesk/db/migrations/*.sql in name order, each once, each in its own transaction.

Recorded in autodesk.schema_migrations (name, sha256). A file whose content changed after it was applied is refused
(never silently re-applied): add a new numbered file instead. A transaction-level advisory lock serialises two
service instances starting together.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_KEY = 0x0A07_0DE5  # arbitrary, stable


class MigrationDrift(RuntimeError):
    pass


async def apply_pending(pool: asyncpg.Pool) -> list[str]:
    applied_now: list[str] = []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
            await conn.execute("CREATE SCHEMA IF NOT EXISTS autodesk")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS autodesk.schema_migrations ("
                " name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
            done = {r["name"]: r["sha256"] for r in await conn.fetch("SELECT name, sha256 FROM autodesk.schema_migrations")}
            for f in files:
                sql = f.read_text()
                digest = hashlib.sha256(sql.encode()).hexdigest()
                if f.name in done:
                    if done[f.name] != digest:
                        raise MigrationDrift(f"{f.name} changed after it was applied; add a new migration instead")
                    continue
                await conn.execute(sql)
                await conn.execute("INSERT INTO autodesk.schema_migrations(name, sha256) VALUES ($1, $2)", f.name, digest)
                applied_now.append(f.name)
                log.info("autodesk migration applied: %s", f.name)
    return applied_now
