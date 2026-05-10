"""DaaS API — Historical Replay & Backtesting endpoints.

Mounted at /v1/replay under the daas_api app. Runs the replay engine
(nidp.quality.replay) directly against the local NIDP Postgres pool so
the engine has fast, native warehouse access. The pod-side admin
backend proxies user requests here so the React UI can drive replays.

All endpoints require the standard X-API-Key header.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.quality.replay.engine import ReplayConfig, ReplayEngine
from nidp.quality.replay.policy import list_policies, get_policy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/replay", tags=["replay"], dependencies=[Depends(require_api_key)])


# ─────────────────────────────────────────────────────────────────
# Background-task registry (one task per replay; pruned opportunistically)
# ─────────────────────────────────────────────────────────────────
_RUNNING: Dict[str, asyncio.Task] = {}


# ─────────────────────────────────────────────────────────────────
# Pydantic
# ─────────────────────────────────────────────────────────────────
class StartReplayRequest(BaseModel):
    start_date:      date
    end_date:        date
    domains:         List[str] = Field(default_factory=lambda: ["mf", "equity"])
    policy_version:  str       = "v1"
    parallel:        int       = Field(default=4, ge=1, le=32)
    inject_failures: bool      = False
    reset_data:      bool      = False
    failure_seed:    Optional[int]   = None
    failure_rate:    float           = Field(default=0.10, ge=0.0, le=1.0)
    skip_weekends:   bool            = True

    @field_validator("end_date")
    @classmethod
    def _validate_window(cls, v, info):
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must be on or after start_date")
        if start and (v - start).days > 366 * 5:
            raise ValueError("replay window cannot exceed 5 years")
        return v

    @field_validator("domains")
    @classmethod
    def _validate_domains(cls, v):
        if not v:
            return ["mf", "equity"]
        for d in v:
            if d not in ("mf", "equity", "all"):
                raise ValueError(f"unknown domain: {d}")
        return v


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────
@router.get("/policies", summary="List registered scoring policies")
async def get_policies() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        policies = await list_policies(conn)
    return {"policies": [p.as_dict() for p in policies], "source": "db"}


async def _run_in_background(cfg: ReplayConfig, holder: Dict[str, Any]) -> None:
    """Execute the replay using the shared NIDP pool."""
    pool = await get_pool()

    def _on_started(replay_id: str) -> None:
        holder["replay_id"] = replay_id

    try:
        engine = ReplayEngine(pool, cfg, on_started=_on_started)
        result = await engine.run()
        holder["replay_id"] = engine.replay_id
        holder["result"]    = result
    except Exception as e:                                                # noqa: BLE001
        logger.exception("replay background task failed")
        holder["error"] = f"{type(e).__name__}: {str(e)[:500]}"


@router.post("/start", summary="Kick off a new replay (returns replay_id immediately)")
async def start_replay(req: StartReplayRequest) -> Dict[str, Any]:
    cfg = ReplayConfig(
        start_date=req.start_date,
        end_date=req.end_date,
        domains=req.domains,
        policy_version=req.policy_version,
        parallel=req.parallel,
        inject_failures=req.inject_failures,
        reset_data=req.reset_data,
        failure_seed=req.failure_seed,
        failure_rate=req.failure_rate,
        skip_weekends=req.skip_weekends,
        initiated_by="daas_api",
    )

    holder: Dict[str, Any] = {}
    task = asyncio.create_task(_run_in_background(cfg, holder))

    pending_key = f"pending_{id(task)}"
    _RUNNING[pending_key] = task
    for k in [k for k, t in _RUNNING.items() if t.done()]:
        _RUNNING.pop(k, None)

    deadline = asyncio.get_event_loop().time() + 5.0
    while "replay_id" not in holder and "error" not in holder:
        if asyncio.get_event_loop().time() > deadline or task.done():
            break
        await asyncio.sleep(0.05)

    if "error" in holder and "replay_id" not in holder:
        raise HTTPException(
            status_code=500,
            detail=f"replay engine failed to start: {holder['error']}",
        )

    return {
        "ok":         True,
        "replay_id":  holder.get("replay_id"),
        "status":     "RUNNING" if holder.get("replay_id") else "STARTING",
        "config":     cfg.__dict__ | {
            "start_date": cfg.start_date.isoformat(),
            "end_date":   cfg.end_date.isoformat(),
        },
    }


@router.get("/status/{replay_id}", summary="Replay status + statistics + live progress")
async def replay_status(replay_id: str) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            """
            SELECT replay_id::text, started_at, finished_at, status,
                   start_date, end_date, domains, policy_version, parallel,
                   inject_failures, reset_data, dates_total, dates_processed,
                   dates_failed, error, initiated_by, config_json::text AS config_json
              FROM audit.replay_runs
             WHERE replay_id = $1::uuid
            """,
            replay_id,
        )
        if not run:
            raise HTTPException(status_code=404, detail="replay not found")

        stats = await conn.fetchrow(
            """
            SELECT total_evaluations, pass_count, review_count, fail_count,
                   avg_overall_score, p50_overall_score, p10_overall_score,
                   cert_gold, cert_silver, cert_review, cert_rejected,
                   publish_auto, publish_review, publish_reject,
                   quarantine_count, exception_count, avg_duration_ms
              FROM audit.replay_statistics
             WHERE replay_id = $1::uuid
            """,
            replay_id,
        )
        live_processed = await conn.fetchval(
            "SELECT count(*) FROM audit.replay_dates WHERE replay_id = $1::uuid",
            replay_id,
        )
    return {
        "run":        _row_to_dict(run),
        "statistics": _row_to_dict(stats) if stats else None,
        "live":       {"rows_persisted": int(live_processed or 0)},
    }


@router.get("/runs", summary="List recent replays with summary stats")
async def list_runs(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.replay_id::text, r.started_at, r.finished_at, r.status,
                   r.start_date, r.end_date, r.domains, r.policy_version,
                   r.parallel, r.inject_failures, r.dates_total,
                   r.dates_processed, r.dates_failed, r.initiated_by, r.error,
                   s.avg_overall_score, s.pass_count, s.review_count,
                   s.fail_count, s.cert_gold, s.cert_silver, s.cert_review,
                   s.cert_rejected
              FROM audit.replay_runs r
              LEFT JOIN audit.replay_statistics s ON s.replay_id = r.replay_id
             ORDER BY r.started_at DESC
             LIMIT $1
            """,
            limit,
        )
    return {"runs": [_row_to_dict(r) for r in rows]}


@router.get("/runs/{replay_id}/dates", summary="Per-date outcomes for a replay")
async def replay_dates(
    replay_id: str,
    domain: Optional[str] = Query(None),
    gate_outcome: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
) -> Dict[str, Any]:
    pool = await get_pool()
    wheres: List[str] = ["replay_id = $1::uuid"]
    params: List[Any] = [replay_id]
    if domain:
        wheres.append(f"domain = ${len(params)+1}")
        params.append(domain)
    if gate_outcome:
        wheres.append(f"gate_outcome = ${len(params)+1}")
        params.append(gate_outcome)
    params.append(limit)
    sql = f"""
        SELECT target_date, domain, overall_score, confidence_score,
               accuracy, consistency, completeness, freshness, auditability,
               certification, publish_decision, gate_outcome,
               block_findings, rules_run, rules_failed, duration_ms, error
          FROM audit.replay_dates
         WHERE {' AND '.join(wheres)}
         ORDER BY target_date DESC, domain
         LIMIT ${len(params)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {"replay_id": replay_id, "dates": [_row_to_dict(r) for r in rows]}


@router.get("/runs/{replay_id}/failures", summary="Synthetic failures injected for the replay")
async def replay_failures(
    replay_id: str,
    limit: int = Query(500, ge=1, le=2000),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT failure_id::text, target_date, domain, failure_type,
                   target_table, rows_affected, detected, detected_by,
                   payload_json::text AS payload, injected_at
              FROM audit.replay_failures
             WHERE replay_id = $1::uuid
             ORDER BY target_date DESC, failure_type
             LIMIT $2
            """,
            replay_id, limit,
        )
    out = [_row_to_dict(r) for r in rows]
    total = len(out)
    detected = sum(1 for r in out if r.get("detected"))
    return {
        "replay_id":      replay_id,
        "failures":       out,
        "total":          total,
        "detected":       detected,
        "detection_rate": round(detected / total, 4) if total > 0 else None,
    }


@router.delete("/runs/{replay_id}", summary="Delete a replay and its per-date rows")
async def delete_run(replay_id: str) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM audit.replay_runs WHERE replay_id = $1::uuid",
            replay_id,
        )
    return {"ok": True, "deleted": res}


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return {}
    out: Dict[str, Any] = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, (list, tuple)):
            out[k] = list(v)
        else:
            out[k] = v
    if "config_json" in out and isinstance(out["config_json"], str):
        try:
            out["config_json"] = json.loads(out["config_json"])
        except (ValueError, TypeError):
            pass
    if "payload" in out and isinstance(out["payload"], str):
        try:
            out["payload"] = json.loads(out["payload"])
        except (ValueError, TypeError):
            pass
    return out
