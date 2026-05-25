"""analytics_refresh — call analytics.refresh_all() for the given date.

Idempotent: the underlying SQL function DELETEs existing rows for the date
before re-inserting, so reruns are safe.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


async def run(target_date: Optional[date] = None) -> dict:
    if target_date is None:
        target_date = date.today()

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT analytics.refresh_all($1::date) AS summary",
            target_date,
        )

    summary = dict(result["summary"]) if result and result["summary"] else {}
    stock_rows   = int(summary.get("stock_card_rows", 0))
    sector_rows  = int(summary.get("sector_snapshot_rows", 0))
    elapsed_ms   = summary.get("elapsed_ms")

    logger.info(
        "analytics_refresh as_of=%s stock_card=%d sector_snapshot=%d elapsed_ms=%s",
        target_date, stock_rows, sector_rows, elapsed_ms,
    )
    return {
        "as_of_date":          target_date.isoformat(),
        "stock_card_rows":     stock_rows,
        "sector_snapshot_rows": sector_rows,
        "elapsed_ms":          elapsed_ms,
        "rows_inserted":       stock_rows + sector_rows,
    }
