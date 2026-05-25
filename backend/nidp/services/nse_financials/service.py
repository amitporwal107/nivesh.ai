"""NIDP nse_financials service.

For each company with a result due today (from nidp.event_calendar):
  1. Try company IR page first (fastest — often published before NSE)
  2. Fall back to NSE XBRL comparator API
  3. Use LLM (Claude Haiku) to extract structured numbers from raw text
  4. Upsert into nidp.nse_financials_quarterly
  5. Trigger event_analyzer to generate AI signal

Can be run daily (catches anything due today) or with --symbol for one stock.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

from .ir_scraper import fetch_nse_xbrl, scrape_ir_page
from .llm_extractor import extract_financials, parse_nse_xbrl_json
from .writer import upsert_financials

logger = logging.getLogger(__name__)


def _infer_period_end(event_date: date) -> date:
    """Derive quarter-end date from the result announcement date.

    Indian FY runs April–March. Results are typically announced:
      Jan–Mar  → Q3 results (Oct–Dec)  → Dec 31 of previous year
      Apr–Jul  → Q4 results (Jan–Mar)  → Mar 31 of same year
      Aug–Sep  → Q1 results (Apr–Jun)  → Jun 30 of same year
      Oct–Dec  → Q2 results (Jul–Sep)  → Sep 30 of same year
    """
    m, y = event_date.month, event_date.year
    if m in (1, 2, 3):
        return date(y - 1, 12, 31)
    if m in (4, 5, 6, 7):
        return date(y, 3, 31)
    if m in (8, 9):
        return date(y, 6, 30)
    return date(y, 9, 30)  # Oct, Nov, Dec


def _fill_period_end(data: dict, event_date: date) -> dict:
    """Set period_end in data if LLM left it null, using event_date heuristic."""
    if not data.get("period_end"):
        inferred = _infer_period_end(event_date)
        data["period_end"] = inferred.strftime("%Y-%m-%d")
        logger.info(
            "nse_financials: inferred period_end=%s from event_date=%s",
            data["period_end"], event_date,
        )
    return data


async def _get_due_today(conn, target_date: date) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT ec.symbol, ec.company_name, ec.period, ec.event_date,
               u.ir_url, u.results_url
          FROM nidp.event_calendar ec
          LEFT JOIN nidp.company_ir_urls u ON u.symbol = ec.symbol
         WHERE ec.event_type = 'quarterly_results'
           AND ec.event_date = $1
        """,
        target_date,
    )
    return [dict(r) for r in rows]


async def _process_symbol(
    symbol: str,
    period: Optional[str],
    event_date: date,
    ir_url: Optional[str],
    results_url: Optional[str],
) -> Optional[int]:
    financials_id = None

    # Strategy 1: Company IR page (fastest)
    if ir_url:
        logger.info("nse_financials: trying IR page for %s", symbol)
        raw = await scrape_ir_page(symbol, ir_url, results_url)
        if raw:
            data = await extract_financials(symbol, raw, source_url=results_url or ir_url)
            if data:
                data = _fill_period_end(data, event_date)
                financials_id = await upsert_financials(
                    symbol, data, source="company_ir", ir_url=results_url or ir_url
                )
                if financials_id:
                    logger.info("nse_financials: ✓ %s from company IR page (id=%d)", symbol, financials_id)
                    return financials_id

    # Strategy 2: NSE XBRL comparator
    logger.info("nse_financials: trying NSE XBRL for %s", symbol)
    xbrl_text = await fetch_nse_xbrl(symbol, period)
    if xbrl_text:
        # Try direct XBRL parse first (no LLM tokens)
        data = parse_nse_xbrl_json(symbol, xbrl_text)
        if not data or not data.get("pat_cr"):
            # Fall back to LLM extraction
            data = await extract_financials(symbol, xbrl_text)
        if data:
            data = _fill_period_end(data, event_date)
            financials_id = await upsert_financials(
                symbol, data, source="nse_xbrl"
            )
            if financials_id:
                logger.info("nse_financials: ✓ %s from NSE XBRL (id=%d)", symbol, financials_id)
                return financials_id

    logger.warning("nse_financials: ✗ could not extract financials for %s", symbol)
    return None


async def run(target_date: Optional[date] = None, symbol: Optional[str] = None) -> None:
    setup_logging(service="nse_financials")
    target_date = target_date or date.today()

    pool = await get_pool()
    async with pool.acquire() as conn:
        if symbol:
            due = [{"symbol": symbol.upper(), "company_name": "", "period": None,
                    "event_date": target_date, "ir_url": None, "results_url": None}]
            # Try to get IR URL from DB
            row = await conn.fetchrow(
                "SELECT ir_url, results_url FROM nidp.company_ir_urls WHERE symbol=$1",
                symbol.upper()
            )
            if row:
                due[0].update(dict(row))
        else:
            due = await _get_due_today(conn, target_date)

    if not due:
        logger.info("nse_financials: no results due on %s", target_date)
        await close_pool()
        return

    logger.info("nse_financials: processing %d companies for %s", len(due), target_date)

    results = await asyncio.gather(
        *[_process_symbol(
            d["symbol"], d.get("period"), d.get("event_date") or target_date,
            d.get("ir_url"), d.get("results_url")
        ) for d in due],
        return_exceptions=True,
    )

    success = sum(1 for r in results if isinstance(r, int))
    logger.info("nse_financials: done. %d/%d succeeded", success, len(due))
    await close_pool()
