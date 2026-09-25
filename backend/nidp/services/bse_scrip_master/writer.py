"""nidp.bse_scrip_master_daily writer (migration 153)."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "BSE_BHAVCOPY"


async def upsert_scrip_master(as_of: date, rows: list[dict[str, Any]],
                              run_id: uuid.UUID) -> int:
    """Write one trading day's scrip master.

    Idempotent on (as_of_date, scrip_code): a re-run of the same day overwrites
    that day only. It never touches another date, which is what keeps the table
    point-in-time — a scrip's group on a past day cannot be rewritten by a later
    run the way sector_master's destructive upsert rewrites everything.
    """
    if not rows:
        return 0
    args = [(
        as_of,
        r["scrip_code"],
        r.get("isin"),
        r.get("bse_ticker"),
        r.get("bse_group"),
        r.get("company_name"),
        SOURCE_NAME,
        run_id,
    ) for r in rows]

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.bse_scrip_master_daily
                    (as_of_date, scrip_code, isin, bse_ticker, bse_group,
                     company_name, source, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, NOW())
                ON CONFLICT (as_of_date, scrip_code) DO UPDATE SET
                    isin          = EXCLUDED.isin,
                    bse_ticker    = EXCLUDED.bse_ticker,
                    bse_group     = EXCLUDED.bse_group,
                    company_name  = EXCLUDED.company_name,
                    source_run_id = EXCLUDED.source_run_id,
                    ingested_at   = NOW()
                """,
                args,
            )
    return len(args)


async def dates_present(start: date, end: date) -> set[date]:
    """Trading days already written, so a backfill can resume without refetching."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT as_of_date FROM nidp.bse_scrip_master_daily "
            "WHERE as_of_date BETWEEN $1::date AND $2::date",
            start, end)
    return {r["as_of_date"] for r in rows}


async def sync_security_master_bse_code() -> dict:
    """Populate ref.security_master.bse_code from the scrip master.

    ref.security_master (migration 041) has carried a bse_code column since it
    was created and no code path has ever written it — 0 of 5,743 rows on
    nidp_staging 2026-09-25. daas_api/routers/documents.py works around that
    with a normalised-company-name join it labels a "DOCUMENTED STOPGAP", and
    migration 129 says the same.

    ref.security_master carries a UNIQUE partial index on bse_code
    (ux_security_master_bse), so the assignment must be strictly 1:1. Two things
    break that naively, both measured on nidp_staging 2026-09-25:

      * 288 scrips carry more than one ISIN over time. Scrip 890236 was
        IN90I0M01014 (Apr-May 2026) then IN90I0M01022 (Jul 2026). Matching on
        ISIN alone hands the same scrip to two securities.
      * 34 ISINs carry more than one scrip. BSE lists a one-day "#" settlement
        series alongside the real listing for some corporate actions:
        500325 RELIANCE (573 days) vs 100325 RELIANCE# (1 day); 532540 TCS vs
        132540 TCS#. Picking by scrip code alone silently prefers the wrong one.
      * 7 ISINs map to two sector_master symbols each (company renames), which
        can put two security_master rows behind one ISIN.

    So: newest ISIN per scrip, then the scrip that actually TRADED most days for
    that ISIN, then one security per ISIN. Only fills rows where bse_code IS NULL, so a hand-corrected value is
    never clobbered. Idempotent — re-run as the master backfills further.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            WITH latest_isin AS (          -- newest ISIN each scrip carried
                SELECT DISTINCT ON (scrip_code) scrip_code, isin
                FROM nidp.bse_scrip_master_daily
                WHERE isin IS NOT NULL
                ORDER BY scrip_code, as_of_date DESC
            ), scrip_days AS (             -- how long each scrip actually traded
                SELECT scrip_code, count(*) AS days
                FROM nidp.bse_scrip_master_daily
                GROUP BY scrip_code
            ), one_per_isin AS (           -- the real listing, not a "#" series
                SELECT DISTINCT ON (li.isin) li.isin, li.scrip_code
                FROM latest_isin li
                JOIN scrip_days d ON d.scrip_code = li.scrip_code
                ORDER BY li.isin, d.days DESC, li.scrip_code
            ), target AS (                 -- one security per ISIN (renames)
                SELECT DISTINCT ON (isin) security_id, isin
                FROM ref.security_master
                WHERE isin IS NOT NULL AND bse_code IS NULL
                ORDER BY isin, security_id
            ), upd AS (
                UPDATE ref.security_master sm
                   SET bse_code = o.scrip_code,
                       updated_at = NOW()
                  FROM target t
                  JOIN one_per_isin o ON o.isin = t.isin
                 WHERE sm.security_id = t.security_id
                RETURNING 1
            )
            SELECT (SELECT count(*) FROM upd)                        AS filled,
                   (SELECT count(*) FROM ref.security_master)        AS total,
                   (SELECT count(bse_code) FROM ref.security_master) AS with_code
            """)
    out = dict(row)
    logger.info("security_master bse_code: filled %s, now %s/%s populated",
                out["filled"], out["with_code"], out["total"])
    return out
