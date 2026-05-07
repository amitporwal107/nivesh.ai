"""nidp.sector_master writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_EQUITY_MASTER"


async def upsert_equity_master(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [(
        r["symbol"],
        r.get("company_name"),
        r.get("series"),
        r.get("isin"),
        to_date(r.get("listing_date")),
        r.get("face_value"),
        r.get("paid_up_value"),
        r.get("market_lot"),
        SOURCE_NAME,
        run_id,
    ) for r in rows]

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.sector_master
                    (symbol, company_name, series, isin,
                     listing_date, face_value, paid_up_value, market_lot,
                     source, source_run_id, ingested_at)
                VALUES ($1, $2, $3, $4,
                        $5::date, $6, $7, $8,
                        $9, $10, NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    company_name   = EXCLUDED.company_name,
                    series         = EXCLUDED.series,
                    isin           = EXCLUDED.isin,
                    listing_date   = EXCLUDED.listing_date,
                    face_value     = EXCLUDED.face_value,
                    paid_up_value  = EXCLUDED.paid_up_value,
                    market_lot     = EXCLUDED.market_lot,
                    source_run_id  = EXCLUDED.source_run_id,
                    ingested_at    = NOW()
                """,
                args,
            )
    logger.info("sector_master upserted %d rows", len(args))
    return len(args)


async def derive_sectors_from_index_membership(run_id: uuid.UUID) -> int:
    """Follow-up pass: backfill sector for symbols in known sectoral
    indices. Idempotent. Returns rows updated.

    Today's mapping is small (Bank Nifty + Nifty IT — the only
    sector indices currently ingested by index_constituents). Extend
    as more sector indices are added.
    """
    SECTOR_INDEX_MAP = {
        "Nifty Bank": "BANKING",
        "Nifty IT":   "IT",
    }
    pool = await get_pool()
    total = 0
    async with pool.acquire() as conn:
        for index_name, sector in SECTOR_INDEX_MAP.items():
            count = await conn.execute(
                """
                UPDATE nidp.sector_master sm
                   SET sector             = $2,
                       sector_source      = 'INDEX_MEMBERSHIP',
                       sector_resolved_at = NOW()
                  FROM (
                    SELECT DISTINCT symbol
                      FROM nidp.index_constituents
                     WHERE index_name = $1
                  ) ic
                 WHERE sm.symbol = ic.symbol
                   AND (sm.sector IS NULL OR sm.sector_source = 'INDEX_MEMBERSHIP')
                """,
                index_name, sector,
            )
            # asyncpg's execute returns "UPDATE N" — extract N
            try:
                total += int(count.split()[-1])
            except (ValueError, IndexError):
                pass
    logger.info("sector backfill from index membership: %d symbols updated", total)
    return total
