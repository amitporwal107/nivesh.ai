"""Resolve / create the ``users`` row for an incoming SDK callback.

Multi-PAN per user is out of scope for V1 (PRD §12). If we already have a
user with the supplied external_id but a different pan_hash, we refuse the
request — this catches PAN-swap attacks and prevents silently aliasing two
people's portfolios under one account.

PAN encryption (T2.3): when a real (un-hashed) PAN is supplied, we also
write the ciphertext to ``users.pan_enc`` via the SQL helper
``portfolio_ingestion.pi_encrypt_pan``. The encryption key is set
session-scoped via SET LOCAL right before the call so it never enters the
WAL log in plaintext.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg

from ..config import get_settings


class PanMismatchError(Exception):
    """external_id maps to a different pan_hash than the one in the payload."""


async def _set_pan_key(conn: "asyncpg.Connection") -> None:
    key = get_settings().pan_encryption_key
    if not key:
        return  # function will fall back to its placeholder; staging-only.
    # SET LOCAL scopes the key to the current transaction. set_config()'s
    # third arg ``true`` does the same; either form is fine.
    await conn.execute(
        "SELECT set_config('portfolio_ingestion.pan_encryption_key', $1, true)",
        key,
    )


async def resolve(
    conn: "asyncpg.Connection",
    *,
    external_id: str,
    pan_hash: str,
    pan: str | None = None,
) -> UUID:
    """Return the users.id for ``(external_id, pan_hash)``; create if missing.

    If ``pan`` (plaintext) is supplied, also writes ``pan_enc`` via pgcrypto.
    """
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

    if pan is None:
        # No plaintext — insert without encrypted PAN. Backfilled on next
        # callback that supplies it.
        return await conn.fetchval(
            """
            INSERT INTO portfolio_ingestion.users (external_id, pan_hash)
            VALUES ($1, $2)
            ON CONFLICT (external_id) DO UPDATE
              SET external_id = EXCLUDED.external_id
            RETURNING id
            """,
            external_id, pan_hash,
        )

    # With plaintext — encrypt server-side via SQL helper.
    async with conn.transaction():
        await _set_pan_key(conn)
        return await conn.fetchval(
            """
            INSERT INTO portfolio_ingestion.users (external_id, pan_hash, pan_enc)
            VALUES ($1, $2, portfolio_ingestion.pi_encrypt_pan($3))
            ON CONFLICT (external_id) DO UPDATE
              SET pan_enc = COALESCE(users.pan_enc, EXCLUDED.pan_enc)
            RETURNING id
            """,
            external_id, pan_hash, pan,
        )
