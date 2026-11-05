"""Fixtures for the Autonomous Trading Desk tests.

Database tests need AUTODESK_TEST_PG_URL: a THROWAWAY Postgres (never the shared staging one). Each test module gets
its own fresh database created from that server and dropped afterwards. Without the variable, DB tests are skipped
(pure unit tests still run). See scripts/run_autodesk_tests.sh for the container recipe.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import urlparse, urlunparse

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "autodesk_unit_test")
os.environ.setdefault("OPENAI_API_KEY", "unit-test-placeholder")

PG_URL = os.environ.get("AUTODESK_TEST_PG_URL", "")


def run(coro):
    """Run a coroutine on the module's loop (the repo's tests do not use pytest-asyncio)."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def loop():
    lp = asyncio.new_event_loop()
    asyncio.set_event_loop(lp)
    yield lp
    lp.close()


def _with_db(url: str, db: str) -> str:
    u = urlparse(url)
    return urlunparse(u._replace(path="/" + db))


@pytest.fixture(scope="module")
def pg_dsn(loop):
    """DSN of a fresh database (dropped after the module)."""
    if not PG_URL:
        pytest.skip("AUTODESK_TEST_PG_URL not set (throwaway Postgres needed)")
    import asyncpg
    name = "adt_" + uuid.uuid4().hex[:12]

    async def mk():
        admin = await asyncpg.connect(PG_URL)
        await admin.execute(f'CREATE DATABASE "{name}"')
        await admin.close()

    loop.run_until_complete(mk())
    yield _with_db(PG_URL, name)

    async def rm():
        admin = await asyncpg.connect(PG_URL)
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()

    loop.run_until_complete(rm())


@pytest.fixture(scope="module")
def pg_pool(loop, pg_dsn):
    """A pool on the module's fresh database with the autodesk schema applied."""
    from autodesk.db import create_pool_for, set_pool
    from autodesk.db.migrate import apply_pending

    async def setup():
        pool = await create_pool_for(pg_dsn)
        await apply_pending(pool)
        return pool

    pool = loop.run_until_complete(setup())
    set_pool(pool)
    yield pool
    set_pool(None)
    loop.run_until_complete(pool.close())
