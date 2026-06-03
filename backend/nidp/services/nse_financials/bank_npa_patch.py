"""Patch NPA data into consolidated bank rows from Screener.in standalone pages.

Screener.in reports NPA percentages (Gross NPA %, Net NPA %) only on the
STANDALONE page — the consolidated quarterly table leaves these cells empty.
Since our backfill prefers consolidated for P&L/revenue data, NPA ends up null.

This script:
  1. Fetches the standalone Screener page for each bank symbol
  2. Extracts the 'gross npa %' and 'net npa %' time-series arrays
  3. Patches them into the consolidated raw_data JSONB in nse_financials_quarterly

Run after the main screener backfill to get full NPA coverage:
    SCREENER_SESSION_COOKIE=<cookie> python -m nidp.services.nse_financials.bank_npa_patch
    python -m nidp.services.nse_financials.bank_npa_patch --symbols HDFCBANK,ICICIBANK
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Optional

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

from .ir_scraper import _SCREENER_SLUG_MAP, _get_text, _screener_is_rate_limited
from .llm_extractor import _parse_screener_section

logger = logging.getLogger(__name__)

# Banks for which Screener.in stores NPA only on standalone page
_BANK_SYMBOLS = [
    "HDFCBANK", "ICICIBANK", "AXISBANK", "SBIN", "PNB",
    "BANKBARODA", "BANKINDIA", "UNIONBANK", "IOB",
    "IDFCFIRSTB", "RBLBANK", "BANDHANBNK", "J&KBANK",
    "KOTAKBANK", "INDUSINDBK", "FEDERALBNK", "CSBBANK",
    "DCBBANK", "KARNATAKA", "LAKSHVILAS",
]


async def _fetch_standalone_npa(symbol: str) -> Optional[tuple[list[Optional[float]], list[Optional[float]], list[str]]]:
    """Fetch standalone page and return (gnpa_series, nnpa_series, quarter_labels) or None."""
    slug = _SCREENER_SLUG_MAP.get(symbol, symbol)
    url = f"https://www.screener.in/company/{slug}/"
    html = await _get_text(url)
    if not html or len(html) < 1000:
        return None

    if _screener_is_rate_limited(html):
        raise RuntimeError(f"Screener.in rate-limit for {symbol}")

    result = _parse_screener_section(html, "quarters")
    if not result:
        return None

    quarter_labels, raw_table = result
    gnpa_series: list[Optional[float]] = raw_table.get("gross npa %", [])
    nnpa_series: list[Optional[float]] = raw_table.get("net npa %", [])

    # Both series absent or all-null → nothing to patch
    if not gnpa_series and not nnpa_series:
        return None
    has_data = any(v is not None for v in gnpa_series) or any(v is not None for v in nnpa_series)
    if not has_data:
        return None

    return gnpa_series, nnpa_series, quarter_labels


async def _patch_npa_in_db(symbol: str, gnpa: list, nnpa: list) -> int:
    """Patch gnpa / nnpa arrays into raw_data rows for the symbol.

    Prefers consolidated rows; falls back to standalone if no consolidated
    rows exist (e.g. BANDHANBNK which Screener only has on standalone page).
    Returns number of rows updated.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Try consolidated first
        result = await conn.execute(
            """
            UPDATE nidp.nse_financials_quarterly
               SET raw_data = jsonb_set(
                       jsonb_set(
                           raw_data,
                           '{data,gross npa %}',
                           $1::jsonb
                       ),
                       '{data,net npa %}',
                       $2::jsonb
                   ),
                   ingested_at = NOW()
             WHERE symbol = $3
               AND consolidated = TRUE
               AND raw_data IS NOT NULL
            """,
            json.dumps(gnpa),
            json.dumps(nnpa),
            symbol,
        )
        count = int(result.split()[-1]) if result else 0

        # If no consolidated rows, fall back to standalone
        if count == 0:
            result = await conn.execute(
                """
                UPDATE nidp.nse_financials_quarterly
                   SET raw_data = jsonb_set(
                           jsonb_set(
                               raw_data,
                               '{data,gross npa %}',
                               $1::jsonb
                           ),
                           '{data,net npa %}',
                           $2::jsonb
                       ),
                       ingested_at = NOW()
                 WHERE symbol = $3
                   AND consolidated = FALSE
                   AND raw_data IS NOT NULL
                """,
                json.dumps(gnpa),
                json.dumps(nnpa),
                symbol,
            )
            count = int(result.split()[-1]) if result else 0

    return count


async def run(symbols: Optional[list[str]] = None, delay_ms: int = 2000) -> None:
    targets = symbols or _BANK_SYMBOLS
    logger.info("bank_npa_patch: starting for %d symbols", len(targets))

    ok = skipped = failed = 0
    for symbol in targets:
        await asyncio.sleep(delay_ms / 1000)
        try:
            result = await _fetch_standalone_npa(symbol)
            if not result:
                logger.warning("bank_npa_patch: %s — no NPA data on standalone page", symbol)
                skipped += 1
                continue

            gnpa, nnpa, quarters = result
            logger.info(
                "bank_npa_patch: %s — gnpa=%s nnpa=%s (%d quarters)",
                symbol,
                [v for v in gnpa if v is not None][-3:] if gnpa else [],
                [v for v in nnpa if v is not None][-3:] if nnpa else [],
                len(quarters),
            )
            patched = await _patch_npa_in_db(symbol, gnpa, nnpa)
            if patched:
                logger.info("bank_npa_patch: ✓ %s — patched %d consolidated rows", symbol, patched)
                ok += 1
            else:
                logger.warning("bank_npa_patch: %s — 0 rows updated (no consolidated rows?)", symbol)
                skipped += 1

        except RuntimeError as e:
            logger.error("bank_npa_patch: %s — %s", symbol, e)
            failed += 1
        except Exception as e:
            logger.error("bank_npa_patch: %s — unexpected error: %s", symbol, e)
            failed += 1

    logger.info(
        "bank_npa_patch: done. ok=%d  skipped=%d  failed=%d",
        ok, skipped, failed,
    )
    await close_pool()


def main() -> None:
    p = argparse.ArgumentParser(description="Patch NPA arrays from standalone into consolidated bank rows")
    p.add_argument("--symbols", default=None,
                   help="Comma-separated symbols (default: all known bank symbols)")
    p.add_argument("--delay-ms", type=int, default=2000,
                   help="Delay between Screener.in requests in ms (default: 2000)")
    a = p.parse_args()

    symbols = [s.strip() for s in a.symbols.split(",")] if a.symbols else None
    setup_logging(service="bank_npa_patch")
    asyncio.run(run(symbols=symbols, delay_ms=a.delay_ms))


if __name__ == "__main__":
    main()
