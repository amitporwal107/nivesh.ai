"""Backfill Screener.in quarterly financials for the full scored stock universe.

Reads symbols from nidp.v_screener_backfill_universe (every stock with recent
features — ~2,300 names, not just Nifty 500), fetches the latest quarter from
Screener.in for each, and upserts into nidp.nse_financials_quarterly. Symbols
without fundamentals are processed first (SD-05).

Skips symbols already ingested via screener_in within the last 6 months
(override with --force).  Throttles to --concurrency parallel requests with
--delay-ms between each to avoid Screener.in rate limits.

Usage:
    python -m nidp.services.nse_financials.backfill_screener
    python -m nidp.services.nse_financials.backfill_screener --concurrency 2 --delay-ms 2000
    python -m nidp.services.nse_financials.backfill_screener --symbols RELIANCE,TCS --force
    python -m nidp.services.nse_financials.backfill_screener --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

from .ir_scraper import fetch_screener_quarters
from .llm_extractor import parse_screener_quarters
from .writer import upsert_financials

logger = logging.getLogger(__name__)

# Re-ingest if the existing row is older than this
_FRESHNESS_WINDOW = timedelta(days=180)


async def _load_symbols(conn, symbols_override: Optional[list[str]]) -> list[str]:
    if symbols_override:
        return [s.upper().strip() for s in symbols_override]
    # Full scored universe (SD-05), missing-fundamentals symbols first so a throttled
    # run delivers coverage fastest. The per-symbol 180-day freshness check still gates
    # whether each one is actually re-fetched.
    rows = await conn.fetch(
        "SELECT symbol FROM nidp.v_screener_backfill_universe "
        "ORDER BY has_fundamentals, symbol"
    )
    return [r["symbol"] for r in rows]


async def _already_ingested(conn, symbol: str) -> bool:
    cutoff = date.today() - _FRESHNESS_WINDOW
    row = await conn.fetchrow(
        """
        SELECT id FROM nidp.nse_financials_quarterly
         WHERE symbol = $1
           AND source = 'screener_in'
           AND period_end >= $2
         LIMIT 1
        """,
        symbol, cutoff,
    )
    return row is not None


async def _process_one(
    symbol: str,
    semaphore: asyncio.Semaphore,
    delay_ms: int,
    force: bool,
    dry_run: bool,
) -> str:
    """Fetch + upsert one symbol. Returns outcome label for stats."""
    async with semaphore:
        # Skip / dry-run checks happen BEFORE the throttle sleep — the delay exists
        # only to rate-limit real Screener.in requests, so already-ingested symbols
        # (the bulk of a full-universe run) cost just a quick DB lookup, not delay_ms.
        if not force and not dry_run:
            pool = await get_pool()
            async with pool.acquire() as conn:
                if await _already_ingested(conn, symbol):
                    logger.debug("backfill: %s already ingested recently, skipping", symbol)
                    return "skipped"

        if dry_run:
            logger.info("backfill [DRY-RUN]: would fetch %s", symbol)
            return "dry_run"

        await asyncio.sleep(delay_ms / 1000)
        result = await fetch_screener_quarters(symbol)
        if not result:
            logger.warning("backfill: %s — not found on Screener.in", symbol)
            return "not_found"

        html, is_consolidated = result
        parsed = parse_screener_quarters(symbol, html, consolidated=is_consolidated)
        if not parsed:
            logger.warning("backfill: %s — parse failed", symbol)
            return "parse_failed"

        data, raw_data = parsed
        if data.get("pat_cr") is None:
            logger.warning("backfill: %s — pat_cr is null, skipping write", symbol)
            return "no_pat"

        fid = await upsert_financials(symbol, data, source="screener_in", raw_data=raw_data)
        if fid:
            logger.info("backfill: ✓ %s  period=%s  pat=%.0f Cr (id=%d)",
                        symbol, data.get("period_end"), data.get("pat_cr", 0), fid)
            return "ok"
        return "write_failed"


async def run(
    symbols_override: Optional[list[str]] = None,
    concurrency: int = 1,
    delay_ms: int = 3000,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    setup_logging(service="nse_financials_backfill")
    pool = await get_pool()

    async with pool.acquire() as conn:
        symbols = await _load_symbols(conn, symbols_override)

    total = len(symbols)
    logger.info("backfill: starting — %d symbols, concurrency=%d, delay=%dms, force=%s, dry_run=%s",
                total, concurrency, delay_ms, force, dry_run)

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        _process_one(sym, semaphore, delay_ms, force, dry_run)
        for sym in symbols
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    counts: dict[str, int] = {}
    for sym, res in zip(symbols, results):
        if isinstance(res, Exception):
            logger.error("backfill: exception for %s: %s", sym, res)
            res = "exception"
        counts[res] = counts.get(res, 0) + 1

    logger.info(
        "backfill: done. total=%d %s",
        total,
        "  ".join(f"{k}={v}" for k, v in sorted(counts.items())),
    )
    await close_pool()


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill Screener.in financials for the scored stock universe")
    p.add_argument("--symbols", default=None,
                   help="Comma-separated symbol override (default: full scored universe, missing-first)")
    p.add_argument("--concurrency", type=int, default=1,
                   help="Max parallel Screener.in requests (default: 1)")
    p.add_argument("--delay-ms", type=int, default=3000,
                   help="Delay between requests in ms (default: 3000)")
    p.add_argument("--force", action="store_true",
                   help="Re-ingest even if already ingested recently")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would be fetched without writing to DB")
    a = p.parse_args()

    symbols = [s.strip() for s in a.symbols.split(",")] if a.symbols else None
    asyncio.run(run(
        symbols_override=symbols,
        concurrency=a.concurrency,
        delay_ms=a.delay_ms,
        force=a.force,
        dry_run=a.dry_run,
    ))


if __name__ == "__main__":
    main()
