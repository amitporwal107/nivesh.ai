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
import re
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


# ── AMC auto-registration ────────────────────────────────────────────────
# amc_id is resolved by prefix-matching amc_name_raw against
# nidp.mf_amc_master. That master listed only 10 AMCs while the AMFI feed
# carries 51, so 5,154 of 14,454 scheme rows carried a NULL amc_id even though
# 5,149 of them knew their AMC by name. The damage was silent and downstream:
# the mf_holdings quant adapter looks schemes up with `WHERE amc_id = 'quant'`,
# matched nothing, and discarded 29 funds it had already downloaded.
#
# Backfilling once does not hold — AlphaGrep Mutual Fund appeared in the feed
# within a day of the backfill and immediately had 12 unmapped schemes. So the
# master is topped up from the feed on every run instead: any amc_name_raw with
# no matching row gets registered under a derived id.
_AMC_ID_OVERRIDES = {
    # ids already used by nidp.mf_amc_source_registry — keep them identical
    "quant mutual fund": "quant",
    "jm financial mutual fund": "jm_financial",
}


def _amc_slug(amc_name_raw: str) -> str:
    """Derive a stable amc_id from an AMFI AMC name.

    "Baroda BNP Paribas Mutual Fund" -> "baroda_bnp_paribas"
    "IL&FS Mutual Fund (IDF)"        -> "il_and_fs"
    """
    key = amc_name_raw.strip().lower()
    if key in _AMC_ID_OVERRIDES:
        return _AMC_ID_OVERRIDES[key]
    t = re.sub(r"\s*\(.*?\)\s*", " ", amc_name_raw)
    t = re.sub(r"\bmutual\s+fund\b", "", t, flags=re.I).strip()
    t = t.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


_AMC_REGISTER_SQL = """
INSERT INTO nidp.mf_amc_master (amc_id, amc_name)
SELECT $1, $2
 WHERE NOT EXISTS (
       SELECT 1 FROM nidp.mf_amc_master m
        WHERE lower($2) LIKE lower(m.amc_name) || '%'
   )
ON CONFLICT (amc_id) DO NOTHING
"""


async def register_unknown_amcs(conn, scheme_rows: list[dict[str, Any]]) -> int:
    """Add any AMC the feed knows about but the master does not.

    The NOT EXISTS mirrors the resolver's own prefix rule, so an AMC that
    already resolves is never re-added under a second id. The FULL name is
    stored (not a bare stem) because the resolver disambiguates by
    `ORDER BY length(amc_name) DESC` — that is what keeps "quant Mutual Fund"
    from swallowing "Quantum Mutual Fund".
    """
    names = sorted({(r.get("amc_name_raw") or "").strip()
                    for r in scheme_rows if (r.get("amc_name_raw") or "").strip()})
    added = 0
    for name in names:
        slug = _amc_slug(name)
        if not slug:
            continue
        status = await conn.execute(_AMC_REGISTER_SQL, slug, name)
        if status and status.rsplit(" ", 1)[-1] != "0":
            added += 1
            logger.info("amfi_nav: registered new AMC %r as amc_id=%r", name, slug)
    if added:
        logger.warning("amfi_nav: added %d AMC(s) to nidp.mf_amc_master", added)
    return added


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
            # Top the master up first: the scheme insert resolves amc_id
            # against it in the same statement, so an AMC registered here is
            # picked up on this run rather than the next one.
            await register_unknown_amcs(conn, scheme_rows)
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
