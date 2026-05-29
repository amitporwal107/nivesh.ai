"""Gate 6 — /v1/dq/* endpoints.

GET /v1/dq/status
    Full DQ envelope for the latest trading day:
    - Overall dq_status (GREEN / AMBER / RED)
    - Degraded feed list with staleness + impact
    - Gate 3 snapshot_status breakdown
    - Links to dq.gate_verdicts for drill-down

GET /v1/dq/verdicts
    Recent gate verdicts (paginated, latest first).

GET /v1/dq/dlq
    Outstanding DLQ messages (replay_status = PENDING).

These endpoints are read-only; they expose the dq.* tables maintained
by the Quality Gates system (migration 077).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from nidp.services.daas_api.auth import require_api_key as require_key

router = APIRouter(prefix="/dq", tags=["dq"])


# ── Response models ───────────────────────────────────────────────────────────

class DegradedFeed(BaseModel):
    feed: str
    last_successful_run: Optional[datetime]
    staleness_days: Optional[float]
    impact: str


class DQEnvelope(BaseModel):
    as_of_date: str
    dq_status: str                  # GREEN | AMBER | RED
    snapshot_id: Optional[str]
    feeds_ready: list[str]
    feeds_blocked: list[str]
    feeds_amber: list[str]
    degraded_feeds: list[DegradedFeed]
    gate_verdicts_uri: str


class GateVerdict(BaseModel):
    id: str
    gate_id: int
    feed: Optional[str]
    target_date: str
    verdict: str
    severity: str
    created_at: datetime
    details: Any


class DLQFinding(BaseModel):
    id: str
    gate_id: int
    feed: str
    target_date: Optional[str]
    failure_reason: str
    severity: str
    replay_status: str
    created_at: datetime


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=DQEnvelope)
async def get_dq_status(
    as_of: Optional[date] = Query(default=None, description="Date (default: latest)"),
    key=Depends(require_key),
):
    """Return the full DQ envelope for a given trading day."""
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        if as_of:
            snap_row = await conn.fetchrow(
                "SELECT * FROM dq.snapshot_status WHERE target_date = $1", as_of
            )
        else:
            snap_row = await conn.fetchrow(
                "SELECT * FROM dq.snapshot_status ORDER BY target_date DESC LIMIT 1"
            )

        if snap_row is None:
            return DQEnvelope(
                as_of_date=str(as_of or date.today()),
                dq_status="GREEN",
                snapshot_id=None,
                feeds_ready=[],
                feeds_blocked=[],
                feeds_amber=[],
                degraded_feeds=[],
                gate_verdicts_uri="/v1/dq/verdicts",
            )

        target_date = snap_row["target_date"]
        raw_status  = snap_row["status"]
        dq_status   = _map_status(raw_status)

        # Fetch degraded feeds with staleness
        degraded: list[DegradedFeed] = []
        for feed in (snap_row["feeds_blocked"] or []) + (snap_row["feeds_amber"] or []):
            staleness_row = await conn.fetchrow(
                """
                SELECT MAX(created_at) AS last_ok
                FROM dq.gate_verdicts
                WHERE feed = $1
                  AND gate_id = 3
                  AND verdict = 'PASS'
                """,
                feed,
            )
            last_ok = staleness_row["last_ok"] if staleness_row else None
            staleness_days = (
                (datetime.utcnow() - last_ok.replace(tzinfo=None)).total_seconds() / 86400
                if last_ok else None
            )
            impact = "Blocked from derivation chain" if feed in (snap_row["feeds_blocked"] or []) \
                else "Degraded scoring inputs"
            degraded.append(DegradedFeed(
                feed=feed,
                last_successful_run=last_ok,
                staleness_days=round(staleness_days, 1) if staleness_days else None,
                impact=impact,
            ))

        return DQEnvelope(
            as_of_date=str(target_date),
            dq_status=dq_status,
            snapshot_id=str(snap_row["id"]) if snap_row["id"] else None,
            feeds_ready=snap_row["feeds_ready"] or [],
            feeds_blocked=snap_row["feeds_blocked"] or [],
            feeds_amber=snap_row["feeds_amber"] or [],
            degraded_feeds=degraded,
            gate_verdicts_uri=f"/v1/dq/verdicts?target_date={target_date}",
        )


@router.get("/verdicts", response_model=list[GateVerdict])
async def list_gate_verdicts(
    target_date: Optional[date] = Query(default=None),
    gate_id: Optional[int]      = Query(default=None, ge=1, le=7),
    feed:    Optional[str]      = Query(default=None),
    limit:   int                = Query(default=50, le=500),
    offset:  int                = Query(default=0),
    key=Depends(require_key),
):
    """List recent gate verdicts, optionally filtered by date/gate/feed."""
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()

    filters = []
    params  = []
    n = 1
    if target_date:
        filters.append(f"target_date = ${n}"); params.append(target_date); n += 1
    if gate_id is not None:
        filters.append(f"gate_id = ${n}"); params.append(gate_id); n += 1
    if feed:
        filters.append(f"feed = ${n}"); params.append(feed); n += 1

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params += [limit, offset]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id::text, gate_id, feed, target_date::text, verdict,
                   severity, created_at, details
            FROM dq.gate_verdicts
            {where}
            ORDER BY created_at DESC
            LIMIT ${n} OFFSET ${n+1}
            """,
            *params,
        )

    return [
        GateVerdict(
            id=r["id"],
            gate_id=r["gate_id"],
            feed=r["feed"],
            target_date=r["target_date"],
            verdict=r["verdict"],
            severity=r["severity"],
            created_at=r["created_at"],
            details=r["details"],
        )
        for r in rows
    ]


@router.get("/dlq", response_model=list[DLQFinding])
async def list_dlq_findings(
    replay_status: str  = Query(default="PENDING"),
    feed: Optional[str] = Query(default=None),
    limit: int          = Query(default=50, le=500),
    key=Depends(require_key),
):
    """List DLQ findings (default: PENDING — awaiting replay or drop)."""
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()

    if feed:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text, gate_id, feed, target_date::text,
                       failure_reason, severity, replay_status, created_at
                FROM dq.dlq_findings
                WHERE replay_status = $1 AND feed = $2
                ORDER BY created_at DESC LIMIT $3
                """,
                replay_status, feed, limit,
            )
    else:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text, gate_id, feed, target_date::text,
                       failure_reason, severity, replay_status, created_at
                FROM dq.dlq_findings
                WHERE replay_status = $1
                ORDER BY created_at DESC LIMIT $2
                """,
                replay_status, limit,
            )

    return [
        DLQFinding(
            id=r["id"],
            gate_id=r["gate_id"],
            feed=r["feed"],
            target_date=r["target_date"],
            failure_reason=r["failure_reason"],
            severity=r["severity"],
            replay_status=r["replay_status"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def _map_status(raw: str) -> str:
    return {"PASS": "GREEN", "PARTIAL": "AMBER", "PENDING": "AMBER", "BLOCKED": "RED"}.get(raw, "AMBER")
