"""nidp.fred_macro append-only writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "FRED"


async def upsert_fred(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (to_date(r["as_of_date"]), r["series_id"], r.get("series_name"),
         r.get("value"), r.get("units"), r.get("frequency"),
         SOURCE_NAME, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.fred_macro
                    (as_of_date, series_id, series_name, value, units, frequency,
                     source, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, NOW())
                ON CONFLICT (as_of_date, series_id, source) DO UPDATE SET
                    series_name   = EXCLUDED.series_name,
                    value         = EXCLUDED.value,
                    units         = EXCLUDED.units,
                    frequency     = EXCLUDED.frequency,
                    source_run_id = EXCLUDED.source_run_id,
                    ingested_at   = NOW()
                """,
                args,
            )
    logger.info("fred_macro upserted %d rows", len(args))
    return len(args)
