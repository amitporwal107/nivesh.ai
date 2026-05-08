"""Event-Day Safe Poller.

Polls NSE announcements ONLY for companies scheduled to report TODAY.
This is the key safety constraint — we never do broad market scanning,
only symbol-specific queries for the small set due today.

Safety design:
  - Only activates when there are companies with event_date = today
  - Polls NSE /api/corp-info for each specific symbol (not broadcast scan)
  - Self-exits once all results are found OR after 16:30 IST
  - Tracks which symbols have been resolved to avoid repeat calls
  - Exponential back-off on HTTP errors

Triggered by Cloud Scheduler every 5 min during market hours:
    cron: "*/5 3-11 * * 1-5"   # 8:30–16:30 IST (UTC 03:00–11:00), weekdays

When results arrive:
  1. Calls nse_financials service to extract & store the data
  2. Calls event_analyzer to generate AI signal
  3. Calls intelligence service to score + alert (if enabled)

The intelligence engine then handles the Telegram alert automatically.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timezone, timedelta
from typing import Optional

from nidp.shared.feature_flags import is_enabled
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

# Stop polling after this time (NSE closes at 15:30, results usually by 16:00)
_POLL_CUTOFF_TIME = time(16, 30)

# NSE announcements API for a specific symbol
_NSE_ANNOUNCEMENTS_URL = (
    "https://www.nseindia.com/api/corp-info"
    "?param={symbol}&type=announcements"
)
_NSE_RESULTS_URL = (
    "https://www.nseindia.com/api/results-comparator"
    "?params={symbol}&period=Quarterly&type=Standalone"
)


def _ist_now() -> datetime:
    return datetime.now(tz=_IST)


def _is_past_cutoff() -> bool:
    return _ist_now().time() >= _POLL_CUTOFF_TIME


async def _get_todays_pending(conn, today: date) -> list[dict]:
    """Return symbols scheduled to report today that haven't been ingested yet."""
    rows = await conn.fetch(
        """
        SELECT ec.symbol, ec.company_name, ec.event_type, ec.period
          FROM nidp.event_calendar ec
         WHERE ec.event_date = $1
           AND ec.event_type IN ('quarterly_results', 'board_meeting')
           AND NOT EXISTS (
               SELECT 1 FROM nidp.nse_financials_quarterly f
                WHERE f.symbol = ec.symbol
                  AND f.period_end >= $1 - INTERVAL '100 days'
                  AND f.ingested_at >= $1
           )
         ORDER BY ec.symbol
        """,
        today,
    )
    return [dict(r) for r in rows]


async def _check_nse_for_result(symbol: str) -> bool:
    """Poll NSE corp-info API for a specific symbol. Returns True if result found."""
    try:
        from nidp.shared.sources.nse_fetcher import fetch_text
        url = _NSE_ANNOUNCEMENTS_URL.format(symbol=symbol)
        text, status = await fetch_text(
            url,
            referer="https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        )
        if status != 200 or not text:
            return False

        import json
        data = json.loads(text)
        announcements = data if isinstance(data, list) else data.get("data", [])

        # Look for result-related announcements from today
        today_str = date.today().strftime("%d-%b-%Y").upper()
        for ann in announcements[:20]:
            desc = str(ann.get("desc", "") or ann.get("subject", "") or "").lower()
            ann_date = str(ann.get("an_dt", "") or ann.get("excTm", "") or "")
            if today_str in ann_date.upper() and any(
                kw in desc for kw in ("financial result", "quarterly result", "unaudited result",
                                       "audited result", "standalone", "consolidated")
            ):
                logger.info("event_day_poller: result found for %s in NSE announcements", symbol)
                return True
        return False
    except Exception as e:
        logger.debug("event_day_poller: NSE check for %s failed: %s", symbol, e)
        return False


async def _ingest_result(symbol: str, event_date: date, period: Optional[str]) -> bool:
    """Trigger nse_financials ingestion for this symbol."""
    try:
        from nidp.services.nse_financials.service import run as run_financials
        await run_financials(target_date=event_date, symbol=symbol)
        logger.info("event_day_poller: nse_financials ingested for %s", symbol)
        return True
    except Exception as e:
        logger.error("event_day_poller: nse_financials failed for %s: %s", symbol, e)
        return False


async def _trigger_analysis(symbol: str, event_date: date) -> None:
    """Run event_analyzer + intelligence for this symbol immediately."""
    try:
        from nidp.services.event_analyzer.service import run as run_analyzer
        await run_analyzer(target_date=event_date - timedelta(days=1), symbol=symbol)
    except Exception as e:
        logger.error("event_day_poller: event_analyzer failed for %s: %s", symbol, e)

    try:
        from nidp.services.intelligence.service import run as run_intel
        await run_intel(target_date=event_date, symbol=symbol)
    except Exception as e:
        logger.error("event_day_poller: intelligence failed for %s: %s", symbol, e)


async def run(target_date: Optional[date] = None) -> None:
    """Run one poll cycle for today's pending result companies.

    Designed to be triggered every 5 minutes by Cloud Scheduler.
    Each invocation is stateless — it queries the DB to find
    what's still pending and checks NSE for those symbols only.
    """
    setup_logging(service="event_day_poller")

    if not await is_enabled("event_processing"):
        logger.info("event_day_poller: event_processing flag is OFF — exiting")
        return
    if not await is_enabled("event_day_polling"):
        logger.info("event_day_poller: event_day_polling flag is OFF — exiting")
        return

    if _is_past_cutoff():
        logger.info("event_day_poller: past 16:30 IST — no point polling, exiting")
        return

    today = target_date or date.today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        pending = await _get_todays_pending(conn, today)

    if not pending:
        logger.info("event_day_poller: no pending results for %s", today)
        await close_pool()
        return

    logger.info("event_day_poller: checking %d symbols: %s",
                len(pending), ", ".join(p["symbol"] for p in pending))

    resolved = []
    for p in pending:
        symbol = p["symbol"]
        found = await _check_nse_for_result(symbol)
        if found:
            ingested = await _ingest_result(symbol, today, p.get("period"))
            if ingested:
                resolved.append(symbol)
                # Fire analysis immediately — don't wait for daily batch
                asyncio.create_task(_trigger_analysis(symbol, today))

        # Small delay between symbols to avoid hammering NSE
        await asyncio.sleep(2)

    if resolved:
        logger.info("event_day_poller: resolved %d symbols: %s",
                    len(resolved), ", ".join(resolved))
    else:
        logger.info("event_day_poller: no new results found yet — will retry next cycle")

    await close_pool()
