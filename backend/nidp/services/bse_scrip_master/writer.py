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
