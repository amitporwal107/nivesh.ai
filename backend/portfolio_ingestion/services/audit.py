"""Append-only audit log writes (PRD §11.2).

Every state transition that touches PAN-linked data must call one of these
helpers inside the same database transaction as the write it records.

The audit_log table has an immutability trigger — no row can ever be
UPDATE-d or DELETE-d after it is written.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg

_INSERT = """
INSERT INTO portfolio_ingestion.audit_log
    (event_type, entity_type, entity_id, pan_hash, actor, payload)
VALUES ($1, $2, $3, $4, $5, $6::jsonb)
"""


def _j(data: dict[str, Any]) -> str:
    return json.dumps(data, default=str)


async def user_created(
    conn: "asyncpg.Connection",
    *,
    user_id: UUID,
    pan_hash: str,
    external_id: str,
    has_enc: bool,
) -> None:
    await conn.execute(
        _INSERT,
        "USER_CREATED", "user", user_id, pan_hash, "system",
        _j({"external_id": external_id, "has_pan_enc": has_enc}),
    )


async def job_status(
    conn: "asyncpg.Connection",
    *,
    job_id: UUID,
    pan_hash: str,
    old_status: str | None,
    new_status: str,
    source_type: str,
    method: str,
    failure_reason: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "from": old_status,
        "to": new_status,
        "source_type": source_type,
        "method": method,
    }
    if failure_reason:
        payload["failure_reason"] = failure_reason
    await conn.execute(
        _INSERT,
        "JOB_STATUS", "job", job_id, pan_hash, "system", _j(payload),
    )


async def snapshot_activated(
    conn: "asyncpg.Connection",
    *,
    snapshot_id: UUID,
    pan_hash: str,
    source_type: str,
    method: str,
    reason: str,
    holdings_written: int,
    statement_to: str,
) -> None:
    await conn.execute(
        _INSERT,
        "SNAPSHOT_ACTIVATED", "snapshot", snapshot_id, pan_hash, "system",
        _j({
            "source_type": source_type,
            "method": method,
            "reason": reason,
            "holdings_written": holdings_written,
            "statement_to": statement_to,
        }),
    )


async def snapshot_deactivated(
    conn: "asyncpg.Connection",
    *,
    snapshot_id: UUID,
    pan_hash: str,
    superseded_by: UUID,
    reason: str,
) -> None:
    await conn.execute(
        _INSERT,
        "SNAPSHOT_DEACTIVATED", "snapshot", snapshot_id, pan_hash, "system",
        _j({"superseded_by": str(superseded_by), "reason": reason}),
    )
