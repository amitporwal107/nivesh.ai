"""Raw ParsedData archive in MongoDB.

Writes one document per ingestion job into ``pi_raw_parsed_data`` so we can
re-build the portfolio from the original SDK payload at any point (PRD
§10.2 — explainability + replay).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any
from uuid import UUID

from ..clients.mongo import get_database

log = logging.getLogger(__name__)

COLLECTION = "pi_raw_parsed_data"

_indexes_ensured = False


async def _ensure_indexes() -> None:
    """Idempotently create our two indexes the first time we write."""
    global _indexes_ensured
    if _indexes_ensured:
        return
    db = await get_database()
    coll = db[COLLECTION]
    await coll.create_index("ingestion_job_id", unique=True, name="ingestion_job_id_uniq")
    await coll.create_index(
        [("pan_hash", 1), ("received_at", -1)], name="pan_received_desc"
    )
    _indexes_ensured = True


def _jsonable(value: Any) -> Any:
    """Recursively coerce Decimals / dates to JSON-safe types.

    BSON natively supports Decimal128 but Pydantic Decimals don't serialise
    cleanly without a custom encoder; ``json.loads(json.dumps(..., default=str))``
    is a small, predictable normalisation that keeps the archive pure JSON.
    """
    return json.loads(json.dumps(value, default=str))


async def archive(
    *,
    ingestion_job_id: UUID,
    pan_hash: str,
    source_type: str,
    sdk_metadata: dict[str, Any],
    parsed_data: dict[str, Any] | Any,        # accepts dict or Pydantic model
) -> str:
    """Insert (or upsert) the raw payload. Returns the Mongo ``_id`` as string."""
    await _ensure_indexes()
    db = await get_database()
    coll = db[COLLECTION]

    # Pydantic model → dict
    if hasattr(parsed_data, "model_dump"):
        parsed_data = parsed_data.model_dump(mode="json")

    doc = {
        "ingestion_job_id": str(ingestion_job_id),
        "pan_hash": pan_hash,
        "source_type": source_type,
        "received_at": dt.datetime.now(dt.timezone.utc),
        "sdk_metadata": _jsonable(sdk_metadata),
        "parsed_data": _jsonable(parsed_data),
    }

    # Upsert by ingestion_job_id so replays are idempotent.
    result = await coll.update_one(
        {"ingestion_job_id": doc["ingestion_job_id"]},
        {"$set": doc},
        upsert=True,
    )
    if result.upserted_id is not None:
        log.info(
            "parsed_data archived (insert)",
            extra={
                "eventType": "PARSED_DATA_ARCHIVE",
                "ingestion_job_id": doc["ingestion_job_id"],
                "operation": "insert",
            },
        )
        return str(result.upserted_id)

    # Update path — fetch the doc to return its _id.
    existing = await coll.find_one(
        {"ingestion_job_id": doc["ingestion_job_id"]}, projection={"_id": 1}
    )
    log.info(
        "parsed_data archived (update)",
        extra={
            "eventType": "PARSED_DATA_ARCHIVE",
            "ingestion_job_id": doc["ingestion_job_id"],
            "operation": "update",
        },
    )
    return str(existing["_id"]) if existing else ""


async def fetch(ingestion_job_id: UUID) -> dict[str, Any] | None:
    db = await get_database()
    coll = db[COLLECTION]
    doc = await coll.find_one({"ingestion_job_id": str(ingestion_job_id)})
    return doc


def reset_indexes_cache_for_test() -> None:
    global _indexes_ensured
    _indexes_ensured = False
