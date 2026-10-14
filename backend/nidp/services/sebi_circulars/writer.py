"""nidp.sebi_circulars upsert writer (keyed by url)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "SEBI_CIRCULARS"

# first_seen_at and source keep the first sighting; a later run refreshes the title and
# last_seen_at, and fills issued_on / department only where they were empty.
_UPSERT_SQL = """
INSERT INTO nidp.sebi_circulars
    (url, title, kind, issued_on, department, source, source_run_id, first_seen_at, last_seen_at)
VALUES ($1, $2, $3, $4::date, $5, $6, $7, NOW(), NOW())
ON CONFLICT (url) DO UPDATE SET
    title         = EXCLUDED.title,
    kind          = EXCLUDED.kind,
    issued_on     = COALESCE(nidp.sebi_circulars.issued_on, EXCLUDED.issued_on),
    department    = COALESCE(nidp.sebi_circulars.department, EXCLUDED.department),
    source_run_id = EXCLUDED.source_run_id,
    last_seen_at  = NOW()
"""


async def upsert_circulars(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (r["url"], r["title"], r["kind"], r.get("issued_on"), r.get("department"),
         r["source"], run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_UPSERT_SQL, args)
    logger.info("sebi_circulars upserted %d rows", len(args))
    return len(args)
