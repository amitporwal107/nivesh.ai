"""Guard for ingesters whose write target may not be writable here.

Some `nidp.*` relations are not local tables in every environment. On
staging, `nidp.index_eod` and `nidp.mf_nav_daily` are thin pass-through
VIEWS over FOREIGN TABLES that FDW into the production database — a
leftover of the abandoned FDW experiment. Reads work (21.7M NAV rows are
served through them), but an ingester's `INSERT ... ON CONFLICT` cannot:
a foreign table has no unique constraint for the conflict target, so
every run dies with

    InvalidColumnReferenceError: there is no unique or exclusion
    constraint matching the ON CONFLICT specification

`index_close` has failed this way 253 times and `amfi_nav` 85 — neither
has ever succeeded. That is a permanently red alarm carrying no
information, and it buries the feeds that are genuinely broken.

This helper lets an ingester notice the situation and report it
accurately (SKIPPED, with the reason) instead of failing identically
forever. It is deliberately *not* a fix for the drift itself: converting
those views into local tables would cut consumers off from the
production history they currently read, which is a decision for whoever
owns the staging/prod split. When that conversion happens, this guard
stops firing on its own and the ingesters resume writing.
"""
from __future__ import annotations

import logging
from typing import Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

_KIND_LABEL = {
    "r": "table", "p": "partitioned table", "v": "view",
    "m": "materialized view", "f": "foreign table",
}


async def upsert_target_problem(qualified_name: str) -> Optional[str]:
    """Return a human-readable reason `qualified_name` can't take an upsert.

    Returns None when the relation is a normal (or partitioned) table, so
    the caller should proceed. A missing relation is *not* reported here —
    that is a genuine error the caller should surface normally.
    """
    schema, _, name = qualified_name.partition(".")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.relkind
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = $1 AND c.relname = $2
            """,
            schema, name,
        )
    if row is None:
        return None                       # let the normal failure path speak
    # asyncpg maps postgres "char" to bytes, so relkind arrives as b'r'.
    # Normalising matters: an un-decoded value matches neither branch and
    # would flag a perfectly healthy table as unwritable.
    kind = row["relkind"]
    if isinstance(kind, (bytes, bytearray)):
        kind = kind.decode("ascii", "replace")
    if kind in ("r", "p"):
        return None

    detail = ""
    if kind == "v":
        async with pool.acquire() as conn:
            base = await conn.fetchval(
                """
                SELECT string_agg(DISTINCT bn.nspname || '.' || bc.relname ||
                                  ' (' || bc.relkind::text || ')', ', ')
                  FROM pg_depend d
                  JOIN pg_rewrite r  ON r.oid = d.objid
                  JOIN pg_class  v   ON v.oid = r.ev_class
                  JOIN pg_class  bc  ON bc.oid = d.refobjid
                  JOIN pg_namespace bn ON bn.oid = bc.relnamespace
                 WHERE v.relname = $1 AND bc.relname <> $1
                """,
                name,
            )
        if not base:
            # A pass-through view over a same-named relation in another
            # schema shows no rewrite dependency edge worth printing;
            # fall back to naming the view's own base relation.
            async with pool.acquire() as conn:
                base = await conn.fetchval(
                    """
                    SELECT string_agg(bn.nspname || '.' || bc.relname ||
                           ' (' || bc.relkind::text || ')', ', ')
                      FROM pg_class bc
                      JOIN pg_namespace bn ON bn.oid = bc.relnamespace
                     WHERE bc.relname = $1 AND bc.relkind = 'f'
                    """,
                    name,
                )
        if base:
            detail = f" over {base}"
    return (
        f"{qualified_name} is a {_KIND_LABEL.get(kind, kind)}{detail}, "
        f"not a writable table — an upsert cannot match a conflict target "
        f"here. Reads still work; this environment sources the data "
        f"elsewhere."
    )
