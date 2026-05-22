"""Resolve / create the ``users`` row for an incoming SDK callback.

Multi-PAN per user is out of scope for V1 (PRD §12). If we already have a
user with the supplied external_id but a different pan_hash, we refuse the
request — this catches PAN-swap attacks and prevents silently aliasing two
people's portfolios under one account.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg


class PanMismatchError(Exception):
    """external_id maps to a different pan_hash than the one in the payload."""


async def resolve(
    conn: "asyncpg.Connection",
    *,
    external_id: str,
    pan_hash: str,
) -> UUID:
    """Return the users.id for ``(external_id, pan_hash)``; create if missing."""
    row = await conn.fetchrow(
        "SELECT id, pan_hash FROM portfolio_ingestion.users WHERE external_id = $1",
        external_id,
    )
    if row is not None:
        if row["pan_hash"] != pan_hash:
            raise PanMismatchError(
                f"external_id {external_id!r} already mapped to a different PAN"
            )
        return row["id"]

    return await conn.fetchval(
        """
        INSERT INTO portfolio_ingestion.users (external_id, pan_hash)
        VALUES ($1, $2)
        ON CONFLICT (external_id) DO UPDATE
          SET external_id = EXCLUDED.external_id   -- no-op to allow RETURNING
        RETURNING id
        """,
        external_id, pan_hash,
    )
