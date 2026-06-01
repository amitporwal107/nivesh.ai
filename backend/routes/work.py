"""
/api/work/ — Issues dashboard backend.

Persists error clusters (from Cloud Logging + diagnostic tool) to the
`work_issues` MongoDB collection and exposes CRUD + stats for the
work.niveshcopilot.com dashboard.

Auth: all routes require admin.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from deps import db, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/work", tags=["work"])

_COLLECTION = "work_issues"

# ── Pydantic models ──────────────────────────────────────────────────────────

class RcaBlock(BaseModel):
    root_cause: str = ""
    fix_suggestion: str = ""
    confidence: float = 0.0
    source: str = "unknown"          # "openai" | "claude" | "heuristic"
    fix_file: Optional[str] = None
    fix_description: Optional[str] = None


class IssueCreate(BaseModel):
    sig: str
    title: str
    severity: str = "ERROR"          # CRITICAL / ERROR / WARNING
    priority: str = "P2"             # P1 / P2 / P3
    source: str = "cloud_logging"    # cloud_logging | diagnostic_tool | manual
    exception_class: str = ""
    endpoint: str = ""
    job_name: str = ""
    http_status: Optional[int] = None
    sample_message: str = ""
    sample_traceback: str = ""
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    count_24h: int = 1
    applications: list[str] = Field(default_factory=list)
    rca: Optional[RcaBlock] = None
    labels: list[str] = Field(default_factory=list)


class IssueUpdate(BaseModel):
    status: Optional[str] = None     # open | in_progress | resolved | wont_fix
    priority: Optional[str] = None
    assignee: Optional[str] = None
    labels: Optional[list[str]] = None
    rca: Optional[RcaBlock] = None
    comment: Optional[str] = None    # appends to comments list


# ── Helpers ──────────────────────────────────────────────────────────────────

def _severity_to_priority(severity: str) -> str:
    return {"CRITICAL": "P1", "ERROR": "P2", "WARNING": "P3"}.get(severity.upper(), "P2")


def _serialize(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    # Convert datetime to ISO string for JSON
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/issues")
async def list_issues(
    request: Request,
    status: Optional[str] = Query(None, description="open|in_progress|resolved|wont_fix"),
    priority: Optional[str] = Query(None, description="P1|P2|P3"),
    source: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    await require_admin(request)
    flt: dict[str, Any] = {}
    if status:
        flt["status"] = status
    if priority:
        flt["priority"] = priority
    if source:
        flt["source"] = source
    if label:
        flt["labels"] = label

    cursor = db[_COLLECTION].find(flt, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit)
    docs = await cursor.to_list(limit)
    total = await db[_COLLECTION].count_documents(flt)
    return {"issues": [_serialize(d) for d in docs], "total": total, "offset": offset, "limit": limit}


@router.get("/issues/{issue_id}")
async def get_issue(request: Request, issue_id: str):
    await require_admin(request)
    doc = await db[_COLLECTION].find_one({"issue_id": issue_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _serialize(doc)


@router.post("/issues", status_code=201)
async def create_issue(request: Request, body: IssueCreate):
    await require_admin(request)

    # Dedupe by sig — update count if exists
    existing = await db[_COLLECTION].find_one({"sig": body.sig})
    now = datetime.now(timezone.utc)
    if existing:
        await db[_COLLECTION].update_one(
            {"sig": body.sig},
            {"$set": {
                "last_seen": body.last_seen or now,
                "count_24h": body.count_24h,
                "updated_at": now,
            }, "$inc": {"recurrence_count": 1}},
        )
        return _serialize(await db[_COLLECTION].find_one({"sig": body.sig}, {"_id": 0}))

    # Auto-number issue_id
    last = await db[_COLLECTION].find_one({}, {"issue_id": 1}, sort=[("created_at", -1)])
    last_n = 0
    if last and last.get("issue_id", "").startswith("WORK-"):
        try:
            last_n = int(last["issue_id"].split("-")[1])
        except (ValueError, IndexError):
            pass
    issue_id = f"WORK-{last_n + 1:04d}"

    priority = body.priority or _severity_to_priority(body.severity)
    doc = {
        "issue_id": issue_id,
        "sig": body.sig,
        "title": body.title,
        "severity": body.severity,
        "priority": priority,
        "status": "open",
        "source": body.source,
        "exception_class": body.exception_class,
        "endpoint": body.endpoint,
        "job_name": body.job_name,
        "http_status": body.http_status,
        "sample_message": body.sample_message,
        "sample_traceback": body.sample_traceback,
        "first_seen": body.first_seen or now,
        "last_seen": body.last_seen or now,
        "count_24h": body.count_24h,
        "applications": body.applications,
        "rca": body.rca.model_dump() if body.rca else None,
        "labels": body.labels,
        "assignee": None,
        "comments": [],
        "recurrence_count": 1,
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
    }
    await db[_COLLECTION].insert_one(doc)
    doc.pop("_id", None)
    return _serialize(doc)


@router.patch("/issues/{issue_id}")
async def update_issue(request: Request, issue_id: str, body: IssueUpdate):
    await require_admin(request)
    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {"updated_at": now}

    if body.status is not None:
        update["status"] = body.status
        if body.status == "resolved":
            update["resolved_at"] = now
    if body.priority is not None:
        update["priority"] = body.priority
    if body.assignee is not None:
        update["assignee"] = body.assignee
    if body.labels is not None:
        update["labels"] = body.labels
    if body.rca is not None:
        update["rca"] = body.rca.model_dump()

    ops: dict[str, Any] = {"$set": update}
    if body.comment:
        user = await require_admin(request)
        ops["$push"] = {"comments": {
            "author": user.get("email", "admin"),
            "body": body.comment,
            "created_at": now.isoformat(),
        }}

    result = await db[_COLLECTION].update_one({"issue_id": issue_id}, ops)
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")
    doc = await db[_COLLECTION].find_one({"issue_id": issue_id}, {"_id": 0})
    return _serialize(doc)


@router.get("/stats")
async def get_stats(request: Request):
    await require_admin(request)
    pipeline = [
        {"$group": {
            "_id": {"status": "$status", "priority": "$priority"},
            "count": {"$sum": 1},
        }}
    ]
    buckets = await db[_COLLECTION].aggregate(pipeline).to_list(100)
    stats: dict[str, Any] = {
        "total": 0,
        "by_status": {"open": 0, "in_progress": 0, "resolved": 0, "wont_fix": 0},
        "by_priority": {"P1": 0, "P2": 0, "P3": 0},
    }
    for b in buckets:
        count = b["count"]
        stats["total"] += count
        status = b["_id"].get("status", "open")
        priority = b["_id"].get("priority", "P2")
        stats["by_status"][status] = stats["by_status"].get(status, 0) + count
        stats["by_priority"][priority] = stats["by_priority"].get(priority, 0) + count
    return stats


@router.post("/issues/ingest", status_code=201)
async def ingest_cluster(request: Request, body: dict):
    """
    Internal endpoint called by error_triage.py to bulk-upsert clusters.
    Accepts the same cluster dict format that error_triage builds.
    Protected by admin auth OR an internal INGEST_SECRET header.
    """
    import os
    ingest_secret = os.getenv("WORK_INGEST_SECRET", "")
    auth_header = request.headers.get("X-Ingest-Secret", "")
    if not (ingest_secret and auth_header == ingest_secret):
        await require_admin(request)

    clusters: list[dict] = body.get("clusters", [])
    created = 0
    updated = 0
    for c in clusters:
        sig = c.get("sig", "")
        if not sig:
            continue
        exc_cls = c.get("exception_class", "")
        endpoint = c.get("endpoint", "")
        job = c.get("job_name", "")
        where = endpoint or job or "(unknown)"
        title = f"{exc_cls or 'Error'} at {where}" if exc_cls else f"Error at {where}"
        severity = c.get("severity", "ERROR")
        priority = _severity_to_priority(severity)
        rca = None
        if c.get("root_cause"):
            rca = RcaBlock(
                root_cause=c.get("root_cause", ""),
                fix_suggestion=c.get("fix_suggestion", ""),
                confidence=0.7,
                source="openai",
            )
        existing = await db[_COLLECTION].find_one({"sig": sig})
        now = datetime.now(timezone.utc)
        if existing:
            await db[_COLLECTION].update_one(
                {"sig": sig},
                {"$set": {
                    "count_24h": c.get("count", 1),
                    "last_seen": c.get("last_seen") or now,
                    "updated_at": now,
                }, "$inc": {"recurrence_count": 1}},
            )
            updated += 1
        else:
            last = await db[_COLLECTION].find_one({}, {"issue_id": 1}, sort=[("created_at", -1)])
            last_n = 0
            if last and last.get("issue_id", "").startswith("WORK-"):
                try:
                    last_n = int(last["issue_id"].split("-")[1])
                except (ValueError, IndexError):
                    pass
            doc = {
                "issue_id": f"WORK-{last_n + 1:04d}",
                "sig": sig,
                "title": title,
                "severity": severity,
                "priority": priority,
                "status": "open",
                "source": "cloud_logging",
                "exception_class": exc_cls,
                "endpoint": endpoint,
                "job_name": job,
                "http_status": c.get("http_status"),
                "sample_message": (c.get("sample_msg") or "")[:500],
                "sample_traceback": (c.get("sample_exc") or "")[:1000],
                "first_seen": c.get("first_seen") or now,
                "last_seen": c.get("last_seen") or now,
                "count_24h": c.get("count", 1),
                "applications": list(c.get("apps", [])),
                "rca": rca.model_dump() if rca else None,
                "labels": [],
                "assignee": None,
                "comments": [],
                "recurrence_count": 1,
                "created_at": now,
                "updated_at": now,
                "resolved_at": None,
            }
            await db[_COLLECTION].insert_one(doc)
            doc.pop("_id", None)
            created += 1

    return {"created": created, "updated": updated}
