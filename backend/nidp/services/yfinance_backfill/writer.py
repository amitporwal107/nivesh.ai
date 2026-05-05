"""nidp.prices_eod writer for YFINANCE-sourced rows.

Same target table as bhavcopy/writer but with source='YFINANCE'.
Both sources coexist via the (as_of_date, symbol, series, source)
PK; downstream views prefer NSE_BHAVCOPY when both exist for the
same (date, symbol).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "YFINANCE"

_INSERT_SQL = """
INSERT INTO nidp.prices_eod
    (as_of_date, symbol, series, isin,
     prev_close, open_price, high_price, low_price,
     close_price, last_price, avg_price,
     volume, turnover, trades,
     source, source_run_id, ingested_at)
VALUES ($1::date, $2, $3, $4,
        $5, $6, $7, $8,
        $9, $10, $11,
        $12, $13, $14,
        $15, $16, NOW())
ON CONFLICT (as_of_date, symbol, series, source) DO UPDATE SET
    prev_close    = EXCLUDED.prev_close,
    open_price    = EXCLUDED.open_price,
    high_price    = EXCLUDED.high_price,
    low_price     = EXCLUDED.low_price,
    close_price   = EXCLUDED.close_price,
    volume        = EXCLUDED.volume,
    source_run_id = EXCLUDED.source_run_id,
    ingested_at   = NOW()
"""


async def upsert_yfinance(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (
            to_date(r["as_of_date"]), r["symbol"], r["series"], r.get("isin"),
            r.get("prev_close"), r.get("open_price"), r.get("high_price"), r.get("low_price"),
            r.get("close_price"), r.get("last_price"), r.get("avg_price"),
            r.get("volume"), r.get("turnover"), r.get("trades"),
            SOURCE_NAME, run_id,
        )
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_SQL, args)
    logger.info("yfinance prices_eod upserted %d rows", len(args))
    return len(args)
