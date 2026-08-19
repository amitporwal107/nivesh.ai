"""nidp.fpi_sector_auc writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSDL_FPI_FORTNIGHTLY"


async def upsert_fpi_sector_auc(rows: list[dict[str, Any]],
                                run_id: uuid.UUID) -> int:
    """Upsert fortnightly sector rows.

    Adjacent monthly reports overlap by one fortnight, and NSDL revises the older
    half when it publishes the newer file — so a later run must win. DO UPDATE
    (not DO NOTHING) is what makes the overlap self-correcting.
    """
    if not rows:
        return 0
    args = [
        (to_date(r["report_date"]), r["sector"], r["asset_class"],
         r.get("auc_inr_cr"), r.get("auc_usd_mn"),
         r.get("net_inv_inr_cr"), r.get("net_inv_usd_mn"),
         r.get("usd_inr_rate"), r.get("sector_norm"),
         SOURCE_NAME, r.get("source_url"), run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.fpi_sector_auc
                    (report_date, sector, asset_class,
                     auc_inr_cr, auc_usd_mn, net_inv_inr_cr, net_inv_usd_mn,
                     usd_inr_rate, sector_norm,
                     source, source_url, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                        NOW())
                ON CONFLICT (report_date, sector, asset_class, source)
                DO UPDATE SET
                    auc_inr_cr     = EXCLUDED.auc_inr_cr,
                    auc_usd_mn     = EXCLUDED.auc_usd_mn,
                    net_inv_inr_cr = EXCLUDED.net_inv_inr_cr,
                    net_inv_usd_mn = EXCLUDED.net_inv_usd_mn,
                    usd_inr_rate   = EXCLUDED.usd_inr_rate,
                    sector_norm    = EXCLUDED.sector_norm,
                    source_url     = EXCLUDED.source_url,
                    source_run_id  = EXCLUDED.source_run_id,
                    ingested_at    = NOW()
                """,
                args,
            )
    logger.info("fpi_sector_auc upserted %d rows", len(args))
    return len(args)
