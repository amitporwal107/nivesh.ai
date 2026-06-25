"""nidp.mf_holdings_monthly upsert writer."""
from __future__ import annotations

import logging
import uuid
from datetime import date as _date
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


_INSERT_SQL = """
INSERT INTO nidp.mf_holdings_monthly
    (scheme_code, as_of_month, security_isin, security_name,
     instrument_type, sector, rating, maturity_date, ytm_pct,
     quantity, market_value_inr, weight_pct, source, source_url,
     source_run_id, ingested_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, NOW())
ON CONFLICT (scheme_code, as_of_month, security_name, security_isin, source) DO UPDATE SET
    instrument_type  = EXCLUDED.instrument_type,
    sector           = EXCLUDED.sector,
    rating           = EXCLUDED.rating,
    maturity_date    = EXCLUDED.maturity_date,
    ytm_pct          = EXCLUDED.ytm_pct,
    quantity         = EXCLUDED.quantity,
    market_value_inr = EXCLUDED.market_value_inr,
    weight_pct       = EXCLUDED.weight_pct,
    source_url       = EXCLUDED.source_url,
    source_run_id    = EXCLUDED.source_run_id,
    ingested_at      = NOW()
"""


_CHUNK_SIZE = 5_000   # rows per transaction — avoids single-transaction lock on large batches


async def upsert_holdings(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0

    def _as_date(v: Any) -> _date:
        if isinstance(v, _date):
            return v
        return _date.fromisoformat(str(v))

    args = [
        (r["scheme_code"], _as_date(r["as_of_month"]), r.get("security_isin"),
         r["security_name"], r.get("instrument_type"), r.get("sector"),
         r.get("rating"), r.get("maturity_date"), r.get("ytm_pct"),
         r.get("quantity"), r.get("market_value_inr"),
         r.get("weight_pct"), r["source"], r.get("source_url"), run_id)
        for r in rows
    ]

    pool = await get_pool()
    total = 0
    for i in range(0, len(args), _CHUNK_SIZE):
        chunk = args[i : i + _CHUNK_SIZE]
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(_INSERT_SQL, chunk, timeout=120)
        total += len(chunk)
        logger.info(
            "mf_holdings upserted %d/%d rows (chunk %d-%d)",
            total, len(args), i + 1, min(i + _CHUNK_SIZE, len(args)),
        )

    return total
