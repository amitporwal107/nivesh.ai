"""nidp.mf_nav_daily writer for the MFAPI backfill source.

Source-tagged 'MFAPI' so it never overwrites authoritative AMFI_NAVALL
rows on the same (scheme_code, nav_date). Both rows can coexist; the
PK is (scheme_code, nav_date, source). Reader queries pick AMFI_NAVALL
when both exist — see views in 005_nidp_views.sql.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "MFAPI"

_INSERT_SQL = """
INSERT INTO nidp.mf_nav_daily
    (scheme_code, nav_date, nav, source, source_run_id, ingested_at)
VALUES ($1, $2::date, $3, $4, $5, NOW())
ON CONFLICT (scheme_code, nav_date, source) DO UPDATE SET
    nav           = EXCLUDED.nav,
    source_run_id = EXCLUDED.source_run_id,
    ingested_at   = NOW()
"""


async def upsert_history(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (r["scheme_code"], r["nav_date"], r["nav"], SOURCE_NAME, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_SQL, args)
    return len(args)
