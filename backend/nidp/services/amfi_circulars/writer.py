"""nidp.mf_amfi_circulars upsert writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "AMFI_CIRCULARS"

_INSERT_SQL = """
INSERT INTO nidp.mf_amfi_circulars
    (circular_id, published_at, title, url, kind, body_text,
     raw_artifact_path, source_run_id, ingested_at)
VALUES ($1, $2::date, $3, $4, $5, $6, $7, $8, NOW())
ON CONFLICT (circular_id) DO UPDATE SET
    published_at      = COALESCE(EXCLUDED.published_at, nidp.mf_amfi_circulars.published_at),
    title             = EXCLUDED.title,
    kind              = COALESCE(EXCLUDED.kind, nidp.mf_amfi_circulars.kind),
    body_text         = COALESCE(EXCLUDED.body_text, nidp.mf_amfi_circulars.body_text),
    raw_artifact_path = COALESCE(EXCLUDED.raw_artifact_path, nidp.mf_amfi_circulars.raw_artifact_path),
    source_run_id     = EXCLUDED.source_run_id,
    ingested_at       = NOW()
"""


async def upsert_circulars(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (r["circular_id"], r.get("published_at"), r["title"], r["url"],
         r.get("kind"), r.get("body_text"), r.get("raw_artifact_path"), run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_SQL, args)
    logger.info("amfi_circulars upserted %d rows", len(args))
    return len(args)
