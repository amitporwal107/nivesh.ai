"""nidp.mf_nav_daily + mf_scheme_master upsert writer.

NAVAll lands ~10k scheme rows daily. Both writes happen in one
transaction: a torn write would leave scheme_master ahead of NAV or
vice versa, which downstream queries don't tolerate.

amc_id resolution is best-effort: we map amc_name_raw → amc_id via
mf_amc_master.amc_name (case-insensitive substring match) inside the
upsert SQL itself, so the resolution stays consistent across runs and
new AMCs in mf_amc_master pick up retroactively without re-running
the ingester.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "AMFI_NAVALL"

# Where the NAV rows actually go.
#
# nidp.mf_nav_daily is a pass-through VIEW over an FDW foreign table into prod in
# some environments. A foreign table has no unique constraint, so the upsert below
# cannot match its conflict target and every run dies with
# "there is no unique or exclusion constraint matching the ON CONFLICT
# specification" — 85 consecutive failures on staging, never once green, while
# AMFI itself was serving fine the whole time.
#
# nidp.mf_nav_daily_local is the real table behind that name (staging's own
# pre-FDW ingestion), with the same columns and the same
# (scheme_code, nav_date, source) primary key. Resolving the target at runtime
# means this writes to the canonical table wherever that is a table, and falls
# back to the local one where it is not — and it self-heals with no code change
# the moment the view is swapped for a table.
# Both of amfi_nav's write targets have the same defect, so both are resolved.
_NAV_TABLE_PREFERRED = "nidp.mf_nav_daily"
_NAV_TABLE_FALLBACK = "nidp.mf_nav_daily_local"
_SCHEME_TABLE_PREFERRED = "nidp.mf_scheme_master"
_SCHEME_TABLE_FALLBACK = "nidp.mf_scheme_master_local"


async def _resolve_table(preferred: str, fallback: str) -> str:
    """Return the first of the two relations that can take an upsert."""
    from nidp.shared.write_target import upsert_target_problem

    problem = await upsert_target_problem(preferred)
    if problem is None:
        return preferred
    logger.warning("amfi_nav: %s — writing to %s instead", problem, fallback)
    return fallback


async def resolve_nav_table() -> str:
    return await _resolve_table(_NAV_TABLE_PREFERRED, _NAV_TABLE_FALLBACK)


async def resolve_scheme_table() -> str:
    return await _resolve_table(_SCHEME_TABLE_PREFERRED, _SCHEME_TABLE_FALLBACK)


_NAV_INSERT_SQL = """
INSERT INTO {nav_table}
    (scheme_code, nav_date, nav, repurchase_nav, sale_nav,
     source, source_run_id, ingested_at)
VALUES ($1, $2::date, $3, $4, $5, $6, $7, NOW())
ON CONFLICT (scheme_code, nav_date, source) DO UPDATE SET
    nav            = EXCLUDED.nav,
    repurchase_nav = EXCLUDED.repurchase_nav,
    sale_nav       = EXCLUDED.sale_nav,
    source_run_id  = EXCLUDED.source_run_id,
    ingested_at    = NOW()
"""

# AMC resolution: pick the first mf_amc_master row whose lowered
# amc_name is a prefix of (or equal to) the lowered amc_name_raw.
# Using LATERAL keeps the subquery scoped per-row.
_SCHEME_INSERT_SQL = """
WITH input AS (
  SELECT $1::text AS scheme_code,
         $2::text AS scheme_name,
         $3::text AS amc_name_raw,
         $4::text AS isin_growth,
         $5::text AS isin_idcw,
         $6::text AS scheme_type,
         $7::text AS scheme_category
)
INSERT INTO {scheme_table}
    (scheme_code, scheme_name, amc_id, amc_name_raw,
     isin_growth, isin_idcw, scheme_type, scheme_category,
     status, first_seen_at, updated_at)
SELECT i.scheme_code,
       i.scheme_name,
       (SELECT a.amc_id
          FROM nidp.mf_amc_master a
         WHERE i.amc_name_raw IS NOT NULL
           AND lower(i.amc_name_raw) LIKE lower(a.amc_name) || '%'
         ORDER BY length(a.amc_name) DESC
         LIMIT 1),
       i.amc_name_raw,
       i.isin_growth,
       i.isin_idcw,
       i.scheme_type,
       i.scheme_category,
       'active', NOW(), NOW()
  FROM input i
ON CONFLICT (scheme_code) DO UPDATE SET
    scheme_name     = EXCLUDED.scheme_name,
    amc_id = COALESCE(EXCLUDED.amc_id, {scheme_table}.amc_id),
    amc_name_raw = COALESCE(EXCLUDED.amc_name_raw, {scheme_table}.amc_name_raw),
    isin_growth = COALESCE(EXCLUDED.isin_growth, {scheme_table}.isin_growth),
    isin_idcw = COALESCE(EXCLUDED.isin_idcw, {scheme_table}.isin_idcw),
    scheme_type = COALESCE(EXCLUDED.scheme_type, {scheme_table}.scheme_type),
    scheme_category = COALESCE(EXCLUDED.scheme_category, {scheme_table}.scheme_category),
    updated_at      = NOW()
"""

# After NAV inserts, refresh latest_nav pointer on scheme_master in
# bulk. One UPDATE for the whole run — much faster than per-row.
_SCHEME_LATEST_NAV_SQL = """
UPDATE {scheme_table} m
   SET latest_nav      = n.nav,
       latest_nav_date = n.nav_date,
       updated_at      = NOW()
  FROM (
    SELECT DISTINCT ON (scheme_code) scheme_code, nav, nav_date
      FROM {nav_table}
     WHERE source_run_id = $1
     ORDER BY scheme_code, nav_date DESC
  ) n
 WHERE m.scheme_code = n.scheme_code
"""


async def upsert_nav_and_master(
    nav_rows: list[dict[str, Any]],
    scheme_rows: list[dict[str, Any]],
    run_id: uuid.UUID,
) -> tuple[int, int]:
    if not nav_rows and not scheme_rows:
        return 0, 0
    nav_args = [
        (r["scheme_code"], r["nav_date"], r["nav"],
         r.get("repurchase_nav"), r.get("sale_nav"),
         SOURCE_NAME, run_id)
        for r in nav_rows
    ]
    scheme_args = [
        (r["scheme_code"], r["scheme_name"], r.get("amc_name_raw"),
         r.get("isin_growth"), r.get("isin_idcw"),
         r.get("scheme_type"), r.get("scheme_category"))
        for r in scheme_rows
    ]
    nav_table = await resolve_nav_table()
    scheme_table = await resolve_scheme_table()
    nav_sql = _NAV_INSERT_SQL.format(nav_table=nav_table)
    scheme_sql = _SCHEME_INSERT_SQL.format(scheme_table=scheme_table)
    latest_sql = _SCHEME_LATEST_NAV_SQL.format(
        scheme_table=scheme_table, nav_table=nav_table)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if scheme_args:
                await conn.executemany(scheme_sql, scheme_args)
            if nav_args:
                await conn.executemany(nav_sql, nav_args)
            await conn.execute(latest_sql, run_id)
    logger.info(
        "amfi_nav upserted nav=%d into %s, scheme_master=%d into %s",
        len(nav_args), nav_table, len(scheme_args), scheme_table,
    )
    return len(nav_args), len(scheme_args)
