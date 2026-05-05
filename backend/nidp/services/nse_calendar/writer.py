"""nidp.nse_holidays writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_HOLIDAY_MASTER"


async def upsert_holidays(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (to_date(r["holiday_date"]), r["segment"], r.get("description"), SOURCE_NAME, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.nse_holidays
                    (holiday_date, segment, description, source, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, NOW())
                ON CONFLICT (holiday_date, segment, source) DO UPDATE SET
                    description   = EXCLUDED.description,
                    source_run_id = EXCLUDED.source_run_id,
                    ingested_at   = NOW()
                """,
                args,
            )
    logger.info("nse_holidays upserted %d rows", len(args))
    return len(args)
