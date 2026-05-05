"""nidp.rbi_yields writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "RBI_REF_RATE"


async def upsert_rbi_yields(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (to_date(r["as_of_date"]), r["tenor"], r["yield_pct"], r.get("instrument"),
         SOURCE_NAME, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.rbi_yields
                    (as_of_date, tenor, yield_pct, instrument,
                     source, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, $6, NOW())
                ON CONFLICT (as_of_date, tenor, source) DO UPDATE SET
                    yield_pct     = EXCLUDED.yield_pct,
                    instrument    = EXCLUDED.instrument,
                    source_run_id = EXCLUDED.source_run_id,
                    ingested_at   = NOW()
                """,
                args,
            )
    logger.info("rbi_yields upserted %d rows", len(args))
    return len(args)
