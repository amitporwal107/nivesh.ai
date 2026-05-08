"""nidp.mf_scheme_disclosure_snapshot upsert writer."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "MF_DISCLOSURE_SNAPSHOT"

_INSERT_SQL = """
INSERT INTO nidp.mf_scheme_disclosure_snapshot
    (scheme_code, snapshot_date, ter_pct, ter_pct_direct, risk_o_meter,
     primary_manager, secondary_manager, aum_inr_crore,
     source_url, source_run_id, ingested_at)
VALUES ($1, $2::date, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
ON CONFLICT (scheme_code, snapshot_date) DO UPDATE SET
    ter_pct           = EXCLUDED.ter_pct,
    ter_pct_direct    = EXCLUDED.ter_pct_direct,
    risk_o_meter      = EXCLUDED.risk_o_meter,
    primary_manager   = EXCLUDED.primary_manager,
    secondary_manager = EXCLUDED.secondary_manager,
    aum_inr_crore     = EXCLUDED.aum_inr_crore,
    source_url        = EXCLUDED.source_url,
    source_run_id     = EXCLUDED.source_run_id,
    ingested_at       = NOW()
"""


async def upsert_snapshot(
    rows: list[dict[str, Any]], snapshot_date: date, run_id: uuid.UUID,
) -> int:
    if not rows:
        return 0
    args = [
        (r["scheme_code"], snapshot_date,
         r.get("ter_pct"), r.get("ter_pct_direct"), r.get("risk_o_meter"),
         r.get("primary_manager"), r.get("secondary_manager"),
         r.get("aum_inr_crore"), r.get("source_url"), run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_SQL, args)
    return len(args)
