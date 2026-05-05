"""nidp.corporate_actions writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_CA"


async def upsert_corporate_actions(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (r["symbol"], r.get("series"), r["action_type"], r.get("action_subtype"),
         r.get("purpose"), r.get("ratio"),
         r.get("face_value_pre"), r.get("face_value_post"), r.get("dividend_amount"),
         to_date(r.get("record_date")), to_date(r["ex_date"]),
         to_date(r.get("bc_start_date")), to_date(r.get("bc_end_date")),
         to_date(r.get("announcement_date")),
         SOURCE_NAME, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.corporate_actions
                    (symbol, series, action_type, action_subtype, purpose, ratio,
                     face_value_pre, face_value_post, dividend_amount,
                     record_date, ex_date, bc_start_date, bc_end_date,
                     announcement_date, source, source_run_id, ingested_at)
                VALUES ($1, $2, $3, $4, $5, $6,
                        $7, $8, $9,
                        $10::date, $11::date, $12::date, $13::date,
                        $14::date, $15, $16, NOW())
                ON CONFLICT (symbol, action_type, ex_date, source) DO UPDATE SET
                    series           = EXCLUDED.series,
                    action_subtype   = EXCLUDED.action_subtype,
                    purpose          = EXCLUDED.purpose,
                    ratio            = EXCLUDED.ratio,
                    face_value_pre   = EXCLUDED.face_value_pre,
                    face_value_post  = EXCLUDED.face_value_post,
                    dividend_amount  = EXCLUDED.dividend_amount,
                    record_date      = EXCLUDED.record_date,
                    bc_start_date    = EXCLUDED.bc_start_date,
                    bc_end_date      = EXCLUDED.bc_end_date,
                    announcement_date = EXCLUDED.announcement_date,
                    source_run_id    = EXCLUDED.source_run_id,
                    ingested_at      = NOW()
                """,
                args,
            )
    logger.info("corporate_actions upserted %d rows", len(args))
    return len(args)
