"""analytics_refresh — call analytics.refresh_all() for the given date.

Idempotent: the underlying SQL function DELETEs existing rows for the date
before re-inserting, so reruns are safe.

The default date is the latest session that has a stock snapshot
(nidp.stock_daily_snapshot, what analytics.refresh_stock_card reads), not the
calendar day. The cron runs at 00:10 IST, when date.today() is already the next
day with no prices: every run from 13 Oct 2026 wrote 0 rows and still reported
OK, so the top movers, the sector heatmap and the delivery surge stayed on
12 Oct. A run that writes no stock card now fails, so the feed status shows it.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


LATEST_SESSION_SQL = (
    "SELECT max(as_of_date) FROM nidp.stock_daily_snapshot WHERE as_of_date <= CURRENT_DATE"
)


async def run(target_date: Optional[date] = None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if target_date is None:
            target_date = await conn.fetchval(LATEST_SESSION_SQL)
            if target_date is None:
                raise RuntimeError("analytics_refresh: nidp.stock_daily_snapshot has no session to refresh")
        result = await conn.fetchrow(
            "SELECT analytics.refresh_all($1::date) AS summary",
            target_date,
        )

    raw = result["summary"] if result else None
    if raw is None:
        summary = {}
    elif isinstance(raw, dict):
        summary = raw
    else:
        summary = json.loads(raw)
    stock_rows   = int(summary.get("stock_cards", summary.get("stock_card_rows", 0)))
    sector_rows  = int(summary.get("sectors", summary.get("sector_snapshot_rows", 0)))
    elapsed_ms   = summary.get("duration_ms", summary.get("elapsed_ms"))

    logger.info(
        "analytics_refresh as_of=%s stock_card=%d sector_snapshot=%d elapsed_ms=%s",
        target_date, stock_rows, sector_rows, elapsed_ms,
    )
    if stock_rows == 0:
        # Nothing to show for that date: say so, so the job log reads FAILED instead of a silent OK.
        raise RuntimeError(f"analytics_refresh: 0 stock cards written for {target_date.isoformat()}")
    return {
        "as_of_date":          target_date.isoformat(),
        "stock_card_rows":     stock_rows,
        "sector_snapshot_rows": sector_rows,
        "elapsed_ms":          elapsed_ms,
        "rows_inserted":       stock_rows + sector_rows,
    }
