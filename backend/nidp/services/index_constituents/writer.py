"""nidp.index_constituents writer."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_INDEX_LIST"


async def upsert_constituents(
    rows: list[dict[str, Any]],
    *,
    index_name: str,
    as_of: date,
    run_id: uuid.UUID,
) -> int:
    if not rows:
        return 0
    args = [
        (as_of, index_name, r["symbol"], r.get("isin"),
         r.get("company_name"), r.get("industry"), r.get("weight_pct"),
         SOURCE_NAME, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.index_constituents
                    (as_of_date, index_name, symbol, isin, company_name,
                     industry, weight_pct, source, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                ON CONFLICT (as_of_date, index_name, symbol, source) DO UPDATE SET
                    isin          = EXCLUDED.isin,
                    company_name  = EXCLUDED.company_name,
                    industry      = EXCLUDED.industry,
                    weight_pct    = EXCLUDED.weight_pct,
                    source_run_id = EXCLUDED.source_run_id,
                    ingested_at   = NOW()
                """,
                args,
            )
    logger.info("index_constituents %s upserted %d rows", index_name, len(args))
    return len(args)
