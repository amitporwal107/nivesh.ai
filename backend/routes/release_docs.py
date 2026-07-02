"""Release Process Management API — powers Settings → Release Management.

Admin-only. Authors and versions two document types (release_notes,
release_process) from generic templates, persisted in MongoDB with an
append-only revision history (see services/release_docs_store.py).

Every endpoint is gated by `require_admin` (401 unauthenticated, 403 non-admin).
Versioning: each document is keyed by release semver; every save appends an
immutable revision snapshot and advances the head's current_revision.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from deps import require_admin
from services import release_docs_store as store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/release-docs", tags=["release-docs"])

_SEMVER = r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$"


class CreateBody(BaseModel):
    doc_type: Literal["release_notes", "release_process"]
    release_version: str = Field(..., pattern=_SEMVER)
    title: str = Field(..., min_length=1, max_length=200)
    content: Dict[str, Any]
    format: Literal["structured", "markdown"] = "structured"
    status: Literal["draft", "in_review", "approved", "final"] = "draft"
    environment: Optional[Literal["staging", "production"]] = None


class UpdateBody(BaseModel):
    content: Dict[str, Any]
    status: Optional[Literal["draft", "in_review", "approved", "final"]] = None
    change_note: Optional[str] = Field(default=None, max_length=500)


@router.get("")
async def list_release_docs(
    request: Request,
    doc_type: Optional[Literal["release_notes", "release_process"]] = Query(default=None),
    status: Optional[Literal["draft", "in_review", "approved", "final"]] = Query(default=None),
) -> Dict[str, List[Dict[str, Any]]]:
    """All release documents (head summaries, no content), newest-updated first."""
    await require_admin(request)
    docs = await store.list_documents(doc_type=doc_type, status=status)
    return {"documents": docs}


@router.get("/templates")
async def get_release_doc_templates(request: Request) -> Dict[str, Any]:
    """The two generic template skeletons the authoring form renders."""
    await require_admin(request)
    return store.get_templates()


@router.post("", status_code=201)
async def create_release_doc(request: Request, body: CreateBody) -> Dict[str, Any]:
    """Create a new release document (head + revision 1) from a template.
    409 if one already exists for this (doc_type, release_version)."""
    admin = await require_admin(request)
    try:
        doc = await store.create_document(
            doc_type=body.doc_type,
            release_version=body.release_version,
            title=body.title,
            content=body.content,
            fmt=body.format,
            status=body.status,
            environment=body.environment,
            author=admin.get("email", "admin"),
        )
    except store.DuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except store.ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return doc


@router.get("/{doc_id}")
async def get_release_doc(request: Request, doc_id: str) -> Dict[str, Any]:
    """Full current content of one release document."""
    await require_admin(request)
    doc = await store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="release document not found")
    return doc


@router.put("/{doc_id}")
async def update_release_doc(request: Request, doc_id: str, body: UpdateBody) -> Dict[str, Any]:
    """Save an edit → append an immutable revision and advance the head."""
    admin = await require_admin(request)
    try:
        doc = await store.update_document(
            doc_id,
            content=body.content,
            status=body.status,
            change_note=body.change_note,
            author=admin.get("email", "admin"),
        )
    except store.ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if doc is None:
        raise HTTPException(status_code=404, detail="release document not found")
    return doc


@router.get("/{doc_id}/revisions")
async def list_release_doc_revisions(request: Request, doc_id: str) -> Dict[str, Any]:
    """Immutable revision history (metadata only), oldest→newest."""
    await require_admin(request)
    revs = await store.list_revisions(doc_id)
    if revs is None:
        raise HTTPException(status_code=404, detail="release document not found")
    return {"document_id": doc_id, "revisions": revs}


@router.get("/{doc_id}/revisions/{revision}")
async def get_release_doc_revision(request: Request, doc_id: str, revision: int) -> Dict[str, Any]:
    """One immutable revision snapshot (full content)."""
    await require_admin(request)
    rev = await store.get_revision(doc_id, revision)
    if rev is None:
        raise HTTPException(status_code=404, detail="revision not found")
    return rev
