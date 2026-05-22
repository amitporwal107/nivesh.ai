"""Read-side queries for snapshots + holdings."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg


@dataclass(frozen=True)
class SnapshotSummary:
    id: UUID
    source_type: str
    statement_from: dt.date
    statement_to: dt.date
    generated_at: dt.datetime
    is_active: bool
    total_value: Decimal | None
    holdings_count: int


async def list_for_pan(
    conn: "asyncpg.Connection", pan_hash: str, *, limit: int = 50,
) -> list[SnapshotSummary]:
    rows = await conn.fetch(
        """
        SELECT s.id, s.source_type, s.statement_from, s.statement_to,
               s.generated_at, s.is_active, s.total_value,
               (SELECT count(*) FROM portfolio_ingestion.holdings h
                  WHERE h.snapshot_id = s.id) AS holdings_count
          FROM portfolio_ingestion.snapshots s
         WHERE s.pan_hash = $1
         ORDER BY s.statement_to DESC, s.created_at DESC
         LIMIT $2
        """,
        pan_hash, limit,
    )
    return [
        SnapshotSummary(
            id=r["id"], source_type=r["source_type"],
            statement_from=r["statement_from"], statement_to=r["statement_to"],
            generated_at=r["generated_at"], is_active=r["is_active"],
            total_value=r["total_value"], holdings_count=r["holdings_count"],
        )
        for r in rows
    ]


async def active_for_pan(
    conn: "asyncpg.Connection", pan_hash: str,
) -> SnapshotSummary | None:
    row = await conn.fetchrow(
        """
        SELECT s.id, s.source_type, s.statement_from, s.statement_to,
               s.generated_at, s.is_active, s.total_value,
               (SELECT count(*) FROM portfolio_ingestion.holdings h
                  WHERE h.snapshot_id = s.id) AS holdings_count
          FROM portfolio_ingestion.snapshots s
         WHERE s.pan_hash = $1 AND s.is_active = true
        """,
        pan_hash,
    )
    if row is None:
        return None
    return SnapshotSummary(
        id=row["id"], source_type=row["source_type"],
        statement_from=row["statement_from"], statement_to=row["statement_to"],
        generated_at=row["generated_at"], is_active=row["is_active"],
        total_value=row["total_value"], holdings_count=row["holdings_count"],
    )


async def by_id_for_pan(
    conn: "asyncpg.Connection", snapshot_id: UUID, pan_hash: str,
) -> SnapshotSummary | None:
    """Fetch a snapshot if and only if it belongs to ``pan_hash``.

    Filtering by pan_hash here (not just by id) is our authorisation
    boundary — a user can never read another user's snapshot, even with a
    valid UUID.
    """
    row = await conn.fetchrow(
        """
        SELECT s.id, s.source_type, s.statement_from, s.statement_to,
               s.generated_at, s.is_active, s.total_value,
               (SELECT count(*) FROM portfolio_ingestion.holdings h
                  WHERE h.snapshot_id = s.id) AS holdings_count
          FROM portfolio_ingestion.snapshots s
         WHERE s.id = $1 AND s.pan_hash = $2
        """,
        snapshot_id, pan_hash,
    )
    if row is None:
        return None
    return SnapshotSummary(
        id=row["id"], source_type=row["source_type"],
        statement_from=row["statement_from"], statement_to=row["statement_to"],
        generated_at=row["generated_at"], is_active=row["is_active"],
        total_value=row["total_value"], holdings_count=row["holdings_count"],
    )


async def holdings_of(
    conn: "asyncpg.Connection", snapshot_id: UUID,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, asset_class, isin, amfi_code, folio, scheme_code,
               amc, name, quantity, value, source_trace
          FROM portfolio_ingestion.holdings
         WHERE snapshot_id = $1
         ORDER BY value DESC
        """,
        snapshot_id,
    )
    return [dict(r) for r in rows]
