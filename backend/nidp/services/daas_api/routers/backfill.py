"""DaaS API — backfill status endpoints.

Read-only: the actual backfill is started from the pod via SSH (a long
job that exceeds HTTP timeouts). This router exposes /v1/backfill/runs
+ /status so the UI can poll progress.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key

router = APIRouter(prefix="/backfill", tags=["backfill"], dependencies=[Depends(require_api_key)])


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
    return out


@router.get("/runs", summary="List recent backfill invocations")
async def list_runs(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT backfill_id::text, started_at, finished_at, status,
                      start_date, end_date, ingesters, wipe_first,
                      politeness_ms, parallel, auto_replay,
                      jobs_total, jobs_done, jobs_failed, rows_loaded,
                      replay_id::text, initiated_by, error
                 FROM audit.backfill_runs
                ORDER BY started_at DESC LIMIT $1""",
            limit,
        )
    return {"runs": [_row_to_dict(r) for r in rows]}


@router.get("/status/{backfill_id}", summary="Detailed backfill status incl. per-job grid")
async def status(
    backfill_id: str,
    ingester: Optional[str] = Query(None),
    job_status: Optional[str] = Query(None, pattern="^(PENDING|RUNNING|DONE|FAILED|SKIPPED)$"),
    limit: int = Query(1000, ge=1, le=5000),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            """SELECT backfill_id::text, started_at, finished_at, status,
                      start_date, end_date, ingesters, wipe_first,
                      politeness_ms, parallel, auto_replay,
                      jobs_total, jobs_done, jobs_failed, rows_loaded,
                      replay_id::text, initiated_by, error,
                      config_json::text AS config_json
                 FROM audit.backfill_runs WHERE backfill_id = $1::uuid""",
            backfill_id,
        )
        if not run:
            raise HTTPException(status_code=404, detail="backfill not found")

        wheres: List[str] = ["backfill_id = $1::uuid"]
        params: List[Any] = [backfill_id]
        if ingester:
            wheres.append(f"ingester = ${len(params) + 1}")
            params.append(ingester)
        if job_status:
            wheres.append(f"status = ${len(params) + 1}")
            params.append(job_status)
        params.append(limit)

        jobs = await conn.fetch(
            f"""SELECT target_date, ingester, status, started_at,
                       finished_at, rows_loaded, duration_ms, attempt,
                       error, log_tail
                  FROM audit.backfill_jobs
                 WHERE {' AND '.join(wheres)}
                 ORDER BY target_date DESC, ingester
                 LIMIT ${len(params)}""",
            *params,
        )

        # Per-ingester roll-up
        rollup = await conn.fetch(
            """SELECT ingester, status, count(*) AS n,
                      sum(coalesce(rows_loaded,0))::bigint AS rows
                 FROM audit.backfill_jobs
                WHERE backfill_id = $1::uuid
                GROUP BY ingester, status
                ORDER BY ingester, status""",
            backfill_id,
        )

    return {
        "run":     _row_to_dict(run),
        "jobs":    [_row_to_dict(j) for j in jobs],
        "rollup":  [_row_to_dict(r) for r in rollup],
    }
