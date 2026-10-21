"""nidp.macro_releases upsert: one row per indicator per release date."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

# A later run that cannot read a figure (NULL) never erases one stored earlier; a figure it does read replaces it.
UPSERT_SQL = """
INSERT INTO nidp.macro_releases
    (indicator_code, release_date, country, name, short_name, release_time, release_tz, time_is_typical, period,
     previous, estimate, actual, unit, impact, source, source_url, source_run_id, fetched_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, NOW())
ON CONFLICT (indicator_code, release_date) DO UPDATE SET
    country = EXCLUDED.country, name = EXCLUDED.name, short_name = EXCLUDED.short_name,
    release_time = EXCLUDED.release_time, release_tz = EXCLUDED.release_tz, time_is_typical = EXCLUDED.time_is_typical,
    period = COALESCE(EXCLUDED.period, nidp.macro_releases.period),
    previous = COALESCE(EXCLUDED.previous, nidp.macro_releases.previous),
    estimate = COALESCE(EXCLUDED.estimate, nidp.macro_releases.estimate),
    actual = COALESCE(EXCLUDED.actual, nidp.macro_releases.actual),
    unit = EXCLUDED.unit, impact = EXCLUDED.impact, source = EXCLUDED.source, source_url = EXCLUDED.source_url,
    source_run_id = EXCLUDED.source_run_id, fetched_at = NOW()
"""


def _args(r: dict, run_id: uuid.UUID) -> tuple:
    return (r["indicator_code"], r["release_date"], r["country"], r["name"], r["short_name"], r.get("release_time"),
            r.get("release_tz"), r.get("time_is_typical", True), r.get("period"), r.get("previous"), r.get("estimate"),
            r.get("actual"), r.get("unit"), r["impact"], r["source"], r.get("source_url"), run_id)


async def upsert_releases(rows: Sequence[dict], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(UPSERT_SQL, [_args(r, run_id) for r in rows])
    logger.info("macro_calendar upserted %d rows", len(rows))
    return len(rows)
