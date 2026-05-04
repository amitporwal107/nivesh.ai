"""nidp.block_deals append-only writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "NSE_BLOCK"


async def upsert_block_deals(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    pool = await get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for r in rows:
                await conn.execute(
                    """
                    INSERT INTO nidp.block_deals
                        (as_of_date, symbol, client_name, deal_type,
                         quantity, avg_price, deal_seq, remarks,
                         source, source_run_id, ingested_at)
                    VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                    ON CONFLICT (as_of_date, symbol, client_name, deal_type, deal_seq, source)
                    DO UPDATE SET
                        quantity = EXCLUDED.quantity,
                        avg_price = EXCLUDED.avg_price,
                        remarks = EXCLUDED.remarks,
                        source_run_id = EXCLUDED.source_run_id,
                        ingested_at = NOW()
                    """,
                    r["as_of_date"], r["symbol"], r["client_name"], r["deal_type"],
                    r["quantity"], r["avg_price"], r["deal_seq"], r.get("remarks"),
                    SOURCE_NAME, run_id,
                )
                inserted += 1
    logger.info("block_deals upserted %d rows", inserted)
    return inserted
