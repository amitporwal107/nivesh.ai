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


_NAV_INSERT_SQL = """
INSERT INTO nidp.mf_nav_daily
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
INSERT INTO nidp.mf_scheme_master
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
    amc_id          = COALESCE(EXCLUDED.amc_id, nidp.mf_scheme_master.amc_id),
    amc_name_raw    = COALESCE(EXCLUDED.amc_name_raw, nidp.mf_scheme_master.amc_name_raw),
    isin_growth     = COALESCE(EXCLUDED.isin_growth, nidp.mf_scheme_master.isin_growth),
    isin_idcw       = COALESCE(EXCLUDED.isin_idcw, nidp.mf_scheme_master.isin_idcw),
    scheme_type     = COALESCE(EXCLUDED.scheme_type, nidp.mf_scheme_master.scheme_type),
    scheme_category = COALESCE(EXCLUDED.scheme_category, nidp.mf_scheme_master.scheme_category),
    updated_at      = NOW()
"""

# After NAV inserts, refresh latest_nav pointer on scheme_master in
# bulk. One UPDATE for the whole run — much faster than per-row.
_SCHEME_LATEST_NAV_SQL = """
UPDATE nidp.mf_scheme_master m
   SET latest_nav      = n.nav,
       latest_nav_date = n.nav_date,
       updated_at      = NOW()
  FROM (
    SELECT DISTINCT ON (scheme_code) scheme_code, nav, nav_date
      FROM nidp.mf_nav_daily
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
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if scheme_args:
                await conn.executemany(_SCHEME_INSERT_SQL, scheme_args)
            if nav_args:
                await conn.executemany(_NAV_INSERT_SQL, nav_args)
            await conn.execute(_SCHEME_LATEST_NAV_SQL, run_id)
    logger.info(
        "amfi_nav upserted nav=%d scheme_master=%d", len(nav_args), len(scheme_args),
    )
    return len(nav_args), len(scheme_args)
