"""nidp.delivery_data writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_SEC_BHAVDATA"


async def upsert_delivery(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (r["as_of_date"], r["symbol"], r["series"],
         r.get("traded_qty"), r.get("deliverable_qty"), r.get("deliverable_pct"),
         SOURCE_NAME, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.delivery_data
                    (as_of_date, symbol, series, traded_qty, deliverable_qty,
                     deliverable_pct, source, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, NOW())
                ON CONFLICT (as_of_date, symbol, series, source) DO UPDATE SET
                    traded_qty       = EXCLUDED.traded_qty,
                    deliverable_qty  = EXCLUDED.deliverable_qty,
                    deliverable_pct  = EXCLUDED.deliverable_pct,
                    source_run_id    = EXCLUDED.source_run_id,
                    ingested_at      = NOW()
                """,
                args,
            )
    logger.info("delivery_data upserted %d rows", len(args))
    return len(args)
