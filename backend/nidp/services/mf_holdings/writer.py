"""nidp.mf_holdings_monthly upsert writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


_INSERT_SQL = """
INSERT INTO nidp.mf_holdings_monthly
    (scheme_code, as_of_month, security_isin, security_name,
     instrument_type, sector, rating, quantity, market_value_inr,
     weight_pct, source, source_url, source_run_id, ingested_at)
VALUES ($1, $2::date, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
ON CONFLICT (scheme_code, as_of_month, security_name, source) DO UPDATE SET
    security_isin    = EXCLUDED.security_isin,
    instrument_type  = EXCLUDED.instrument_type,
    sector           = EXCLUDED.sector,
    rating           = EXCLUDED.rating,
    quantity         = EXCLUDED.quantity,
    market_value_inr = EXCLUDED.market_value_inr,
    weight_pct       = EXCLUDED.weight_pct,
    source_url       = EXCLUDED.source_url,
    source_run_id    = EXCLUDED.source_run_id,
    ingested_at      = NOW()
"""


async def upsert_holdings(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (r["scheme_code"], r["as_of_month"], r.get("security_isin"),
         r["security_name"], r.get("instrument_type"), r.get("sector"),
         r.get("rating"), r.get("quantity"), r.get("market_value_inr"),
         r.get("weight_pct"), r["source"], r.get("source_url"), run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_SQL, args)
    logger.info("mf_holdings upserted %d rows", len(args))
    return len(args)
