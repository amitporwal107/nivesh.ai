"""nidp.delivery_data writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_SEC_BHAVDATA"


_BATCH_SIZE = 500
_STMT_TIMEOUT_MS = 60_000  # 60s per batch


async def upsert_delivery(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0
    args = [
        (to_date(r["as_of_date"]), r["symbol"], r["series"],
         r.get("traded_qty"), r.get("deliverable_qty"), r.get("deliverable_pct"),
         SOURCE_NAME, run_id)
        for r in rows
    ]

    sql = """
        INSERT INTO nidp.delivery_data
            (as_of_date, symbol, series, traded_qty, deliverable_qty,
             deliverable_pct, source, source_run_id, ingested_at)
        VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, NOW())
        ON CONFLICT (as_of_date, symbol, series, source) DO UPDATE SET
            traded_qty       = EXCLUDED.traded_qty,
            deliverable_qty  = EXCLUDED.deliverable_qty,
            deliverable_pct  = EXCLUDED.deliverable_pct,
            source_run_id    = EXCLUDED.source_run_id,
            ingested_at      = NOW()
    """

    # Batch the upsert to avoid asyncpg executemany TimeoutError
    # on the default 30s socket-level timeout when row count is large
    # (~2k rows * 8 cols * round-trips).
    pool = await get_pool()
    total = 0
    async with pool.acquire() as conn:
        await conn.execute(f"SET LOCAL statement_timeout = {_STMT_TIMEOUT_MS}")
        for i in range(0, len(args), _BATCH_SIZE):
            batch = args[i:i + _BATCH_SIZE]
            async with conn.transaction():
                await conn.executemany(sql, batch, timeout=120)
            total += len(batch)
            logger.info("delivery_data batch upserted %d/%d rows",
                        total, len(args))
    logger.info("delivery_data upserted %d rows total", total)
    return total


# One row per (day, symbol, series): gap-fill should mean only one
# delivery source exists per day, but DISTINCT ON makes the choice
# explicit and deterministic (NSE first) instead of letting the planner
# pick if that invariant is ever broken.
_PROPAGATE_SQL = """
    UPDATE nidp.prices_eod p
       SET deliv_qty = d.deliverable_qty,
           deliv_pct = d.deliverable_pct
      FROM (
            SELECT DISTINCT ON (as_of_date, symbol, series)
                   as_of_date, symbol, series,
                   deliverable_qty, deliverable_pct
              FROM nidp.delivery_data
             WHERE as_of_date = ANY($1::date[])
               AND deliverable_pct IS NOT NULL
             ORDER BY as_of_date, symbol, series,
                      (source = 'NSE_SEC_BHAVDATA') DESC, ingested_at DESC
           ) d
     WHERE p.as_of_date = d.as_of_date
       AND p.symbol     = d.symbol
       AND p.series     = d.series
       AND (p.deliv_pct IS DISTINCT FROM d.deliverable_pct
            OR p.deliv_qty IS DISTINCT FROM d.deliverable_qty)
"""


async def propagate_to_prices_eod(dates: list[Any]) -> int:
    """Copy delivery figures onto the matching nidp.prices_eod rows.

    `delivery_data` and `prices_eod` share the (as_of_date, symbol, series)
    grain but are written by two different ingesters, so prices_eod's
    `deliv_qty` / `deliv_pct` columns were never populated — while
    snapshot_builder, sector_scoring's `deliv_pct_avg_20` accumulation
    pillar and the DaaS /prices routes all read them. This closes that
    gap on every delivery run.

    Returns the number of prices_eod rows updated.
    """
    if not dates:
        return 0
    day_list = [to_date(d) for d in dates]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                f"SET LOCAL statement_timeout = {_STMT_TIMEOUT_MS}")
            status = await conn.execute(_PROPAGATE_SQL, day_list, timeout=120)
    # asyncpg returns e.g. "UPDATE 3310"
    updated = int(status.rsplit(" ", 1)[-1]) if status else 0
    logger.info("prices_eod delivery columns updated for %d row(s) over %d day(s)",
                updated, len(day_list))
    return updated


BSE_SOURCE_NAME = "BSE_DELIVERY"


async def dates_already_covered_by_nse(dates: list[Any]) -> set[Any]:
    """Days for which NSE's own delivery file already landed."""
    if not dates:
        return set()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT as_of_date
              FROM nidp.delivery_data
             WHERE source = $1 AND as_of_date = ANY($2::date[])
            """,
            SOURCE_NAME, [to_date(d) for d in dates],
        )
    return {r["as_of_date"] for r in rows}


async def _isin_to_nse_identity() -> dict[str, tuple[str, str]]:
    """ISIN -> (symbol, series) as NSE names them."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (isin) isin, symbol, series
              FROM nidp.prices_eod
             WHERE source = 'NSE_BHAVCOPY' AND isin IS NOT NULL AND isin <> ''
             ORDER BY isin, as_of_date DESC
            """
        )
    return {r["isin"]: (r["symbol"], r["series"]) for r in rows}


async def upsert_bse_delivery_gapfill(
    rows: list[dict[str, Any]],
    scrip_to_isin: dict[str, str],
    run_id: uuid.UUID,
) -> int:
    """Write BSE delivery rows for days NSE has missed.

    BSE identifies rows by scrip code only, so each row is bridged
    scrip_code -> ISIN (from the same day's BSE bhavcopy) -> NSE
    (symbol, series). Rows whose ISIN is unknown to the NSE universe are
    dropped rather than introducing BSE-only scrips that nothing
    downstream expects. Days NSE already covers are skipped so a symbol
    never carries two delivery rows for one day.
    """
    if not rows:
        return 0

    dates = sorted({r["as_of_date"] for r in rows})
    covered = await dates_already_covered_by_nse(dates)
    universe = await _isin_to_nse_identity()

    args, no_bridge, unknown_isin, skipped_covered = [], 0, 0, 0
    for r in rows:
        if to_date(r["as_of_date"]) in covered:
            skipped_covered += 1
            continue
        isin = scrip_to_isin.get(r["scrip_code"])
        if not isin:
            no_bridge += 1
            continue
        ident = universe.get(isin)
        if ident is None:
            unknown_isin += 1
            continue
        symbol, series = ident
        args.append((
            to_date(r["as_of_date"]), symbol, series,
            r.get("traded_qty"), r.get("deliverable_qty"),
            r.get("deliverable_pct"), BSE_SOURCE_NAME, run_id,
        ))

    logger.info(
        "bse delivery gapfill: %d row(s) to write, %d skipped (NSE has the day), "
        "%d no scrip->ISIN bridge, %d ISIN not in NSE universe",
        len(args), skipped_covered, no_bridge, unknown_isin,
    )
    if not args:
        return 0

    sql = """
        INSERT INTO nidp.delivery_data
            (as_of_date, symbol, series, traded_qty, deliverable_qty,
             deliverable_pct, source, source_run_id, ingested_at)
        VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, NOW())
        ON CONFLICT (as_of_date, symbol, series, source) DO UPDATE SET
            traded_qty       = EXCLUDED.traded_qty,
            deliverable_qty  = EXCLUDED.deliverable_qty,
            deliverable_pct  = EXCLUDED.deliverable_pct,
            source_run_id    = EXCLUDED.source_run_id,
            ingested_at      = NOW()
    """
    pool = await get_pool()
    total = 0
    async with pool.acquire() as conn:
        for i in range(0, len(args), _BATCH_SIZE):
            batch = args[i:i + _BATCH_SIZE]
            async with conn.transaction():
                await conn.executemany(sql, batch, timeout=120)
            total += len(batch)
    logger.info("bse delivery gapfill: wrote %d row(s)", total)
    return total


async def drop_bse_delivery_gapfill_for(dates: list[Any]) -> int:
    """Retire BSE stand-in rows for days NSE has now delivered."""
    if not dates:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            """
            DELETE FROM nidp.delivery_data
             WHERE source = $1 AND as_of_date = ANY($2::date[])
            """,
            BSE_SOURCE_NAME, [to_date(d) for d in dates],
        )
    removed = int(status.rsplit(" ", 1)[-1]) if status else 0
    if removed:
        logger.info("bse delivery gapfill: dropped %d row(s) superseded by NSE",
                    removed)
    return removed
