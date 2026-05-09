"""Quality score, certification, and consistency API routes.

Endpoints:
  GET   /quality                     — latest quality score per domain
  GET   /certification               — current certification tier per date+domain
  GET   /consistency                 — latest consistency run summary
  GET   /consistency/findings        — individual consistency findings
  GET   /publish-gate                — actionable PASS/REVIEW/FAIL per date
  GET   /exception-queue             — REVIEW items (ops dashboard)
  PATCH /exception-queue/{queue_id}  — resolve / override an exception
  GET   /quarantine                  — FAIL-quarantined dates
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.query_api.auth import require_bearer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["quality"], dependencies=[Depends(require_bearer)])


def _date(v: Any) -> Optional[str]:
    return v.isoformat() if v else None


# ── GET /quality ─────────────────────────────────────────────────────
@router.get("/quality")
async def quality_latest(
    domain: Optional[str] = Query(None, description="mf | equity | all"),
    limit:  int           = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    """Latest quality score per (target_date, domain), newest first."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT target_date, domain, overall_score,
                       accuracy, consistency, completeness, freshness, auditability,
                       confidence_score, certification, publish_decision, computed_at
                  FROM nidp.v_data_certification
                 WHERE ($1::text IS NULL OR domain = $1)
                 ORDER BY target_date DESC, domain
                 LIMIT $2
                """,
                domain, limit,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("quality_latest: %s", exc)
            return {"quality": [], "error": str(exc)[:300]}

    return {
        "quality": [
            {
                "target_date":    _date(r["target_date"]),
                "domain":         r["domain"],
                "overall_score":  float(r["overall_score"]) if r["overall_score"] else None,
                "accuracy":       float(r["accuracy"])       if r["accuracy"]       else None,
                "consistency":    float(r["consistency"])    if r["consistency"]    else None,
                "completeness":   float(r["completeness"])   if r["completeness"]   else None,
                "freshness":      float(r["freshness"])      if r["freshness"]      else None,
                "auditability":   float(r["auditability"])   if r["auditability"]   else None,
                "confidence":     float(r["confidence_score"]) if r["confidence_score"] else None,
                "certification":  r["certification"],
                "publish_decision": r["publish_decision"],
                "computed_at":    _date(r["computed_at"]),
            }
            for r in rows
        ],
        "error": None,
    }


# ── GET /certification ───────────────────────────────────────────────
@router.get("/certification")
async def certification(
    domain: Optional[str] = Query(None),
    limit:  int           = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    """Certified dates — only dates that passed the quality gate."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT cert_id, target_date, domain,
                       overall_score, certification, certified_at
                  FROM nidp.certified_dates
                 WHERE ($1::text IS NULL OR domain = $1)
                 ORDER BY target_date DESC, domain
                 LIMIT $2
                """,
                domain, limit,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("certification: %s", exc)
            return {"certified": [], "error": str(exc)[:300]}

    return {
        "certified": [
            {
                "target_date":   _date(r["target_date"]),
                "domain":        r["domain"],
                "overall_score": float(r["overall_score"]) if r["overall_score"] else None,
                "certification": r["certification"],
                "certified_at":  _date(r["certified_at"]),
            }
            for r in rows
        ],
        "error": None,
    }


# ── GET /consistency ─────────────────────────────────────────────────
@router.get("/consistency")
async def consistency_runs(
    domain: Optional[str] = Query(None),
    limit:  int           = Query(30, ge=1, le=200),
) -> Dict[str, Any]:
    """Latest consistency run per (target_date, domain)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (target_date, domain)
                    run_id, target_date, domain, status,
                    rules_run, rules_failed, findings_count, has_block, started_at
                  FROM nidp.consistency_runs
                 WHERE ($1::text IS NULL OR domain = $1)
                 ORDER BY target_date DESC, domain, started_at DESC
                 LIMIT $2
                """,
                domain, limit,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("consistency_runs: %s", exc)
            return {"consistency": [], "error": str(exc)[:300]}

    return {
        "consistency": [
            {
                "target_date":    _date(r["target_date"]),
                "domain":         r["domain"],
                "status":         r["status"],
                "rules_run":      r["rules_run"],
                "rules_failed":   r["rules_failed"],
                "findings_count": r["findings_count"],
                "has_block":      r["has_block"],
                "started_at":     _date(r["started_at"]),
            }
            for r in rows
        ],
        "error": None,
    }


# ── GET /consistency/findings ────────────────────────────────────────
@router.get("/consistency/findings")
async def consistency_findings(
    domain:     Optional[str] = Query(None),
    dimension:  Optional[str] = Query(None, description="CROSS_SOURCE|INTERNAL|TEMPORAL|API|POINT_IN_TIME"),
    severity:   Optional[str] = Query(None, description="INFO|WARN|ERROR|CRITICAL"),
    entity_id:  Optional[str] = Query(None),
    limit:      int           = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Individual consistency findings, newest first."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT finding_id, target_date, domain, dimension,
                       rule_name, severity, failure_class,
                       entity_type, entity_id, field_name,
                       source_a, value_a, source_b, value_b,
                       deviation_pct, message, detected_at
                  FROM nidp.consistency_findings
                 WHERE ($1::text IS NULL OR domain    = $1)
                   AND ($2::text IS NULL OR dimension = $2)
                   AND ($3::text IS NULL OR severity  = $3)
                   AND ($4::text IS NULL OR entity_id = $4)
                 ORDER BY detected_at DESC
                 LIMIT $5
                """,
                domain, dimension, severity, entity_id, limit,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("consistency_findings: %s", exc)
            return {"findings": [], "error": str(exc)[:300]}

    return {
        "findings": [
            {
                "target_date":   _date(r["target_date"]),
                "domain":        r["domain"],
                "dimension":     r["dimension"],
                "rule_name":     r["rule_name"],
                "severity":      r["severity"],
                "failure_class": r["failure_class"],
                "entity_type":   r["entity_type"],
                "entity_id":     r["entity_id"],
                "field_name":    r["field_name"],
                "source_a":      r["source_a"],
                "value_a":       r["value_a"],
                "source_b":      r["source_b"],
                "value_b":       r["value_b"],
                "deviation_pct": float(r["deviation_pct"]) if r["deviation_pct"] else None,
                "message":       r["message"],
                "detected_at":   _date(r["detected_at"]),
            }
            for r in rows
        ],
        "error": None,
    }


# ── GET /publish-gate ────────────────────────────────────────────────
@router.get("/publish-gate")
async def publish_gate(
    domain: Optional[str] = Query(None),
    limit:  int           = Query(30, ge=1, le=90),
) -> Dict[str, Any]:
    """Go/no-go publish decision per (date, domain) from v_publish_gate."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT target_date, domain, overall_score,
                       certification, publish_decision,
                       confidence_score, consistency_blocks, gate_decision
                  FROM nidp.v_publish_gate
                 WHERE ($1::text IS NULL OR domain = $1)
                 ORDER BY target_date DESC, domain
                 LIMIT $2
                """,
                domain, limit,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("publish_gate: %s", exc)
            return {"gate": [], "error": str(exc)[:300]}

    return {
        "gate": [
            {
                "target_date":        _date(r["target_date"]),
                "domain":             r["domain"],
                "overall_score":      float(r["overall_score"])    if r["overall_score"]    else None,
                "certification":      r["certification"],
                "publish_decision":   r["publish_decision"],
                "confidence_score":   float(r["confidence_score"]) if r["confidence_score"] else None,
                "consistency_blocks": r["consistency_blocks"],
                "gate_decision":      r["gate_decision"],
            }
            for r in rows
        ],
        "error": None,
    }


# ── GET /exception-queue ─────────────────────────────────────────────
@router.get("/exception-queue")
async def exception_queue(
    resolved: Optional[bool] = Query(False),
    limit:    int             = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Items in the manual-review queue (ops dashboard)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT queue_id, target_date, domain, outcome,
                       quality_score, confidence_score, block_findings,
                       reason, created_at, resolved, resolved_at, resolution_note
                  FROM nidp.exception_queue
                 WHERE ($1::boolean IS NULL OR resolved = $1)
                 ORDER BY created_at DESC
                 LIMIT $2
                """,
                resolved, limit,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("exception_queue: %s", exc)
            return {"exceptions": [], "error": str(exc)[:300]}

    return {
        "exceptions": [
            {
                "queue_id":        str(r["queue_id"]),
                "target_date":     _date(r["target_date"]),
                "domain":          r["domain"],
                "outcome":         r["outcome"],
                "quality_score":   float(r["quality_score"])   if r["quality_score"]   else None,
                "confidence":      float(r["confidence_score"]) if r["confidence_score"] else None,
                "block_findings":  r["block_findings"],
                "reason":          r["reason"],
                "created_at":      _date(r["created_at"]),
                "resolved":        r["resolved"],
                "resolved_at":     _date(r["resolved_at"]),
                "resolution_note": r["resolution_note"],
            }
            for r in rows
        ],
        "error": None,
    }


# ── PATCH /exception-queue/{queue_id} ────────────────────────────────
@router.patch("/exception-queue/{queue_id}")
async def resolve_exception(
    queue_id:        str  = Path(..., description="UUID from exception_queue.queue_id"),
    action:          str  = Body(..., embed=True, description="APPROVE | REJECT | OVERRIDE | ESCALATE"),
    resolution_note: str  = Body("",  embed=True),
    resolved_by:     str  = Body("ops", embed=True),
) -> Dict[str, Any]:
    """Mark an exception queue item as resolved (ops action)."""
    if action not in ("APPROVE", "REJECT", "OVERRIDE", "ESCALATE"):
        raise HTTPException(status_code=422, detail=f"Invalid action: {action}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                UPDATE nidp.exception_queue
                   SET resolved        = TRUE,
                       resolved_at     = NOW(),
                       resolved_by     = $2,
                       resolution_note = $3,
                       outcome         = $4
                 WHERE queue_id = $1::uuid
                RETURNING queue_id, target_date, domain, outcome, resolved_at
                """,
                queue_id, resolved_by,
                f"[{action}] {resolution_note}".strip(),
                action,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("resolve_exception: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)[:300]) from exc

    if not row:
        raise HTTPException(status_code=404, detail=f"queue_id {queue_id} not found")

    return {
        "queue_id":    str(row["queue_id"]),
        "target_date": _date(row["target_date"]),
        "domain":      row["domain"],
        "outcome":     row["outcome"],
        "resolved_at": _date(row["resolved_at"]),
        "error": None,
    }


# ── GET /quarantine ──────────────────────────────────────────────────
@router.get("/quarantine")
async def quarantine_log(
    domain: Optional[str] = Query(None),
    limit:  int           = Query(30, ge=1, le=200),
) -> Dict[str, Any]:
    """Dates condemned by the quality gate (FAIL outcome → quarantine)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT quarantine_id, target_date, domain,
                       quality_score, confidence_score, block_findings,
                       reason, quarantined_at
                  FROM nidp.quarantine_log
                 WHERE ($1::text IS NULL OR domain = $1)
                 ORDER BY quarantined_at DESC
                 LIMIT $2
                """,
                domain, limit,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("quarantine_log: %s", exc)
            return {"quarantine": [], "error": str(exc)[:300]}

    return {
        "quarantine": [
            {
                "quarantine_id":   str(r["quarantine_id"]),
                "target_date":     _date(r["target_date"]),
                "domain":          r["domain"],
                "quality_score":   float(r["quality_score"])    if r["quality_score"]    else None,
                "confidence":      float(r["confidence_score"]) if r["confidence_score"] else None,
                "block_findings":  r["block_findings"],
                "reason":          r["reason"],
                "quarantined_at":  _date(r["quarantined_at"]),
            }
            for r in rows
        ],
        "error": None,
    }
