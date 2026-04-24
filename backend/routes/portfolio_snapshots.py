"""Portfolio Time-Machine API.

Exposes the snapshot engine to the frontend:
  - GET  /api/portfolio/snapshots          → available snapshot dates
  - GET  /api/portfolio/snapshot            → latest or by ?date=YYYY-MM-DD
  - GET  /api/portfolio/trend               → sparkline series
  - GET  /api/portfolio/compare             → diff two snapshot dates
  - POST /api/portfolio/snapshot            → manual snapshot trigger (advisor-only nicety)
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deps import get_current_user
from services import portfolio_snapshot as _snap

router = APIRouter(prefix="/api/portfolio", tags=["snapshots"])


@router.get("/snapshots")
async def list_dates(request: Request, limit: int = 365):
    user = await get_current_user(request)
    uid = user["user_id"]
    dates = await _snap.list_snapshot_dates(uid, limit=limit)
    return {"count": len(dates), "dates": dates}


@router.get("/snapshot")
async def get_snapshot(request: Request, date: Optional[str] = None):
    """If `date` omitted → latest snapshot. If given → that exact date,
    else the closest earlier snapshot (for timeline scrubbing)."""
    user = await get_current_user(request)
    uid = user["user_id"]
    if date:
        doc = (
            await _snap.get_snapshot(uid, date)
            or await _snap.get_snapshot_on_or_before(uid, date)
        )
    else:
        doc = await _snap.get_latest_snapshot(uid)
    if not doc:
        raise HTTPException(404, "No snapshots yet — upload a CAS or run a manual snapshot")
    return doc


@router.get("/trend")
async def trend(request: Request, days: int = 30):
    user = await get_current_user(request)
    uid = user["user_id"]
    series = await _snap.build_trend_series(uid, days=days)
    return {"days": days, "count": len(series), "series": series}


@router.get("/compare")
async def compare(request: Request, to: Optional[str] = None, from_: Optional[str] = None):
    """?to=YYYY-MM-DD&from=YYYY-MM-DD. Defaults: to=latest, from=2nd latest.
    (FastAPI aliases 'from_' because `from` is a Python keyword — frontend
    passes `from`.)"""
    user = await get_current_user(request)
    uid = user["user_id"]
    # Accept both `from` and `from_` query params
    raw_from = request.query_params.get("from") or from_

    if to:
        new_snap = await _snap.get_snapshot(uid, to) or await _snap.get_snapshot_on_or_before(uid, to)
    else:
        new_snap = await _snap.get_latest_snapshot(uid)

    if not new_snap:
        raise HTTPException(404, "No snapshots yet")

    if raw_from:
        old_snap = await _snap.get_snapshot(uid, raw_from) or await _snap.get_snapshot_on_or_before(uid, raw_from)
    else:
        # Default = most recent snapshot BEFORE the `to` one
        dates = await _snap.list_snapshot_dates(uid, limit=10)
        older = [d for d in dates if d < new_snap["snapshot_date"]]
        old_snap = await _snap.get_snapshot(uid, older[0]) if older else None

    diff = _snap.diff_snapshots(new_snap, old_snap)
    return {
        "new": new_snap,
        "old": old_snap,
        "diff": diff,
    }


class ManualSnapshotRequest(BaseModel):
    trigger: str = Field(default="manual", max_length=32)


@router.post("/snapshot")
async def manual_snapshot(payload: ManualSnapshotRequest, request: Request):
    """Advisor-triggered snapshot. Overwrites today's snapshot if
    one already exists."""
    user = await get_current_user(request)
    uid = user["user_id"]
    doc = await _snap.persist_snapshot(uid, trigger=payload.trigger or "manual")
    return {"snapshot": doc, "persisted": doc.get("holdings_count", 0) > 0}
