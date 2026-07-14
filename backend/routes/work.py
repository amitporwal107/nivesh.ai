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

from deps import db, require_admin, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/work", tags=["work"])

_COLLECTION = "work_issues"

# ── Lifecycle & triage vocab (matches the issue-lifecycle diagram) ────────────
# open → in_progress → in_review → testing_qa → resolved ; wont_fix (from open).
# The QA-failure path (testing_qa → in_progress) and regression/reopen
# (resolved → open) are ordinary status writes — not special-cased, just allowed.
ALLOWED_STATUSES = {"open", "in_progress", "in_review", "testing_qa", "resolved", "wont_fix"}

# Triage classification, set by a human after the issue is auto-filed:
#   valid                → a real defect
#   business_validation  → expected validation error, not a code bug
#   tbd                  → needs clarification
ALLOWED_CLASSIFICATIONS = {"unclassified", "valid", "business_validation", "tbd"}

# ── Program-tracker hierarchy (epics → stories → tasks) ───────────────────────
# The dashboard doubles as a program tracker for planned work (source="manual"),
# alongside the auto-filed error issues. These fields are additive and optional:
# existing error issues default to issue_type="task" with no parent/phase.
ALLOWED_ISSUE_TYPES = {"project", "epic", "story", "task"}
ALLOWED_PHASES = {"phase-1", "phase-2", "phase-3"}
ALLOWED_TRACKS = {"internal", "vendor-gated"}
ALLOWED_ESTIMATES = {"S", "M", "L", "XL"}

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
    # ── program-tracker (project → epics → stories → tasks) — optional, additive ──
    issue_type: str = "task"                  # project | epic | story | task
    project: Optional[str] = None             # project key (e.g. "ADVW") — scopes an item to a project
    parent: Optional[str] = None              # parent issue_id (epic→project, story→epic, task→story)
    phase: Optional[str] = None               # phase-1 | phase-2 | phase-3
    track: Optional[str] = None               # internal | vendor-gated
    workflow: list[str] = Field(default_factory=list)     # ["WF-01", ...]
    estimate: Optional[str] = None            # S | M | L | XL
    assignee: Optional[str] = None            # owner (used for project rows)
    requirements_md: Optional[str] = None     # plain-English requirement + acceptance
    design_md: Optional[str] = None           # design elements + component list
    screens: list[dict] = Field(default_factory=list)     # [{"name","url"}]
    implementation_md: Optional[str] = None   # core implementation details
    github: Optional[dict] = None             # {"commit","pr_url","branch"}
    test_doc_md: Optional[str] = None         # test-cases document
    artifacts: list[dict] = Field(default_factory=list)   # [{"kind","url"}] post-impl


class IssueUpdate(BaseModel):
    status: Optional[str] = None     # see ALLOWED_STATUSES
    classification: Optional[str] = None  # see ALLOWED_CLASSIFICATIONS
    priority: Optional[str] = None
    assignee: Optional[str] = None
    labels: Optional[list[str]] = None
    rca: Optional[RcaBlock] = None
    comment: Optional[str] = None    # appends to comments list
    # ── program-tracker fields (all optional; used for grooming + migration) ──
    title: Optional[str] = None
    issue_type: Optional[str] = None
    project: Optional[str] = None
    parent: Optional[str] = None
    phase: Optional[str] = None
    track: Optional[str] = None
    workflow: Optional[list[str]] = None
    estimate: Optional[str] = None
    requirements_md: Optional[str] = None
    design_md: Optional[str] = None
    screens: Optional[list[dict]] = None
    implementation_md: Optional[str] = None
    github: Optional[dict] = None
    test_doc_md: Optional[str] = None
    artifacts: Optional[list[dict]] = None


class Remediation(BaseModel):
    """State of the auto-fix pipeline for an issue (PR-only; never auto-merged)."""
    status: str = "none"             # none|queued|running|pr_open|failed|verified
    branch: Optional[str] = None
    pr_url: Optional[str] = None
    run_id: Optional[str] = None
    detail: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ArtifactsUpdate(BaseModel):
    """Written by the remediation pipeline (fix agent / diagnostics), not humans."""
    rca_document: Optional[str] = None      # full RCA markdown
    test_document: Optional[str] = None     # test report markdown
    screenshots: Optional[list[str]] = None # screenshot URLs / data refs
    remediation: Optional[Remediation] = None
    status: Optional[str] = None            # pipeline may advance the lifecycle
    comment: Optional[str] = None


class ClientErrorEntry(BaseModel):
    message: str
    correlation_id: Optional[str] = None


class ClientErrorBatch(BaseModel):
    entries: list[ClientErrorEntry] = Field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _severity_to_priority(severity: str) -> str:
    return {"CRITICAL": "P1", "ERROR": "P2", "WARNING": "P3"}.get(severity.upper(), "P2")


def _validate_tracker_fields(issue_type=None, phase=None, track=None, estimate=None) -> None:
    """Validate optional program-tracker enums; None values are skipped."""
    if issue_type and issue_type not in ALLOWED_ISSUE_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid issue_type; allowed: {sorted(ALLOWED_ISSUE_TYPES)}")
    if phase and phase not in ALLOWED_PHASES:
        raise HTTPException(status_code=400, detail=f"invalid phase; allowed: {sorted(ALLOWED_PHASES)}")
    if track and track not in ALLOWED_TRACKS:
        raise HTTPException(status_code=400, detail=f"invalid track; allowed: {sorted(ALLOWED_TRACKS)}")
    if estimate and estimate not in ALLOWED_ESTIMATES:
        raise HTTPException(status_code=400, detail=f"invalid estimate; allowed: {sorted(ALLOWED_ESTIMATES)}")


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
    issue_type: Optional[str] = Query(None, description="project|epic|story|task"),
    project: Optional[str] = Query(None, description="project key, e.g. ADVW"),
    phase: Optional[str] = Query(None, description="phase-1|phase-2|phase-3"),
    parent: Optional[str] = Query(None, description="parent issue_id"),
    track: Optional[str] = Query(None, description="internal|vendor-gated"),
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
    if issue_type:
        flt["issue_type"] = issue_type
    if project:
        flt["project"] = project
    if phase:
        flt["phase"] = phase
    if parent:
        flt["parent"] = parent
    if track:
        flt["track"] = track

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
    _validate_tracker_fields(body.issue_type, body.phase, body.track, body.estimate)

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
        "assignee": body.assignee,
        "comments": [],
        "recurrence_count": 1,
        "classification": "unclassified",
        "rca_document": None,
        "test_document": None,
        "screenshots": [],
        "remediation": None,
        # ── program-tracker (project → epics → stories → tasks) ──
        "issue_type": body.issue_type or "task",
        "project": body.project,
        "parent": body.parent,
        "phase": body.phase,
        "track": body.track,
        "workflow": body.workflow,
        "estimate": body.estimate,
        "requirements_md": body.requirements_md,
        "design_md": body.design_md,
        "screens": body.screens,
        "implementation_md": body.implementation_md,
        "github": body.github,
        "test_doc_md": body.test_doc_md,
        "artifacts": body.artifacts,
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
        if body.status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail=f"invalid status; allowed: {sorted(ALLOWED_STATUSES)}")
        update["status"] = body.status
        if body.status == "resolved":
            update["resolved_at"] = now
        elif body.status == "open":
            # regression / reopen — clear the resolved timestamp
            update["resolved_at"] = None
    if body.classification is not None:
        if body.classification not in ALLOWED_CLASSIFICATIONS:
            raise HTTPException(status_code=400, detail=f"invalid classification; allowed: {sorted(ALLOWED_CLASSIFICATIONS)}")
        update["classification"] = body.classification
    if body.priority is not None:
        update["priority"] = body.priority
    if body.assignee is not None:
        update["assignee"] = body.assignee
    if body.labels is not None:
        update["labels"] = body.labels
    if body.rca is not None:
        update["rca"] = body.rca.model_dump()

    # ── program-tracker fields (grooming + migration) ──
    _validate_tracker_fields(body.issue_type, body.phase, body.track, body.estimate)
    for _f in ("title", "issue_type", "project", "parent", "phase", "track", "workflow", "estimate",
               "requirements_md", "design_md", "screens", "implementation_md",
               "github", "test_doc_md", "artifacts"):
        _v = getattr(body, _f)
        if _v is not None:
            update[_f] = _v

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
        "by_status": {s: 0 for s in
                      ("open", "in_progress", "in_review", "testing_qa", "resolved", "wont_fix")},
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


@router.post("/issues/from-client-errors", status_code=202)
async def intake_client_errors(request: Request, body: ClientErrorBatch):
    """File work_issues for client-side (browser) errors captured while a user
    has session logging on. Any authenticated user may report their OWN errors
    (unlike the admin-only dashboard views). Deduped by sig; best-effort."""
    user = await get_current_user(request)
    from services import issue_intake
    filed: list[str] = []
    for e in body.entries[:50]:
        iid = await issue_intake.intake_error(
            severity="ERROR",
            source="session_client",
            message=e.message,
            application="nivesh-web",
            client=True,
        )
        if iid:
            filed.append(iid)
    logger.info("client-error intake by %s → %d issue(s)", user.get("user_id", "?"), len(set(filed)))
    return {"filed": list(dict.fromkeys(filed))}


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
                "classification": "unclassified",
                "rca_document": None,
                "test_document": None,
                "screenshots": [],
                "remediation": None,
                "created_at": now,
                "updated_at": now,
                "resolved_at": None,
            }
            await db[_COLLECTION].insert_one(doc)
            doc.pop("_id", None)
            created += 1

    return {"created": created, "updated": updated}


# ── Remediation pipeline: fix trigger + artifact attach (Phases 2/3) ──────────

_bg_tasks: set = set()


def _schedule(coro) -> None:
    """Fire-and-forget a background coroutine, keeping a ref so it isn't GC'd."""
    import asyncio
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _require_admin_or_ingest_secret(request: Request) -> None:
    import os
    ingest_secret = os.getenv("WORK_INGEST_SECRET", "")
    if ingest_secret and request.headers.get("X-Ingest-Secret", "") == ingest_secret:
        return
    await require_admin(request)


@router.post("/issues/{issue_id}/fix", status_code=202)
async def trigger_fix(request: Request, issue_id: str):
    """Spawn the PR-only auto-fix agent for a VALID coding issue.

    Safety: the agent works in an isolated clone and opens a PR for human
    review — it never applies or merges changes to dev/main. The issue must be
    triaged `classification=valid` first.
    """
    await require_admin(request)
    doc = await db[_COLLECTION].find_one({"issue_id": issue_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Issue not found")
    if doc.get("classification") != "valid":
        raise HTTPException(status_code=409, detail="Issue must be classified 'valid' before requesting a fix")
    rem = doc.get("remediation") or {}
    if rem.get("status") in ("queued", "running"):
        raise HTTPException(status_code=409, detail="A fix is already in progress for this issue")

    now = datetime.now(timezone.utc)
    await db[_COLLECTION].update_one(
        {"issue_id": issue_id},
        {"$set": {
            "status": "in_progress",
            "remediation": {
                "status": "queued", "started_at": now, "finished_at": None,
                "branch": None, "pr_url": None, "run_id": None,
                "detail": "Queued for the VM fix-agent runner",
            },
            "updated_at": now,
        }},
    )
    # The fix runs OUT-OF-PROCESS on the VM (which has git) — see
    # backend/scripts/fix_agent_runner.py (cron). It polls GET /api/work/fix-queue,
    # does the clone / LLM / push / PR, and reports back via /artifacts. The app
    # container has no git, so we never run the fix in-process.
    return {"issue_id": issue_id, "remediation": {"status": "queued"}}


@router.get("/fix-queue")
async def fix_queue(request: Request, limit: int = Query(20, le=100)):
    """Issues queued for the VM fix-agent runner (oldest first). Admin OR
    X-Ingest-Secret. Returns just the fields the runner needs to clone + fix + PR."""
    await _require_admin_or_ingest_secret(request)
    cursor = db[_COLLECTION].find(
        {"remediation.status": "queued", "classification": "valid"},
        {"_id": 0, "issue_id": 1, "title": 1, "severity": 1, "exception_class": 1,
         "endpoint": 1, "http_status": 1, "sample_message": 1, "sample_traceback": 1, "rca": 1},
    ).sort("updated_at", 1).limit(limit)
    docs = await cursor.to_list(limit)
    return {"issues": docs, "count": len(docs)}


@router.post("/issues/{issue_id}/artifacts")
async def attach_artifacts(request: Request, issue_id: str, body: ArtifactsUpdate):
    """Attach RCA / test documents / screenshots and (optionally) advance the
    lifecycle. Written by the remediation pipeline (admin OR X-Ingest-Secret)."""
    await _require_admin_or_ingest_secret(request)
    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {"updated_at": now}
    if body.rca_document is not None:
        update["rca_document"] = body.rca_document
    if body.test_document is not None:
        update["test_document"] = body.test_document
    if body.screenshots is not None:
        update["screenshots"] = body.screenshots
    if body.remediation is not None:
        update["remediation"] = body.remediation.model_dump()
    if body.status is not None:
        if body.status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail=f"invalid status; allowed: {sorted(ALLOWED_STATUSES)}")
        update["status"] = body.status
        if body.status == "resolved":
            update["resolved_at"] = now

    ops: dict[str, Any] = {"$set": update}
    if body.comment:
        ops["$push"] = {"comments": {"author": "pipeline", "body": body.comment,
                                     "created_at": now.isoformat()}}
    result = await db[_COLLECTION].update_one({"issue_id": issue_id}, ops)
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found")
    doc = await db[_COLLECTION].find_one({"issue_id": issue_id}, {"_id": 0})
    return _serialize(doc)
