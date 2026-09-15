"""nidp.prices_eod append-only writer (NSE bhavcopy).

Bhavcopy lands ~30k rows/day. We use asyncpg's `executemany` with a
single transaction so a parse anomaly mid-stream rolls back cleanly.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "NSE_BHAVCOPY"

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
    isin          = EXCLUDED.isin,
    prev_close    = EXCLUDED.prev_close,
    open_price    = EXCLUDED.open_price,
    high_price    = EXCLUDED.high_price,
    low_price     = EXCLUDED.low_price,
    close_price   = EXCLUDED.close_price,
    last_price    = EXCLUDED.last_price,
    avg_price     = EXCLUDED.avg_price,
    volume        = EXCLUDED.volume,
    turnover      = EXCLUDED.turnover,
    trades        = EXCLUDED.trades,
    source_run_id = EXCLUDED.source_run_id,
    ingested_at   = NOW()
"""


async def upsert_bhavcopy(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
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
    logger.info("prices_eod upserted %d rows", len(args))
    return len(args)


BSE_SOURCE_NAME = "BSE_BHAVCOPY"


async def _nse_universe() -> dict[str, tuple[str, str]]:
    """ISIN -> (symbol, series) for everything NSE bhavcopy has ever written.

    BSE's ticker and series vocabularies differ from NSE's (group codes
    A/B/X/T vs EQ/BE/SM/ST), and every downstream consumer filters on the
    NSE vocabulary — `series = 'EQ'` in d1_prep and price_adjuster,
    `series IN ('EQ','BE','BZ','SM')` in snapshot_builder. Writing BSE's
    own codes would therefore be invisible to all of them. Instead we
    re-key BSE rows onto the NSE identity via ISIN, which both files
    carry, so a fallback day looks exactly like a normal day.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (isin) isin, symbol, series
              FROM nidp.prices_eod
             WHERE source = $1 AND isin IS NOT NULL AND isin <> ''
             ORDER BY isin, as_of_date DESC
            """,
            SOURCE_NAME,
        )
    return {r["isin"]: (r["symbol"], r["series"]) for r in rows}


async def dates_already_covered_by_nse(dates: list[Any]) -> set[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT as_of_date
              FROM nidp.prices_eod
             WHERE source = $1 AND as_of_date = ANY($2::date[])
            """,
            SOURCE_NAME, [to_date(d) for d in dates],
        )
    return {r["as_of_date"] for r in rows}


async def upsert_bse_gapfill(rows: list[dict[str, Any]],
                             run_id: uuid.UUID) -> int:
    """Write BSE bhavcopy rows, but only where NSE has left a hole.

    Two guards keep prices_eod's meaning intact:

    1. **Gap-fill only.** A date NSE already covered is skipped entirely,
       so a symbol never has both an NSE and a BSE row for one day.
       Without this, consumers that filter on `series` but not `source`
       would silently double-count.
    2. **Known universe only.** A BSE row is kept only if its ISIN is
       already known from NSE bhavcopy, and it is written under NSE's
       symbol/series. BSE-only scrips (~2k microcaps, plus the X/XT/Z
       groups) are dropped rather than injected into a universe that
       nothing downstream expects.

    Returns the number of rows written.
    """
    if not rows:
        return 0

    dates = sorted({r["as_of_date"] for r in rows})
    covered = await dates_already_covered_by_nse(dates)
    universe = await _nse_universe()

    args, skipped_unknown, skipped_covered = [], 0, 0
    for r in rows:
        if to_date(r["as_of_date"]) in covered:
            skipped_covered += 1
            continue
        ident = universe.get((r.get("isin") or "").strip())
        if ident is None:
            skipped_unknown += 1
            continue
        symbol, series = ident
        args.append((
            to_date(r["as_of_date"]), symbol, series, r.get("isin"),
            r.get("prev_close"), r.get("open_price"), r.get("high_price"),
            r.get("low_price"), r.get("close_price"), r.get("last_price"),
            r.get("avg_price"), r.get("volume"), r.get("turnover"),
            r.get("trades"), BSE_SOURCE_NAME, run_id,
        ))

    logger.info(
        "bse gapfill: %d row(s) to write, %d skipped (NSE already has the day), "
        "%d skipped (ISIN not in NSE universe)",
        len(args), skipped_covered, skipped_unknown,
    )
    if not args:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_SQL, args)
    return len(args)


async def drop_bse_gapfill_for(dates: list[Any]) -> int:
    """Remove BSE placeholder rows for dates NSE has now delivered.

    NSE is the primary source; once a real NSE bhavcopy lands for a day,
    the BSE stand-in for that day must go, or the day carries two rows
    per symbol and every `series`-filtered consumer double-counts.
    """
    if not dates:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            """
            DELETE FROM nidp.prices_eod
             WHERE source = $1 AND as_of_date = ANY($2::date[])
            """,
            BSE_SOURCE_NAME, [to_date(d) for d in dates],
        )
    removed = int(status.rsplit(" ", 1)[-1]) if status else 0
    if removed:
        logger.info("bse gapfill: dropped %d placeholder row(s) superseded "
                    "by NSE bhavcopy", removed)
    return removed
