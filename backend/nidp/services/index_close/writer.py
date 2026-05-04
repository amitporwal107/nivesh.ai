"""nidp.index_eod writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_IND_CLOSE"


async def upsert_index_close(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (r["as_of_date"], r["index_name"],
         r.get("open_price"), r.get("high_price"), r.get("low_price"),
         r.get("close_price"),
         r.get("pe_ratio"), r.get("pb_ratio"), r.get("div_yield"),
         r.get("pts_change"), r.get("pct_change"),
         r.get("volume"), r.get("turnover"),
         SOURCE_NAME, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.index_eod
                    (as_of_date, index_name, open_price, high_price, low_price,
                     close_price, pe_ratio, pb_ratio, div_yield,
                     pts_change, pct_change, volume, turnover,
                     source, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, NOW())
                ON CONFLICT (as_of_date, index_name, source) DO UPDATE SET
                    open_price    = EXCLUDED.open_price,
                    high_price    = EXCLUDED.high_price,
                    low_price     = EXCLUDED.low_price,
                    close_price   = EXCLUDED.close_price,
                    pe_ratio      = EXCLUDED.pe_ratio,
                    pb_ratio      = EXCLUDED.pb_ratio,
                    div_yield     = EXCLUDED.div_yield,
                    pts_change    = EXCLUDED.pts_change,
                    pct_change    = EXCLUDED.pct_change,
                    volume        = EXCLUDED.volume,
                    turnover      = EXCLUDED.turnover,
                    source_run_id = EXCLUDED.source_run_id,
                    ingested_at   = NOW()
                """,
                args,
            )
    logger.info("index_eod upserted %d rows", len(args))
    return len(args)
