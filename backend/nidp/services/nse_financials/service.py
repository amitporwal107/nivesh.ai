"""NIDP nse_financials service.

For each company with a result due today (from nidp.event_calendar):
  1. Try NSE Integrated XBRL filing (_WEB.xml via corporate-announcements API)
  2. Try Screener.in quarterly table (structured HTML — no LLM tokens; reliable for Nifty 50)
  3. Fall back to company IR page (manual ir_url seeded in company_ir_urls)
  4. Fall back to NSE XBRL comparator API
  5. Use LLM to extract structured numbers from raw text (strategies 3 & 4)
  6. Upsert into nidp.nse_financials_quarterly

Can be run daily (catches anything due today) or with --symbol for one stock.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

from .ir_scraper import fetch_nse_integrated_filing, fetch_nse_xbrl, fetch_screener_quarters, scrape_ir_page
from .llm_extractor import (
    extract_financials,
    parse_nse_integrated_xbrl,
    parse_nse_xbrl_json,
    parse_screener_balance_sheet,
    parse_screener_profit_loss,
    parse_screener_quarters,
    parse_screener_shareholding,
)
from .writer import upsert_financials, upsert_shareholding

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

    # Strategy 1: NSE Integrated XBRL filing (structured XML — no LLM tokens)
    logger.info("nse_financials: trying NSE integrated filing XBRL for %s", symbol)
    xml_text = await fetch_nse_integrated_filing(symbol)
    if xml_text:
        data = parse_nse_integrated_xbrl(symbol, xml_text)
        if data and data.get("pat_cr") is not None:
            data = _fill_period_end(data, event_date)
            financials_id = await upsert_financials(symbol, data, source="nse_integrated_xbrl")
            if financials_id:
                logger.info("nse_financials: ✓ %s from NSE integrated XBRL (id=%d)", symbol, financials_id)
                return financials_id

    # Strategy 2: Screener.in quarterly table (structured HTML — no LLM tokens)
    logger.info("nse_financials: trying Screener.in for %s", symbol)
    screener_result = await fetch_screener_quarters(symbol)
    if screener_result:
        html, is_consolidated = screener_result

        # ── Always extract supplemental data from the same page fetch ──
        # Balance sheet (annual: equity, reserves, borrowings)
        bs_entries = parse_screener_balance_sheet(symbol, html, consolidated=is_consolidated)
        for bs in bs_entries:
            await upsert_financials(symbol, bs, source="screener_in_bs")

        # Annual P&L (revenue + PAT history for 3Y CAGR primitives)
        pl_entries = parse_screener_profit_loss(symbol, html, consolidated=is_consolidated)
        for pl in pl_entries:
            await upsert_financials(symbol, pl, source="screener_in_annual")

        # Shareholding pattern (promoter_pct primitive)
        shp_entries = parse_screener_shareholding(symbol, html)
        for shp in shp_entries:
            await upsert_shareholding(symbol, shp, source="screener_in")

        logger.info(
            "nse_financials: %s supplemental from Screener.in — %d bs_years  %d pl_years  %d shp",
            symbol, len(bs_entries), len(pl_entries), len(shp_entries),
        )

        # ── Latest-quarter P&L (primary quarterly record) ──────────────
        parsed = parse_screener_quarters(symbol, html, consolidated=is_consolidated)
        if parsed:
            data, raw_data = parsed
            if data.get("pat_cr") is not None:
                data = _fill_period_end(data, event_date)
                financials_id = await upsert_financials(
                    symbol, data, source="screener_in", raw_data=raw_data
                )
                if financials_id:
                    logger.info("nse_financials: ✓ %s from Screener.in (id=%d)", symbol, financials_id)
                    return financials_id

    # Strategy 3: Company IR page or direct XBRL URL (seeded in company_ir_urls)
    if ir_url or results_url:
        logger.info("nse_financials: trying IR/results URL for %s", symbol)
        raw = await scrape_ir_page(symbol, ir_url or results_url, results_url)
        if raw:
            # If it's XBRL XML (results_url pointed directly at a _WEB.xml), parse structurally
            if raw.lstrip().startswith("<?xml"):
                data = parse_nse_integrated_xbrl(symbol, raw)
            else:
                data = await extract_financials(symbol, raw, source_url=results_url or ir_url)
            if data:
                data = _fill_period_end(data, event_date)
                financials_id = await upsert_financials(
                    symbol, data, source="company_ir", ir_url=results_url or ir_url
                )
                if financials_id:
                    logger.info("nse_financials: ✓ %s from company IR page (id=%d)", symbol, financials_id)
                    return financials_id

    # Strategy 4: NSE XBRL comparator (JSON API)
    logger.info("nse_financials: trying NSE XBRL comparator for %s", symbol)
    xbrl_text = await fetch_nse_xbrl(symbol, period)
    if xbrl_text:
        data = parse_nse_xbrl_json(symbol, xbrl_text)
        if not data or not data.get("pat_cr"):
            data = await extract_financials(symbol, xbrl_text)
        if data:
            data = _fill_period_end(data, event_date)
            financials_id = await upsert_financials(symbol, data, source="nse_xbrl")
            if financials_id:
                logger.info("nse_financials: ✓ %s from NSE XBRL comparator (id=%d)", symbol, financials_id)
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

    success = 0
    for d, r in zip(due, results):
        if isinstance(r, int):
            success += 1
        elif isinstance(r, Exception):
            logger.error("nse_financials: exception for %s: %s", d["symbol"], r)

    logger.info("nse_financials: done. %d/%d succeeded", success, len(due))
    await close_pool()
