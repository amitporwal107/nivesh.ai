"""Motor (async MongoDB) client wrapper for the raw ParsedData archive.

The new service writes to one collection only: ``pi_raw_parsed_data`` inside
the database named in the connection URL. We keep the client and database
references as module-level singletons opened on first use.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from ..config import Settings, get_settings

log = logging.getLogger(__name__)

_client: "AsyncIOMotorClient | None" = None
_lock = asyncio.Lock()


async def get_database(settings: Settings | None = None) -> "AsyncIOMotorDatabase":
    """Return the configured Motor database; open the client on first call."""
    global _client
    if _client is not None:
        return _client.get_default_database()

    async with _lock:
        if _client is not None:
            return _client.get_default_database()

        from motor.motor_asyncio import AsyncIOMotorClient

        s = settings or get_settings()
        if not s.mongo_url:
            raise RuntimeError("PI_MONGO_URL is not set; cannot open Mongo client.")

        _client = AsyncIOMotorClient(
            s.mongo_url,
            tz_aware=True,
            appname=s.service_name,
            serverSelectionTimeoutMS=5_000,
        )
        log.info("mongo client opened", extra={"eventType": "MONGO_OPEN"})
        return _client.get_default_database()


async def close_client() -> None:
    """Close the client on app shutdown."""
    global _client
    if _client is None:
        return
    _client.close()
    _client = None
    log.info("mongo client closed", extra={"eventType": "MONGO_CLOSE"})


def reset_client_for_test() -> None:
    global _client
    _client = None
