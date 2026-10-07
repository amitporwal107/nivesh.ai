"""Machine-to-machine ingest of corporate-event AI analyses into Mongo.

Background jobs on nidp-stack-vm run the owner's Corporate Event AI Impact Analysis prompt over
exchange filings (research/event_direction/ai_analysis/) and POST the results here. The backend
already holds the Mongo connection, so the jobs need no database credentials, no ssh and no
user-scoped GCP token.

Auth: shared-secret header X-Event-AI-Key matched (constant time) against the EVENT_AI_INGEST_KEY
secret (DB-first via helpers.secrets, env fallback). Unset secret => 503, never an open write path.

Writes are idempotent upserts keyed on the caller's `_id`
("<source>:<announcement_id>:<prompt_sha12>:<model_tag>"), so re-sending a batch is safe and a new
prompt version or model sits beside the old one.
"""
from __future__ import annotations

import hmac
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReplaceOne

from deps import db
from helpers import secrets as _secrets

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/internal/event-ai-analysis", tags=["event-ai"])

COLLECTION = "event_ai_analysis"
MAX_DOCS = 200
REQUIRED = ("_id", "announcement_id", "source", "prompt_sha256")
DATE_FIELDS = ("event_ts", "analyzed_at")
_indexes_ready = False


class BulkBody(BaseModel):
    docs: List[Dict[str, Any]] = Field(..., min_length=1, max_length=MAX_DOCS)


def _authorize(provided: Optional[str]) -> None:
    expected = _secrets.get("EVENT_AI_INGEST_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="event AI ingest disabled (EVENT_AI_INGEST_KEY not set)")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid ingest key")


def _parse_date(v: Any) -> Any:
    """Accept an ISO string or Mongo extended JSON {"$date": iso}; store a real datetime."""
    if isinstance(v, dict) and "$date" in v:
        v = v["$date"]
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return v


def normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one analysis document and convert its date fields. Raises ValueError."""
    missing = [k for k in REQUIRED if not doc.get(k)]
    if missing:
        raise ValueError(f"missing {missing}")
    if not isinstance(doc["_id"], str) or len(doc["_id"]) > 300:
        raise ValueError("_id must be a string <= 300 chars")
    if any(k.startswith("$") for k in doc):
        raise ValueError("top-level keys may not start with $")
    out = dict(doc)
    for k in DATE_FIELDS:
        if k in out and out[k] is not None:
            try:
                out[k] = _parse_date(out[k])
            except ValueError as e:
                raise ValueError(f"{k}: {e}") from e
    return out


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    col = db[COLLECTION]
    await col.create_index([("symbol", 1), ("event_ts", -1)])
    await col.create_index([("event_type", 1), ("event_ts", -1)])
    await col.create_index([("exchange_category", 1)])
    await col.create_index([("prompt_sha256", 1)])
    _indexes_ready = True


@router.post("/bulk")
async def bulk_upsert(body: BulkBody, x_event_ai_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _authorize(x_event_ai_key)
    ops, rejected = [], []
    for i, d in enumerate(body.docs):
        try:
            n = normalize(d)
            ops.append(ReplaceOne({"_id": n["_id"]}, n, upsert=True))
        except ValueError as e:
            rejected.append({"index": i, "_id": d.get("_id"), "reason": str(e)})
    written = {"upserted": 0, "modified": 0, "matched": 0}
    if ops:
        await _ensure_indexes()
        res = await db[COLLECTION].bulk_write(ops, ordered=False)
        written = {"upserted": res.upserted_count, "modified": res.modified_count, "matched": res.matched_count}
    logger.info("event-ai ingest: received=%d written=%s rejected=%d", len(body.docs), written, len(rejected))
    return {"ok": not rejected, "received": len(body.docs), **written, "rejected": rejected}


@router.get("/stats")
async def stats(x_event_ai_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Counts by mode / model / net band — lets the caller verify what landed."""
    _authorize(x_event_ai_key)
    col = db[COLLECTION]
    groups = await col.aggregate([
        {"$group": {"_id": {"mode": "$mode", "model": "$model_tag", "band": "$net_band"}, "n": {"$sum": 1}}},
        {"$sort": {"_id.mode": 1, "_id.model": 1, "_id.band": 1}},
    ]).to_list(500)
    return {"total": await col.count_documents({}), "groups": [{**g["_id"], "n": g["n"]} for g in groups]}
