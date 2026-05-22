"""GET /api/portfolio/* — read-side endpoints.

  * GET /api/portfolio/me                  — current active snapshot + holdings
  * GET /api/portfolio/snapshots           — list of historical snapshots
  * GET /api/portfolio/snapshots/{id}      — one snapshot + holdings

All three are scoped to the caller's pan_hash via X-User-External-Id, so a
valid UUID for someone else's snapshot returns 404 rather than 403.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict

from ..db.pool import get_pool
from ..db.repositories import snapshots as snap_repo
from ..schemas.portfolio import PortfolioResponse
from ..schemas.snapshot import HoldingRow
from ..services.portfolio_view import assemble

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio-read"])


# ── Tiny auth helper: header → (user_id, pan_hash) ───────────────────────


async def _user_lookup(external_id: str) -> tuple[UUID, str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, pan_hash FROM portfolio_ingestion.users WHERE external_id = $1",
            external_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return row["id"], row["pan_hash"]


async def current_user(
    x_user_external_id: Annotated[str, Header(alias="X-User-External-Id")],
) -> tuple[UUID, str]:
    return await _user_lookup(x_user_external_id)


# ── Response models ──────────────────────────────────────────────────────


class SnapshotItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    source_type: str
    statement_from: str          # ISO date
    statement_to: str
    generated_at: str            # ISO datetime
    is_active: bool
    total_value: Decimal | None
    holdings_count: int


class SnapshotsList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshots: list[SnapshotItem]


class SnapshotDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: SnapshotItem
    portfolio: PortfolioResponse


# ── Endpoints ────────────────────────────────────────────────────────────


def _to_item(s) -> SnapshotItem:
    return SnapshotItem(
        id=s.id, source_type=s.source_type,
        statement_from=s.statement_from.isoformat(),
        statement_to=s.statement_to.isoformat(),
        generated_at=s.generated_at.isoformat(),
        is_active=s.is_active, total_value=s.total_value,
        holdings_count=s.holdings_count,
    )


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_me(
    user: Annotated[tuple[UUID, str], Depends(current_user)],
) -> SnapshotDetail:
    _, pan_hash = user
    pool = await get_pool()
    async with pool.acquire() as conn:
        active = await snap_repo.active_for_pan(conn, pan_hash)
        if active is None:
            raise HTTPException(status_code=404, detail="no active snapshot")
        rows = await snap_repo.holdings_of(conn, active.id)

    holdings = [HoldingRow(**_holding_row_compat(r)) for r in rows]
    return SnapshotDetail(snapshot=_to_item(active), portfolio=assemble(holdings))


@router.get("/snapshots", status_code=status.HTTP_200_OK)
async def list_snapshots(
    user: Annotated[tuple[UUID, str], Depends(current_user)],
    limit: int = 50,
) -> SnapshotsList:
    _, pan_hash = user
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await snap_repo.list_for_pan(conn, pan_hash, limit=min(limit, 200))
    return SnapshotsList(snapshots=[_to_item(s) for s in rows])


@router.get("/snapshots/{snapshot_id}", status_code=status.HTTP_200_OK)
async def get_snapshot(
    snapshot_id: Annotated[UUID, Path()],
    user: Annotated[tuple[UUID, str], Depends(current_user)],
) -> SnapshotDetail:
    _, pan_hash = user
    pool = await get_pool()
    async with pool.acquire() as conn:
        snap = await snap_repo.by_id_for_pan(conn, snapshot_id, pan_hash)
        if snap is None:
            raise HTTPException(status_code=404, detail="snapshot not found")
        rows = await snap_repo.holdings_of(conn, snap.id)

    holdings = [HoldingRow(**_holding_row_compat(r)) for r in rows]
    return SnapshotDetail(snapshot=_to_item(snap), portfolio=assemble(holdings))


def _holding_row_compat(row: dict) -> dict:
    """Reshape an asyncpg row dict into the HoldingRow ctor's kwargs.

    asyncpg may return JSONB as a string for older driver versions; normalise.
    """
    import json
    trace = row.get("source_trace")
    if isinstance(trace, str):
        trace = json.loads(trace)
    return dict(
        asset_class=row["asset_class"],
        isin=row.get("isin"),
        amfi_code=row.get("amfi_code"),
        folio=row.get("folio"),
        scheme_code=row.get("scheme_code"),
        amc=row.get("amc"),
        name=row["name"],
        quantity=row["quantity"],
        value=row["value"],
        source_trace=trace if isinstance(trace, dict) else {},
    )
