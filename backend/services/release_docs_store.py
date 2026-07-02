"""Release Process Management — MongoDB store.

Powers Settings → Release Management (admin-only). Two document types are
authored from generic templates and versioned by release semver:

  - release_notes    (from docs/release-management/TEMPLATE_release_notes.md)
  - release_process  (from docs/release-management/TEMPLATE_release_process.md)

Storage model (two collections, both keyed by a string uuid ``_id`` like the
rest of the app — see routes/positional_journal.py):

  release_documents           — the current HEAD of each (doc_type, release_version).
                                Fast reads for the list + editor.
  release_document_revisions  — APPEND-ONLY snapshot per save. Never mutated or
                                deleted, so the full edit history is an immutable
                                audit trail. Each save bumps head.current_revision
                                and inserts a new revision snapshot.

Every function is a no-op-safe async wrapper around the shared Motor handle
(`deps.db`). Validation lives here (defensive) and in the route's pydantic models.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from deps import db

logger = logging.getLogger(__name__)

DOCS_COL = "release_documents"
REVISIONS_COL = "release_document_revisions"

DOC_TYPES = ("release_notes", "release_process")
STATUSES = ("draft", "in_review", "approved", "final")
FORMATS = ("structured", "markdown")
ENVIRONMENTS = ("staging", "production")

# MAJOR.MINOR.PATCH with an optional pre-release/build suffix (e.g. 4.2.0, 4.2.0-rc.1).
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")


class ReleaseDocError(Exception):
    """Base for expected, caller-mappable errors."""


class DuplicateError(ReleaseDocError):
    """A (doc_type, release_version) document already exists."""


class ValidationError(ReleaseDocError):
    """Payload failed a defensive store-side check."""


# ── Templates ──────────────────────────────────────────────────────────────
# The generic, reusable skeletons interpreted from the two example documents.
# Each template is an ordered list of sections; the authoring form renders one
# labelled field per section, pre-filled with the section's starter body.
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "release_notes": {
        "doc_type": "release_notes",
        "label": "Release Notes",
        "title_hint": "Release Notes — v<version>",
        "sections": [
            {"key": "document_information", "title": "Document Information",
             "body": "| Field | Value |\n|---|---|\n| Release Date | |\n| Status | Draft |\n| Prepared By | |\n| Reviewed By | |\n| Approved By | |\n| Environment | Production |\n| Related Sprint | |"},
            {"key": "release_summary", "title": "Release Summary",
             "body": "One paragraph on what this release delivers.\n\n| Category | Count | Priority |\n|---|---|---|\n| New Features | | |\n| Bug Fixes | | |\n| Performance | | |\n| Security | | |"},
            {"key": "new_features", "title": "New Features",
             "body": "### <FEAT-ID> — <name>\n- Priority: \n- Module: \n- Description: \n- Changes Made: \n- Impact: "},
            {"key": "bug_fixes", "title": "Bug Fixes",
             "body": "| Bug ID | Severity | Module | Description | Root Cause | Fix |\n|---|---|---|---|---|---|\n| | | | | | |"},
            {"key": "testing_verification", "title": "Testing Verification",
             "body": "| Test Type | Total | Passed | Failed | Pass Rate |\n|---|---|---|---|---|\n| Unit | | | | |\n| Integration | | | | |\n| E2E | | | | |\n| Regression | | | | |"},
            {"key": "impact_analysis", "title": "Impact Analysis",
             "body": "| Component | Impacted? | Change Type | Risk | Rollback Plan |\n|---|---|---|---|---|\n| | | | | |"},
            {"key": "rollback_deployment", "title": "Rollback & Deployment Plan",
             "body": "Deployment Steps:\n\nRollback Triggers:\n\nRollback Procedure:"},
            {"key": "approvals", "title": "Approval & Sign-Off",
             "body": "| Role | Name | Date | Status |\n|---|---|---|---|\n| QA Lead | | | Pending |\n| Tech Lead | | | Pending |\n| Product Manager | | | Pending |\n| Security Officer | | | Pending |\n| VP Engineering | | | Pending |"},
        ],
    },
    "release_process": {
        "doc_type": "release_process",
        "label": "Release Process",
        "title_hint": "Release Process — v<version>",
        "sections": [
            {"key": "overview", "title": "Overview",
             "body": "| Item | Detail |\n|---|---|\n| Release Type | |\n| Staging Window | |\n| Production Window | |\n| Estimated Downtime | Zero |\n| Rollback SLA | < 15 min |"},
            {"key": "prerequisites", "title": "Prerequisites & Readiness Checklist",
             "body": "Code & QA:\n- [ ] Branches merged\n- [ ] CI green\n- [ ] QA sign-off\n\nInfra:\n- [ ] Staging mirrors prod\n- [ ] Migrations reviewed\n- [ ] Secrets updated\n\nApprovals:\n- [ ] QA · [ ] Tech Lead · [ ] PM · [ ] Security · [ ] VP Eng"},
            {"key": "environment_architecture", "title": "Environment Architecture",
             "body": "| Property | Staging | Production |\n|---|---|---|\n| URL | | |\n| DB | | |\n| API Pods | | |"},
            {"key": "roles", "title": "Roles & Responsibilities",
             "body": "| Role | Person | Responsibilities |\n|---|---|---|\n| Release Manager | | |\n| DevOps | | |\n| QA Lead | | |"},
            {"key": "stage_code_freeze", "title": "Stage 1 — Code Freeze & Branching",
             "body": "Owner: · Timeline: T-48h\nSteps: freeze, cut release branch, version bump, tag artifacts.\nExit: branch protected, CI green, artifacts pushed."},
            {"key": "stage_staging_deploy", "title": "Stage 2 — Staging Deployment",
             "body": "Owner: · Timeline: \nSteps: notify, DB migration, deploy API, deploy frontend, enable flags.\nExit: new version live, migrations applied, health 200."},
            {"key": "stage_staging_verify", "title": "Stage 3 — Staging Verification & Sign-Off",
             "body": "Smoke · Regression · Per-feature · Bug-fix · Load.\nSign-off gate: all pass; QA + PM + Security sign-off; no Sev-1/Sev-2."},
            {"key": "stage_production_deploy", "title": "Stage 4 — Production Deployment",
             "body": "Owner: · Timeline: low-traffic window\nSteps: pre-checks, snapshot, migration, blue/green 10→50→100%, frontend, gradual flags.\nExit: version live, error rate in band, no Sev-1."},
            {"key": "stage_post_deploy", "title": "Stage 5 — Post-Deployment Monitoring",
             "body": "Owner: · Timeline: 24h\nReal-time thresholds · Synthetics · Business metrics · Post-deploy review."},
            {"key": "rollback", "title": "Rollback Procedure",
             "body": "Triggers: error rate / latency / payment failure / Sev-1 / data integrity / security.\nSteps (< N min): disable flags → shift traffic → revert frontend → rollback migration → verify.\nPost: notify, Sev-1 ticket, preserve logs, RCA."},
            {"key": "communication", "title": "Communication Plan",
             "body": "| Event | Channel | Audience | Owner |\n|---|---|---|---|\n| Code freeze | | | |\n| Staging deploy | | | |\n| Prod deploy | | | |\n| Rollback | | | |"},
            {"key": "checklist_summary", "title": "Release Checklist Summary",
             "body": "- [ ] Stage 1 · [ ] Stage 2 · [ ] Stage 3 sign-off · [ ] Stage 4 · [ ] Stage 5 review"},
        ],
    },
}


def get_templates() -> Dict[str, Any]:
    """Return the two generic template skeletons for the authoring form."""
    return {"templates": [TEMPLATES["release_notes"], TEMPLATES["release_process"]]}


# ── Helpers ──────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate(doc_type: str, release_version: str, fmt: str, status: str) -> None:
    if doc_type not in DOC_TYPES:
        raise ValidationError(f"invalid doc_type: {doc_type!r}")
    if not SEMVER_RE.match(release_version or ""):
        raise ValidationError(f"invalid release_version (expected semver): {release_version!r}")
    if fmt not in FORMATS:
        raise ValidationError(f"invalid format: {fmt!r}")
    if status not in STATUSES:
        raise ValidationError(f"invalid status: {status!r}")


def _summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    """List-view projection — everything except the (potentially large) content."""
    return {
        "id": doc["_id"],
        "doc_type": doc["doc_type"],
        "release_version": doc["release_version"],
        "title": doc["title"],
        "status": doc["status"],
        "environment": doc.get("environment"),
        "format": doc["format"],
        "current_revision": doc["current_revision"],
        "created_at": doc["created_at"],
        "created_by": doc["created_by"],
        "updated_at": doc["updated_at"],
        "updated_by": doc["updated_by"],
    }


def _full(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = _summary(doc)
    out["content"] = doc.get("content")
    return out


# ── CRUD ─────────────────────────────────────────────────────────────────
async def list_documents(
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """All release docs (head summaries), newest-updated first."""
    q: Dict[str, Any] = {}
    if doc_type:
        q["doc_type"] = doc_type
    if status:
        q["status"] = status
    docs = await db[DOCS_COL].find(q, {"content": 0}).sort("updated_at", -1).to_list(1000)
    # content is projected out, so build summaries directly (content key absent).
    return [
        {
            "id": d["_id"],
            "doc_type": d["doc_type"],
            "release_version": d["release_version"],
            "title": d["title"],
            "status": d["status"],
            "environment": d.get("environment"),
            "format": d["format"],
            "current_revision": d["current_revision"],
            "created_at": d["created_at"],
            "created_by": d["created_by"],
            "updated_at": d["updated_at"],
            "updated_by": d["updated_by"],
        }
        for d in docs
    ]


async def get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    doc = await db[DOCS_COL].find_one({"_id": doc_id})
    return _full(doc) if doc else None


async def create_document(
    *,
    doc_type: str,
    release_version: str,
    title: str,
    content: Any,
    fmt: str = "structured",
    status: str = "draft",
    environment: Optional[str] = None,
    author: str,
) -> Dict[str, Any]:
    """Create a new release doc (head + revision 1). Enforces one document per
    (doc_type, release_version). Raises DuplicateError / ValidationError."""
    _validate(doc_type, release_version, fmt, status)
    if not title or not str(title).strip():
        raise ValidationError("title is required")
    if content is None:
        raise ValidationError("content is required")

    existing = await db[DOCS_COL].find_one(
        {"doc_type": doc_type, "release_version": release_version}, {"_id": 1}
    )
    if existing:
        raise DuplicateError(
            f"a {doc_type} for release {release_version} already exists"
        )

    now = _now()
    doc_id = str(uuid4())
    head = {
        "_id": doc_id,
        "doc_type": doc_type,
        "release_version": release_version,
        "title": str(title).strip(),
        "status": status,
        "environment": environment if environment in ENVIRONMENTS else None,
        "format": fmt,
        "content": content,
        "current_revision": 1,
        "created_at": now,
        "created_by": author,
        "updated_at": now,
        "updated_by": author,
    }
    await db[DOCS_COL].insert_one(head)
    await db[REVISIONS_COL].insert_one(
        {
            "_id": str(uuid4()),
            "document_id": doc_id,
            "doc_type": doc_type,
            "release_version": release_version,
            "revision": 1,
            "status": status,
            "format": fmt,
            "content": content,
            "change_note": "initial version",
            "saved_at": now,
            "saved_by": author,
        }
    )
    logger.info(
        "release doc created: %s v%s rev1", doc_type, release_version,
        extra={"eventType": "BUSINESS_EVENT"},
    )
    return _full(head)


async def update_document(
    doc_id: str,
    *,
    content: Any,
    status: Optional[str] = None,
    change_note: Optional[str] = None,
    author: str,
) -> Optional[Dict[str, Any]]:
    """Save an edit → append an immutable revision and advance the head.
    Returns the updated head, or None if the document does not exist."""
    head = await db[DOCS_COL].find_one({"_id": doc_id})
    if not head:
        return None
    if content is None:
        raise ValidationError("content is required")
    new_status = status if status is not None else head["status"]
    if new_status not in STATUSES:
        raise ValidationError(f"invalid status: {new_status!r}")

    now = _now()
    new_rev = int(head["current_revision"]) + 1
    await db[DOCS_COL].update_one(
        {"_id": doc_id},
        {
            "$set": {
                "content": content,
                "status": new_status,
                "current_revision": new_rev,
                "updated_at": now,
                "updated_by": author,
            }
        },
    )
    await db[REVISIONS_COL].insert_one(
        {
            "_id": str(uuid4()),
            "document_id": doc_id,
            "doc_type": head["doc_type"],
            "release_version": head["release_version"],
            "revision": new_rev,
            "status": new_status,
            "format": head["format"],
            "content": content,
            "change_note": (change_note or None),
            "saved_at": now,
            "saved_by": author,
        }
    )
    logger.info(
        "release doc updated: %s v%s rev%d", head["doc_type"],
        head["release_version"], new_rev, extra={"eventType": "BUSINESS_EVENT"},
    )
    updated = await db[DOCS_COL].find_one({"_id": doc_id})
    return _full(updated) if updated else None


async def list_revisions(doc_id: str) -> Optional[List[Dict[str, Any]]]:
    """Revision history metadata (no content), oldest→newest. None if the
    document does not exist (distinguishes 'no doc' from 'no revisions')."""
    head = await db[DOCS_COL].find_one({"_id": doc_id}, {"_id": 1})
    if not head:
        return None
    revs = (
        await db[REVISIONS_COL]
        .find({"document_id": doc_id}, {"content": 0})
        .sort("revision", 1)
        .to_list(1000)
    )
    return [
        {
            "revision": r["revision"],
            "status": r["status"],
            "format": r["format"],
            "change_note": r.get("change_note"),
            "saved_at": r["saved_at"],
            "saved_by": r["saved_by"],
        }
        for r in revs
    ]


async def get_revision(doc_id: str, revision: int) -> Optional[Dict[str, Any]]:
    """A single immutable revision snapshot (full content)."""
    r = await db[REVISIONS_COL].find_one({"document_id": doc_id, "revision": revision})
    if not r:
        return None
    return {
        "document_id": doc_id,
        "revision": r["revision"],
        "doc_type": r["doc_type"],
        "release_version": r["release_version"],
        "status": r["status"],
        "format": r["format"],
        "content": r.get("content"),
        "change_note": r.get("change_note"),
        "saved_at": r["saved_at"],
        "saved_by": r["saved_by"],
    }
