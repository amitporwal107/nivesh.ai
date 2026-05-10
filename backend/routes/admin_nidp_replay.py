"""Admin → NIDP → Replay endpoints.

Drives the 90-day historical replay engine from the admin UI. The
engine itself runs against the NIDP Postgres warehouse (`NIDP_PG_DSN`);
this module is just the thin proxy that:

  1. Accepts a config payload, validates it.
  2. Creates an asyncpg pool against the NIDP DB.
  3. Spawns the replay as a fire-and-forget background task.
  4. Exposes status + history endpoints reading audit.replay_runs.

For local-dev pods that don't have NIDP_PG_DSN set, every endpoint
returns 503 with a helpful hint — same pattern as /diag and /catalog.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from deps import require_admin
from nidp.quality.replay.engine import ReplayConfig, ReplayEngine
from nidp.quality.replay.policy import list_policies

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/nidp/replay", tags=["admin-nidp-replay"])


def _nidp_dsn() -> Optional[str]:
    return (
        os.environ.get("NIDP_PG_DSN")
        or os.environ.get("NIDP_POSTGRES_URL")
        or os.environ.get("POSTGRES_URL")
    )


async def _open_pool() -> asyncpg.Pool:
    dsn = _nidp_dsn()
    if not dsn:
        raise HTTPException(
            status_code=503,
            detail=(
                "NIDP_PG_DSN not configured on this host. "
                "Set NIDP_PG_DSN (or POSTGRES_URL) to the NIDP TimescaleDB "
                "DSN to enable replay endpoints."
            ),
        )
    try:
        return await asyncpg.create_pool(dsn, min_size=1, max_size=8, command_timeout=60)
    except Exception as e:                                                # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"NIDP PG connect failed: {e}") from e


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
# Background-task registry — one running replay at a time per pool.
# ─────────────────────────────────────────────────────────────────
_RUNNING: Dict[str, asyncio.Task] = {}


async def _run_in_background(pool: asyncpg.Pool, cfg: ReplayConfig, replay_id_holder: Dict[str, Any]) -> None:
    try:
        engine = ReplayEngine(pool, cfg)
        result = await engine.run()
        replay_id_holder["replay_id"] = engine.replay_id
        replay_id_holder["result"]    = result
    except Exception as e:                                                # noqa: BLE001
        logger.exception("replay background task failed")
        replay_id_holder["error"] = f"{type(e).__name__}: {str(e)[:500]}"
    finally:
        await pool.close()


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────
@router.get("/policies")
async def get_policies(request: Request) -> Dict[str, Any]:
    await require_admin(request)
    # Graceful degrade: builtin policies don't need a DB.
    dsn = _nidp_dsn()
    if not dsn:
        policies = await list_policies(None)
        return {
            "policies": [p.as_dict() for p in policies],
            "source":   "builtin",
            "hint":     "NIDP_PG_DSN not set — showing built-in defaults; apply migration 044 on NIDP DB to register custom policies.",
        }
    try:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, command_timeout=10)
    except Exception as e:                                                # noqa: BLE001
        policies = await list_policies(None)
        return {
            "policies": [p.as_dict() for p in policies],
            "source":   "builtin",
            "warning":  f"NIDP DB unreachable ({type(e).__name__}); showing built-in defaults",
        }
    try:
        async with pool.acquire() as conn:
            policies = await list_policies(conn)
        return {"policies": [p.as_dict() for p in policies], "source": "db"}
    finally:
        await pool.close()


@router.post("/start")
async def start_replay(req: StartReplayRequest, request: Request) -> Dict[str, Any]:
    await require_admin(request)
    pool = await _open_pool()
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
        initiated_by=getattr(request.state, "user_email", None) or "admin",
    )

    holder: Dict[str, Any] = {}
    task = asyncio.create_task(_run_in_background(pool, cfg, holder))

    # Park the task so the event loop doesn't GC it. Use a placeholder
    # key until the engine writes back the real replay_id, then
    # overwrite. Cleanup is opportunistic (next /start prunes done).
    pending_key = f"pending_{id(task)}"
    _RUNNING[pending_key] = task
    for k in [k for k, t in _RUNNING.items() if t.done()]:
        _RUNNING.pop(k, None)

    # Brief settle — give the engine 1.5s to insert the replay_runs row
    # so we can return a real replay_id (UI then polls /status).
    try:
        await asyncio.wait_for(_wait_for_replay_id(pool, holder, task), timeout=2.0)
    except asyncio.TimeoutError:
        pass

    replay_id = holder.get("replay_id") or _last_replay_id(holder)
    return {
        "ok":         True,
        "replay_id":  replay_id,
        "status":     "RUNNING",
        "config":     cfg.__dict__ | {
            "start_date": cfg.start_date.isoformat(),
            "end_date":   cfg.end_date.isoformat(),
        },
    }


async def _wait_for_replay_id(pool: asyncpg.Pool, holder: Dict[str, Any], task: asyncio.Task) -> None:
    # We don't want to mutate `pool` after start_replay closes it via
    # the background task — so query directly via a fresh pool would
    # double-connect. Instead poll the holder dict the engine writes to.
    while not task.done() and "replay_id" not in holder:
        await asyncio.sleep(0.1)


def _last_replay_id(holder: Dict[str, Any]) -> Optional[str]:
    return holder.get("replay_id")


@router.get("/status/{replay_id}")
async def replay_status(replay_id: str, request: Request) -> Dict[str, Any]:
    await require_admin(request)
    pool = await _open_pool()
    try:
        async with pool.acquire() as conn:
            run = await conn.fetchrow(
                """
                SELECT r.replay_id::text, r.started_at, r.finished_at,
                       r.status, r.start_date, r.end_date, r.domains,
                       r.policy_version, r.parallel, r.inject_failures,
                       r.reset_data, r.dates_total, r.dates_processed,
                       r.dates_failed, r.error, r.initiated_by,
                       r.config_json::text AS config_json
                  FROM audit.replay_runs r
                 WHERE r.replay_id = $1::uuid
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

            # Live progress while RUNNING — count rows actually inserted
            # by background workers.
            live_processed = await conn.fetchval(
                "SELECT count(*) FROM audit.replay_dates WHERE replay_id = $1::uuid",
                replay_id,
            )

        return {
            "run":        _row_to_dict(run),
            "statistics": _row_to_dict(stats) if stats else None,
            "live": {
                "rows_persisted": int(live_processed or 0),
            },
        }
    finally:
        await pool.close()


@router.get("/runs")
async def list_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    await require_admin(request)
    pool = await _open_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.replay_id::text, r.started_at, r.finished_at,
                       r.status, r.start_date, r.end_date, r.domains,
                       r.policy_version, r.parallel, r.inject_failures,
                       r.dates_total, r.dates_processed, r.dates_failed,
                       r.initiated_by, r.error,
                       s.avg_overall_score, s.pass_count, s.review_count,
                       s.fail_count, s.cert_gold, s.cert_silver, s.cert_review,
                       s.cert_rejected
                  FROM audit.replay_runs r
                  LEFT JOIN audit.replay_statistics s
                    ON s.replay_id = r.replay_id
                 ORDER BY r.started_at DESC
                 LIMIT $1
                """,
                limit,
            )
        return {"runs": [_row_to_dict(r) for r in rows]}
    finally:
        await pool.close()


@router.get("/runs/{replay_id}/dates")
async def replay_dates(
    replay_id: str,
    request: Request,
    domain: Optional[str] = Query(None),
    gate_outcome: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
) -> Dict[str, Any]:
    await require_admin(request)
    pool = await _open_pool()
    try:
        wheres = ["replay_id = $1::uuid"]
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
    finally:
        await pool.close()


@router.get("/runs/{replay_id}/failures")
async def replay_failures(
    replay_id: str,
    request: Request,
    limit: int = Query(500, ge=1, le=2000),
) -> Dict[str, Any]:
    await require_admin(request)
    pool = await _open_pool()
    try:
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
        # Detection rate summary
        total = len(out)
        detected = sum(1 for r in out if r.get("detected"))
        return {
            "replay_id":      replay_id,
            "failures":       out,
            "total":          total,
            "detected":       detected,
            "detection_rate": round(detected / total, 4) if total > 0 else None,
        }
    finally:
        await pool.close()


@router.delete("/runs/{replay_id}")
async def delete_run(replay_id: str, request: Request) -> Dict[str, Any]:
    await require_admin(request)
    pool = await _open_pool()
    try:
        async with pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM audit.replay_runs WHERE replay_id = $1::uuid",
                replay_id,
            )
        return {"ok": True, "deleted": res}
    finally:
        await pool.close()


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
    # Parse json columns shipped as text
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
