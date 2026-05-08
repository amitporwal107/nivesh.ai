"""NIDP event_calendar service.

Fetches the NSE corporate event calendar (board meetings, quarterly results,
dividends, bonuses, splits, AGMs) and upserts into nidp.event_calendar.

Also fetches recently filed financial results (last 3 days) so the
nse_financials service has fresh targets to process.

Runs daily via Cloud Scheduler. Safe to re-run (upserts are idempotent).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from .fetcher import fetch_event_calendar, fetch_recent_results
from .writer import upsert_events

logger = logging.getLogger(__name__)


async def run(target_date: Optional[date] = None) -> None:
    setup_logging(service="event_calendar")

    # 1. Fetch forward calendar (today → +90 days) to track upcoming results
    logger.info("Fetching NSE event calendar...")
    calendar_events = await fetch_event_calendar(
        from_date=date.today() - timedelta(days=7),
        to_date=date.today() + timedelta(days=90),
    )
    n1 = await upsert_events(calendar_events)
    logger.info("event_calendar: upserted %d calendar events", n1)

    # 2. Fetch recently filed results (last 3 days) — triggers nse_financials
    logger.info("Fetching recently filed financial results...")
    recent = await fetch_recent_results(days_back=3)
    # Store recent filings in event_calendar too
    n2 = await upsert_events([e for e in recent if e["event_type"] == "quarterly_results"])
    logger.info("event_calendar: upserted %d recent result filings", n2)

    logger.info("event_calendar: done. total=%d", n1 + n2)
    await close_pool()
