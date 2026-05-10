"""DaaS API routes for AI-assisted data quality.

Mounted at /v1/dq under the existing daas_api app. All endpoints
require the standard X-API-Key header.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, page_params, parse_date, row_to_dict

from nidp.services.dq_ai import diagnostics, expectation_author


router = APIRouter(prefix="/dq", tags=["data-quality"], dependencies=[Depends(require_api_key)])


# ── Smell diagnostics ───────────────────────────────────────────────

class AnalyzeRunBody(BaseModel):
    run_id: str = Field(..., description="dq.validation_runs.run_id (UUID)")


@router.post("/diagnostics/analyze", summary="Run AI smell analyzer on a validation_run")
async def analyze_run(body: AnalyzeRunBody) -> Dict[str, Any]:
    try:
        return await diagnostics.analyze_run(body.run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/diagnostics", summary="List smell diagnostics for a dataset")
async def list_diagnostics(
    dataset: Optional[str] = Query(None),
    target_date: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d = parse_date(target_date, field="target_date")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT diagnostic_id, run_id, dataset_name, target_date,
                      smell, root_causes_json, suggested_fixes_json,
                      blocking_for_intelligence, estimated_impact,
                      llm_model, created_at
                 FROM dq.smell_diagnostics
                WHERE ($1::text IS NULL OR dataset_name = $1)
                  AND ($2::date IS NULL OR target_date  = $2)
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4""",
            dataset, d, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/diagnostics/{diagnostic_id}", summary="Get one smell diagnostic")
async def get_diagnostic(diagnostic_id: str) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM dq.smell_diagnostics WHERE diagnostic_id = $1::uuid",
            diagnostic_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="diagnostic not found")
    return {"data": row_to_dict(row)}


# ── Expectation proposals ───────────────────────────────────────────

class ProposeBody(BaseModel):
    dataset: str = Field(..., min_length=1, max_length=128)
    sample_size: int = Field(1000, ge=10, le=10000)
    failure_history_days: int = Field(30, ge=0, le=365)


@router.post("/proposals/generate", summary="Run AI expectation author for a dataset")
async def generate_proposals(body: ProposeBody) -> Dict[str, Any]:
    try:
        result = await expectation_author.propose_expectations(
            body.dataset,
            sample_size=body.sample_size,
            failure_history_days=body.failure_history_days,
        )
        # Trim raw_proposals to keep response compact; full bodies
        # available via /v1/dq/proposals individual fetch.
        return {
            "dataset": result["dataset"],
            "model": result["model"],
            "proposals_count": result["proposals_count"],
            "written_count": result["written_count"],
            "proposal_ids": result["proposal_ids"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/proposals", summary="List AI proposals (filterable)")
async def list_proposals(
    dataset: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(proposed|accepted|rejected|superseded)$"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT proposal_id, dataset_name, proposed_rule_json, status,
                      reviewed_by, reviewed_at, review_notes,
                      promoted_rule_id, llm_model, created_at
                 FROM dq.expectation_proposals
                WHERE ($1::text IS NULL OR dataset_name = $1)
                  AND ($2::text IS NULL OR status       = $2)
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4""",
            dataset, status, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


class ReviewBody(BaseModel):
    reviewer: str = Field(..., min_length=1, max_length=128)
    notes: Optional[str] = None


@router.post("/proposals/{proposal_id}/accept", summary="Promote proposal to active expectation")
async def accept(proposal_id: str, body: ReviewBody) -> Dict[str, Any]:
    try:
        return await expectation_author.accept_proposal(
            proposal_id, reviewer=body.reviewer, notes=body.notes
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class RejectBody(BaseModel):
    reviewer: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(..., min_length=1, max_length=512)


@router.post("/proposals/{proposal_id}/reject", summary="Reject AI proposal")
async def reject(proposal_id: str, body: RejectBody) -> Dict[str, Any]:
    return await expectation_author.reject_proposal(
        proposal_id, reviewer=body.reviewer, reason=body.reason
    )


# ── Active expectations ─────────────────────────────────────────────

@router.get("/expectations/active", summary="List active expectation rules")
async def list_active(
    dataset: Optional[str] = Query(None),
    source: Optional[str] = Query(None, pattern="^(hand|ai_proposed|promoted)$"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT rule_id, dataset_name, name, description, expression,
                      severity, source, active, rationale, business_impact,
                      promoted_by, promoted_at, created_at
                 FROM dq.expectations_active
                WHERE ($1::text IS NULL OR dataset_name = $1)
                  AND ($2::text IS NULL OR source       = $2)
                  AND active = TRUE
                ORDER BY dataset_name, name
                LIMIT $3 OFFSET $4""",
            dataset, source, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)
