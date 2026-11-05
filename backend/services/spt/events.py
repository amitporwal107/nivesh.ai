"""The SPT event log (Workflow §22): one append-only document per business fact, in `spt_events`.

Envelope: {event_id, event_type, event_version, occurred_at, ingested_at, correlation_id, account_id, instrument_id,
source_service, idempotency_key, payload}. `idempotency_key` is stable per fact (for example "order:<id>:filled:<seq>"),
so a replay or a second worker inserts nothing new: the insert hits the unique index and `emit` reports a duplicate.
`instrument_id` is the NSE symbol for now (there is no instrument master id in the app yet).

`emit` never raises into the caller's business write: the business document is the system of record and the event is
its log. A failed insert is logged with its type and reported in the return value, so a caller that must not proceed
without the event (none tonight) can check it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import constants as C

logger = logging.getLogger(__name__)

_indexed = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db) -> None:
    global _indexed
    if _indexed:
        return
    await db[C.EVENTS].create_index("idempotency_key", unique=True)
    await db[C.EVENTS].create_index([("account_id", 1), ("occurred_at", -1)])
    await db[C.EVENTS].create_index([("correlation_id", 1)])
    await db[C.EVENTS].create_index([("event_type", 1), ("occurred_at", -1)])
    _indexed = True


def envelope(event_type: str, *, idempotency_key: str, source_service: str, payload: Dict[str, Any],
             occurred_at: Optional[str] = None, correlation_id: Optional[str] = None, account_id: Optional[str] = None,
             instrument_id: Optional[str] = None) -> Dict[str, Any]:
    """The event document. ValueError for an unknown type or an empty key (a programming error, not a data error)."""
    if event_type not in C.EVENT_TYPES:
        raise ValueError(f"unknown event type {event_type!r}")
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    eid = str(uuid.uuid4())
    return {"_id": eid, "event_id": eid, "event_type": event_type, "event_version": C.EVENT_VERSION,
            "occurred_at": occurred_at or now_iso(), "ingested_at": now_iso(), "correlation_id": correlation_id or eid,
            "account_id": account_id, "instrument_id": instrument_id, "source_service": source_service,
            "idempotency_key": idempotency_key, "payload": payload}


async def emit(db, event_type: str, *, idempotency_key: str, source_service: str, payload: Dict[str, Any],
               occurred_at: Optional[str] = None, correlation_id: Optional[str] = None, account_id: Optional[str] = None,
               instrument_id: Optional[str] = None) -> Dict[str, Any]:
    """Append one event. Returns {"stored": True, "event_id"} or {"stored": False, "duplicate": bool, "error": str|None}."""
    doc = envelope(event_type, idempotency_key=idempotency_key, source_service=source_service, payload=payload,
                   occurred_at=occurred_at, correlation_id=correlation_id, account_id=account_id,
                   instrument_id=instrument_id)
    try:
        await ensure_indexes(db)
        await db[C.EVENTS].insert_one(doc)
        return {"stored": True, "event_id": doc["event_id"]}
    except Exception as e:  # noqa: BLE001 — the business write stands; the log says why its event is missing
        dup = type(e).__name__ == "DuplicateKeyError" or "duplicate key" in str(e).lower()
        if not dup:
            logger.warning("spt events: %s not stored (%s)", event_type, type(e).__name__)
        return {"stored": False, "duplicate": dup, "error": None if dup else type(e).__name__}
