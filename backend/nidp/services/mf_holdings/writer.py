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

# Single-source invariant: a scheme's portfolio for a month comes from ONE
# disclosure. Before writing, drop any OTHER-source rows for exactly the
# (scheme_code, as_of_month) pairs in this batch — so migrating an AMC to a new
# source (e.g. its AdvisorKhoj adapter) never leaves the old source's rows behind
# to double-count downstream. Scoped to the pairs we are writing: schemes/months
# NOT in this batch (e.g. HDFC when only ICICI runs) are untouched. In steady
# state each scheme already has one source, so this is a no-op.
_REPLACE_STALE_SQL = """
DELETE FROM nidp.mf_holdings_monthly h
USING unnest($1::text[], $2::date[], $3::text[]) AS n(scheme_code, as_of_month, keep_source)
WHERE h.scheme_code = n.scheme_code
  AND h.as_of_month = n.as_of_month
  AND h.source <> n.keep_source
"""


def _as_date(v: Any) -> _date:
    if isinstance(v, _date):
        return v
    return _date.fromisoformat(str(v))


async def upsert_holdings(
    rows: list[dict[str, Any]], run_id: uuid.UUID, *, replace_stale_sources: bool = True,
) -> int:
    if not rows:
        return 0

    args = [
        (r["scheme_code"], _as_date(r["as_of_month"]), r.get("security_isin"),
         r["security_name"], r.get("instrument_type"), r.get("sector"),
         r.get("rating"), r.get("maturity_date"), r.get("ytm_pct"),
         r.get("quantity"), r.get("market_value_inr"),
         r.get("weight_pct"), r["source"], r.get("source_url"), run_id)
        for r in rows
    ]

    pool = await get_pool()

    if replace_stale_sources:
        # One authoritative source per (scheme_code, as_of_month) in this batch.
        keep: dict[tuple[str, _date], str] = {}
        for r in rows:
            keep[(r["scheme_code"], _as_date(r["as_of_month"]))] = r["source"]
        codes = [k[0] for k in keep]
        months = [k[1] for k in keep]
        sources = [keep[k] for k in keep]
        async with pool.acquire() as conn:
            removed = await conn.execute(_REPLACE_STALE_SQL, codes, months, sources, timeout=120)
        logger.info("mf_holdings replace: %s over %d scheme/month pairs", removed, len(keep))

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
