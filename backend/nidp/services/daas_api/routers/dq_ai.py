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
    include_inactive: bool = Query(False),
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
                  AND ($3::bool OR active = TRUE)
                ORDER BY dataset_name, name
                LIMIT $4 OFFSET $5""",
            dataset, source, include_inactive, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


# ── Hand-authored CRUD on active expectations ────────────────────────

_SEVERITY_RE = "^(INFO|WARN|ERROR|CRITICAL)$"


class CreateRuleBody(BaseModel):
    dataset_name:    str = Field(..., min_length=1, max_length=128)
    name:            str = Field(..., min_length=1, max_length=128)
    expression:      str = Field(..., min_length=1, max_length=2000)
    severity:        str = Field("ERROR", pattern=_SEVERITY_RE)
    description:     Optional[str] = None
    rationale:       Optional[str] = None
    business_impact: Optional[str] = None
    actor:           str = Field("ui", min_length=1, max_length=128)


@router.post("/expectations/active", summary="Create hand-authored expectation")
async def create_active(body: CreateRuleBody) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rid = await conn.fetchval(
                """
                INSERT INTO dq.expectations_active (
                    dataset_name, name, description, expression, severity,
                    source, active, rationale, business_impact,
                    promoted_by, promoted_at
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    'hand', TRUE, $6, $7,
                    $8, NOW()
                ) RETURNING rule_id
                """,
                body.dataset_name, body.name, body.description, body.expression,
                body.severity, body.rationale, body.business_impact, body.actor,
            )
        except Exception as e:                  # noqa: BLE001
            raise HTTPException(status_code=409, detail=f"could not create rule: {e}")
    return {"rule_id": str(rid), "status": "created"}


class UpdateRuleBody(BaseModel):
    expression:      Optional[str] = Field(None, min_length=1, max_length=2000)
    severity:        Optional[str] = Field(None, pattern=_SEVERITY_RE)
    description:     Optional[str] = None
    rationale:       Optional[str] = None
    business_impact: Optional[str] = None
    active:          Optional[bool] = None
    actor:           str = Field("ui", min_length=1, max_length=128)


@router.patch("/expectations/active/{rule_id}", summary="Edit/toggle active expectation")
async def update_active(rule_id: str, body: UpdateRuleBody) -> Dict[str, Any]:
    fields = body.model_dump(exclude_unset=True, exclude={"actor"})
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")

    set_clauses = []
    values: list = []
    for i, (k, v) in enumerate(fields.items(), start=1):
        set_clauses.append(f"{k} = ${i}")
        values.append(v)
    values.append(rule_id)
    sql = (
        "UPDATE dq.expectations_active SET "
        + ", ".join(set_clauses)
        + f", promoted_by = ${len(values) + 1}, promoted_at = NOW() "
        + f"WHERE rule_id = ${len(values)}::uuid RETURNING rule_id"
    )
    values.append(body.actor)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rid = await conn.fetchval(sql, *values)
    if rid is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"rule_id": str(rid), "status": "updated", "changed_fields": list(fields)}


@router.delete("/expectations/active/{rule_id}", summary="Soft-delete expectation (active=FALSE)")
async def delete_active(rule_id: str, actor: str = Query("ui")) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rid = await conn.fetchval(
            """UPDATE dq.expectations_active
                  SET active = FALSE, promoted_by = $2, promoted_at = NOW()
                WHERE rule_id = $1::uuid RETURNING rule_id""",
            rule_id, actor,
        )
    if rid is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"rule_id": str(rid), "status": "deactivated"}


# ── Bulk AI generation across all NIDP datasets ──────────────────────

class GenerateAllBody(BaseModel):
    sample_size: int = Field(200, ge=10, le=5000)
    failure_history_days: int = Field(30, ge=0, le=365)
    feeds: Optional[list[str]] = Field(
        None,
        description="explicit list of dataset names; default = auto-discover from source_registry",
    )
    skip_existing: bool = Field(
        True,
        description="if a dataset already has active rules + recent proposals, skip it",
    )


@router.post("/proposals/generate-all", summary="Run AI expectation author across all feeds")
async def generate_all(body: GenerateAllBody) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if body.feeds:
            feeds = body.feeds
        else:
            rows = await conn.fetch(
                """SELECT ingester FROM nidp.source_registry
                    WHERE is_active IS NOT FALSE
                    ORDER BY ingester"""
            )
            feeds = [r["ingester"] for r in rows]

    # We do not block on LLM calls; persist run state and process sequentially.
    # For UX, just return what we attempted and a per-feed summary.
    results: list[dict[str, Any]] = []
    for feed in feeds:
        # Resolve ingester → table name via best-effort lookup. Many
        # ingesters write to a single dominant table; AI author tries
        # the ingester-name first and falls back via information_schema.
        try:
            out = await expectation_author.propose_expectations(
                feed,
                sample_size=body.sample_size,
                failure_history_days=body.failure_history_days,
            )
            results.append({
                "feed": feed,
                "ok": True,
                "proposals_count": out["proposals_count"],
                "written_count": out["written_count"],
            })
        except Exception as e:                  # noqa: BLE001
            results.append({"feed": feed, "ok": False, "error": str(e)[:240]})
    return {"attempted": len(feeds), "results": results}
