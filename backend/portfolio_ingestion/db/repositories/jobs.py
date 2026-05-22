"""Ingestion-jobs repository.

The job row is created up-front (before parsing / snapshot activation) so we
have a stable id to thread through audit, raw-archive references and async
PDF downloads. Idempotency lives here: a second call with the same
``(pan_hash, checksum)`` returns the same id with ``is_new=False``.

For the ``cdsl_fetch`` flow there is no PDF to checksum — every call lands a
new row (the database UNIQUE constraint allows multiple NULL checksums per
PAN by default, which is what we want).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg


@dataclasses.dataclass(frozen=True)
class JobRow:
    id: UUID
    user_id: UUID
    pan_hash: str
    source_type: str
    method: str
    checksum: str | None
    status: str
    pdf_gcs_key: str | None
    pdf_status: str | None
    raw_data_ref: str | None
    failure_reason: str | None
    created_at: dt.datetime
    completed_at: dt.datetime | None


VALID_STATUSES = frozenset({"pending_upload", "received", "parsing", "activated", "failed"})


def _row_to_jobrow(row: "asyncpg.Record") -> JobRow:
    return JobRow(
        id=row["id"],
        user_id=row["user_id"],
        pan_hash=row["pan_hash"],
        source_type=row["source_type"],
        method=row["method"],
        checksum=row["checksum"],
        status=row["status"],
        pdf_gcs_key=row["pdf_gcs_key"],
        pdf_status=row["pdf_status"],
        raw_data_ref=row["raw_data_ref"],
        failure_reason=row["failure_reason"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


async def upsert(
    conn: "asyncpg.Connection",
    *,
    user_id: UUID,
    pan_hash: str,
    source_type: str,
    method: str,
    checksum: str | None,
    pdf_gcs_key: str | None = None,
    pdf_status: str | None = None,
    status: str = "received",
) -> tuple[UUID, bool]:
    """Return ``(job_id, is_new)``.

    Idempotent on ``(pan_hash, checksum)`` when checksum is non-null. With a
    null checksum every call is treated as a fresh job (cdsl_fetch case).
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}")

    if checksum is None:
        # No idempotency key available — always insert.
        row = await conn.fetchrow(
            """
            INSERT INTO portfolio_ingestion.ingestion_jobs
                (user_id, pan_hash, source_type, method, checksum,
                 pdf_gcs_key, pdf_status, status)
            VALUES ($1, $2, $3, $4, NULL, $5, $6, $7)
            RETURNING id
            """,
            user_id, pan_hash, source_type, method,
            pdf_gcs_key, pdf_status, status,
        )
        return row["id"], True

    # Single round-trip: try to insert; if the unique key collides, capture
    # the existing id in a CTE. Postgres returns at most one row from the
    # winning branch, so we always know is_new from whether RETURNING fired.
    inserted = await conn.fetchrow(
        """
        INSERT INTO portfolio_ingestion.ingestion_jobs
            (user_id, pan_hash, source_type, method, checksum,
             pdf_gcs_key, pdf_status, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (pan_hash, checksum) DO NOTHING
        RETURNING id
        """,
        user_id, pan_hash, source_type, method, checksum,
        pdf_gcs_key, pdf_status, status,
    )
    if inserted is not None:
        return inserted["id"], True

    # The insert was a no-op — fetch the pre-existing row.
    existing_id: UUID = await conn.fetchval(
        """
        SELECT id FROM portfolio_ingestion.ingestion_jobs
         WHERE pan_hash = $1 AND checksum = $2
        """,
        pan_hash, checksum,
    )
    return existing_id, False


async def insert_pending_upload(
    conn: "asyncpg.Connection",
    *,
    user_id: UUID,
    pan_hash: str,
    source_type: str,
    pdf_gcs_key: str,
) -> UUID:
    """Create a job in ``pending_upload`` state for the signed-URL flow."""
    return await conn.fetchval(
        """
        INSERT INTO portfolio_ingestion.ingestion_jobs
            (user_id, pan_hash, source_type, method,
             checksum, pdf_gcs_key, pdf_status, status)
        VALUES ($1, $2, $3, 'upload', NULL, $4, 'pending', 'pending_upload')
        RETURNING id
        """,
        user_id, pan_hash, source_type, pdf_gcs_key,
    )


async def get(conn: "asyncpg.Connection", job_id: UUID) -> JobRow | None:
    row = await conn.fetchrow(
        "SELECT * FROM portfolio_ingestion.ingestion_jobs WHERE id = $1",
        job_id,
    )
    return _row_to_jobrow(row) if row else None


async def mark(
    conn: "asyncpg.Connection",
    job_id: UUID,
    *,
    status: str,
    failure_reason: str | None = None,
    raw_data_ref: str | None = None,
    pdf_status: str | None = None,
) -> None:
    """Transition a job to a new status. Sets completed_at for terminal states."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}")
    terminal = status in ("activated", "failed")
    await conn.execute(
        """
        UPDATE portfolio_ingestion.ingestion_jobs
           SET status         = $2,
               failure_reason = COALESCE($3, failure_reason),
               raw_data_ref   = COALESCE($4, raw_data_ref),
               pdf_status     = COALESCE($5, pdf_status),
               completed_at   = CASE WHEN $6 THEN now() ELSE completed_at END
         WHERE id = $1
        """,
        job_id, status, failure_reason, raw_data_ref, pdf_status, terminal,
    )
