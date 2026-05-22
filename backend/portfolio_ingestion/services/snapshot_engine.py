"""Snapshot activation transaction — the heart of the platform.

PRD §7. Inside one Postgres transaction:

  1. ``pg_advisory_xact_lock(hashtext(pan_hash))`` to serialise concurrent
     ingests for the same PAN.
  2. Look up the current active snapshot.
  3. Decide via :mod:`portfolio_ingestion.services.source_priority` whether the
     incoming snapshot should become active.
  4. If yes: deactivate the loser, insert + activate the incoming, replace
     all rows in ``holdings`` for this PAN.
  5. If no: insert the incoming with ``is_active=false`` so it's archived but
     not promoted.

The whole thing is one transaction, so any failure rolls back cleanly and
the previously-active snapshot stays active (PRD §9 failure recovery).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from ..db.pool import get_pool
from ..schemas.snapshot import ActivationDecision, ActivationRequest
from .source_priority import (
    Method,
    SnapshotKey,
    SourceType,
    incoming_wins,
    method_priority,
)

if TYPE_CHECKING:
    import asyncpg

log = logging.getLogger(__name__)


async def activate(req: ActivationRequest) -> ActivationDecision:
    """Run the activation TX. Returns what was decided + what was written."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _activate_on_conn(conn, req)


async def _activate_on_conn(
    conn: "asyncpg.Connection", req: ActivationRequest
) -> ActivationDecision:
    incoming_source = SourceType(req.source_type)
    try:
        incoming_method = Method(req.method)
    except ValueError:
        incoming_method = Method.UPLOAD  # safest default for unknowns

    async with conn.transaction():
        # 1) Serialise on PAN. hashtext() returns int4, pg_advisory_xact_lock
        #    auto-releases on COMMIT/ROLLBACK.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext($1))", req.pan_hash
        )

        # 2) Read current active (FOR UPDATE — within the same TX + lock).
        current_row = await conn.fetchrow(
            """
            SELECT id, source_type, statement_to::text AS statement_to,
                   ingestion_job_id
              FROM portfolio_ingestion.snapshots
             WHERE pan_hash = $1 AND is_active = true
             FOR UPDATE
            """,
            req.pan_hash,
        )

        # 3) Decide.
        if current_row is None:
            decision_reason = "no_current_active"
            incoming_active = True
        else:
            current_source = SourceType(current_row["source_type"])
            # The previous job's method drives the current's priority — fetch it.
            current_method_row = await conn.fetchrow(
                "SELECT method FROM portfolio_ingestion.ingestion_jobs WHERE id = $1",
                current_row["ingestion_job_id"],
            )
            current_method = (
                Method(current_method_row["method"])
                if current_method_row and current_method_row["method"] in Method.__members__.values()
                else Method.UPLOAD
            )

            incoming_key = SnapshotKey(
                source_type=incoming_source,
                statement_to=req.statement_to.isoformat(),
                method_priority=method_priority(incoming_method),
            )
            current_key = SnapshotKey(
                source_type=current_source,
                statement_to=current_row["statement_to"],
                method_priority=method_priority(current_method),
            )
            incoming_active = incoming_wins(incoming_key, current_key)

            if incoming_active:
                if incoming_source.is_ecas and not current_source.is_ecas:
                    decision_reason = "ecas_supersedes_mf"
                elif req.statement_to.isoformat() > current_row["statement_to"]:
                    decision_reason = "newer_statement"
                else:
                    decision_reason = "higher_method_priority"
            else:
                decision_reason = "stored_inactive_loses"

        # 4a) Deactivate loser if we're activating.
        deactivated_ids: list[UUID] = []
        if incoming_active and current_row is not None:
            deactivated_ids = [
                row["id"]
                for row in await conn.fetch(
                    """
                    UPDATE portfolio_ingestion.snapshots
                       SET is_active = false, deactivated_at = now()
                     WHERE pan_hash = $1 AND is_active = true
                     RETURNING id
                    """,
                    req.pan_hash,
                )
            ]

        # 4b) Insert the incoming snapshot.
        new_snapshot_id: UUID = await conn.fetchval(
            """
            INSERT INTO portfolio_ingestion.snapshots
                (pan_hash, source_type, statement_from, statement_to,
                 generated_at, ingestion_job_id, is_active, total_value)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            req.pan_hash,
            req.source_type,
            req.statement_from,
            req.statement_to,
            req.generated_at,
            req.job_id,
            incoming_active,
            req.total_value,
        )

        # 4c) Replace holdings when we activated.
        holdings_written = 0
        if incoming_active and req.holdings:
            await conn.execute(
                "DELETE FROM portfolio_ingestion.holdings WHERE pan_hash = $1",
                req.pan_hash,
            )
            rows = [
                (
                    req.pan_hash,
                    new_snapshot_id,
                    h.asset_class,
                    h.isin,
                    h.amfi_code,
                    h.folio,
                    h.scheme_code,
                    h.amc,
                    h.name,
                    h.quantity,
                    h.value,
                    h.source_trace,
                )
                for h in req.holdings
            ]
            await conn.executemany(
                """
                INSERT INTO portfolio_ingestion.holdings
                  (pan_hash, snapshot_id, asset_class, isin, amfi_code,
                   folio, scheme_code, amc, name, quantity, value, source_trace)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
                """,
                [
                    (
                        r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8],
                        r[9], r[10], _to_jsonb(r[11]),
                    )
                    for r in rows
                ],
            )
            holdings_written = len(rows)
        elif incoming_active and not req.holdings:
            # Activated a snapshot with no holdings; still clear the table
            # for this PAN so we don't carry stale rows from a previous active.
            await conn.execute(
                "DELETE FROM portfolio_ingestion.holdings WHERE pan_hash = $1",
                req.pan_hash,
            )

        log.info(
            "snapshot activation decided",
            extra={
                "eventType": "SNAPSHOT_ACTIVATION",
                "pan_hash_prefix": req.pan_hash[:8],
                "source_type": req.source_type,
                "method": req.method,
                "incoming_active": incoming_active,
                "reason": decision_reason,
                "deactivated": len(deactivated_ids),
                "holdings_written": holdings_written,
            },
        )

        return ActivationDecision(
            snapshot_id=new_snapshot_id,
            is_active=incoming_active,
            activated=incoming_active and len(deactivated_ids) >= 0,
            deactivated_snapshot_ids=deactivated_ids,
            holdings_written=holdings_written,
            reason=decision_reason,  # type: ignore[arg-type]
        )


def _to_jsonb(value: object) -> str:
    """asyncpg expects JSONB as a JSON-encoded text payload."""
    import json

    return json.dumps(value, default=str)
