"""Fill sector_master.sector / industry from NSE's industry classification on Screener.in.

sector_master.sector was seeded once (migration 080) from the Nifty 500 index list, so none
of the next 500 stocks has a sector: 0 of 494 on 2026-09-13. Sector-relative valuation
(sector median P/E), the sector-aware V3 scorer and peer comparison all go blind for them.
NSE's quote API carries the classification but answers 403 from the VM; the Nifty Total
Market list adds only the Microcap 250. Every Screener.in company page links NSE's four-level
classification, whose "Sector" level is the Nifty 500 list's "Industry" column (Screener
spells it with commas: "Oil, Gas & Consumable Fuels").

Only rows with a NULL sector are written, so index-derived and manual sectors are never
overwritten. --validate N compares against N stocks that already have an index-derived
sector, without writing.

Usage:
    python -m nidp.services.nse_financials.screener_sector --validate 40
    python -m nidp.services.nse_financials.screener_sector --dry-run
    python -m nidp.services.nse_financials.screener_sector --symbols KPEL,CMPDI
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
from typing import Optional

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

from .ir_scraper import fetch_screener_quarters
from .llm_extractor import parse_screener_classification

logger = logging.getLogger(__name__)

SOURCE = "screener_nse_classification"

# Nifty 500 list "Industry" (= classification Sector level) -> sector_master.sector.
# Same labels as migration 080, which the sector scorer's keyword profiles depend on.
SECTOR_LABEL: dict[str, str] = {
    "Financial Services": "Finance",
    "Capital Goods": "Capital Goods",
    "Healthcare": "Healthcare",
    "Automobile and Auto Components": "Automobile",
    "Fast Moving Consumer Goods": "FMCG",
    "Consumer Durables": "Consumer Durables",
    "Consumer Services": "Consumer Services",
    "Information Technology": "Information Technology",
    "Chemicals": "Chemicals",
    "Metals & Mining": "Metals",
    "Construction Materials": "Construction Materials",
    "Construction": "Construction",
    "Realty": "Realty",
    "Oil Gas & Consumable Fuels": "Oil Gas",
    "Power": "Power",
    "Textiles": "Textiles",
    "Telecommunication": "Telecommunication",
    "Services": "Services",
    "Media Entertainment & Publication": "Media",
    "Diversified": "Diversified",
}


def nifty500_industry(label: str) -> str:
    """Screener's Sector label in the Nifty 500 list's spelling (no commas)."""
    return re.sub(r"\s+", " ", label.replace(",", "")).strip()


def sector_fields(classification: dict[str, str]) -> tuple[str, str]:
    """(sector, industry) as migration 080 stores them; unknown labels pass through as-is."""
    industry = nifty500_industry(classification["sector"])
    return SECTOR_LABEL.get(industry, industry), industry


async def _targets(conn, symbols: Optional[list[str]], validate: int) -> list[dict]:
    if symbols:
        rows = await conn.fetch(
            "SELECT symbol, sector, industry FROM nidp.sector_master WHERE symbol = ANY($1::text[])",
            [s.strip().upper() for s in symbols])
    elif validate:
        rows = await conn.fetch(
            "SELECT symbol, sector, industry FROM nidp.sector_master "
            "WHERE sector_source = 'index_constituents' ORDER BY md5(symbol) LIMIT $1", validate)
    else:
        rows = await conn.fetch(
            "SELECT sm.symbol, sm.sector, sm.industry FROM nidp.sector_master sm "
            "JOIN nidp.v_screener_backfill_universe u USING (symbol) "
            "WHERE sm.sector IS NULL ORDER BY sm.symbol")
    return [dict(r) for r in rows]


async def run(symbols: Optional[list[str]] = None, validate: int = 0,
              dry_run: bool = False, delay_ms: int = 3000) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        targets = await _targets(conn, symbols, validate)
    stats = {"targets": len(targets), "classified": 0, "written": 0, "not_found": 0,
             "no_breadcrumb": 0, "agree": 0, "disagree": 0}
    logger.info("screener_sector: %d symbols (validate=%s dry_run=%s)", len(targets), validate, dry_run)

    for i, t in enumerate(targets):
        if i:
            await asyncio.sleep(delay_ms / 1000)
        try:
            fetched = await fetch_screener_quarters(t["symbol"])
        except RuntimeError as exc:
            logger.error("screener_sector: Screener.in blocked at %s (%s) — stopping", t["symbol"], exc)
            stats["blocked_at"] = t["symbol"]
            break
        if not fetched:
            stats["not_found"] += 1
            continue
        cls = parse_screener_classification(t["symbol"], fetched[0])
        if not cls:
            stats["no_breadcrumb"] += 1
            continue
        stats["classified"] += 1
        sector, industry = sector_fields(cls)

        if validate:
            same = (sector, industry) == (t["sector"], t["industry"])
            stats["agree" if same else "disagree"] += 1
            if not same:
                logger.warning("screener_sector: %s index says (%s, %s), Screener says (%s, %s)",
                               t["symbol"], t["sector"], t["industry"], sector, industry)
            continue
        if dry_run:
            logger.info("screener_sector [DRY-RUN] %s -> %s / %s", t["symbol"], sector, industry)
            continue
        async with pool.acquire() as conn:
            status = await conn.execute(
                """
                UPDATE nidp.sector_master
                   SET sector = $2, industry = $3, sector_source = $4, sector_resolved_at = NOW()
                 WHERE symbol = $1 AND sector IS NULL
                """,
                t["symbol"], sector, industry, SOURCE,
            )
        stats["written"] += int(status.split()[-1])

    logger.info("screener_sector: done — %s", stats)
    return stats


def main() -> None:
    setup_logging("screener_sector")
    p = argparse.ArgumentParser(description="sector_master sector/industry from Screener.in's NSE classification")
    p.add_argument("--symbols", default=None, help="comma-separated NSE symbols")
    p.add_argument("--validate", type=int, default=0,
                   help="compare N index-derived sectors against Screener, write nothing")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--delay-ms", type=int, default=3000)
    a = p.parse_args()

    async def _go() -> None:
        try:
            await run(symbols=a.symbols.split(",") if a.symbols else None, validate=a.validate,
                      dry_run=a.dry_run, delay_ms=a.delay_ms)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
