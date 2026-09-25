"""Point-in-time BSE scrip master — one row per scrip per trading day.

Fetches the BSE SEBI-standard daily equity bhavcopy (the same file nidp already
uses as an NSE fallback) and persists scrip_code, ISIN, BSE ticker, trading group
and company name for that day. See migration 153 for why this must be dated and
not a current-state master.

    python -m nidp.services.bse_scrip_master --date 2026-09-24
    python -m nidp.services.bse_scrip_master --from 2024-06-01 --to 2026-09-24

The backfill skips days already written, so it is safe to re-run after an
interruption. A non-trading day returns 404 from BSE and is recorded as a skip,
not a failure — BSE publishes nothing for holidays and the NSE holiday calendar
is not authoritative for BSE.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from nidp.services.bhavcopy.parser import (looks_like_html,
                                           parse_bse_scrip_master)
from nidp.shared.sources.bse_fetcher import bhavcopy_url, fetch_bytes

from .writer import dates_present, upsert_scrip_master

logger = logging.getLogger(__name__)

# BSE serves the archive without complaint, but this runs thousands of requests
# on a backfill; keep it polite.
PAUSE_SECONDS = 0.6
# A day with far fewer scrips than this is a truncated or error response, not a
# thin trading day — the file carried 4,999 equity scrips on 2026-09-24.
MIN_PLAUSIBLE_ROWS = 2000


@dataclass
class Report:
    days_written: int = 0
    days_skipped_present: int = 0
    days_no_file: int = 0
    days_failed: int = 0
    rows_written: int = 0
    suspect_days: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "days_written": self.days_written,
            "days_skipped_present": self.days_skipped_present,
            "days_no_file": self.days_no_file,
            "days_failed": self.days_failed,
            "rows_written": self.rows_written,
            "suspect_days": self.suspect_days,
        }


async def ingest_day(target: date, run_id: uuid.UUID, rep: Report) -> int:
    """Fetch, parse and write one trading day. Returns rows written."""
    url = bhavcopy_url(target)
    try:
        body, status = await fetch_bytes(url)
    except Exception as exc:                                   # noqa: BLE001
        # 404 on a holiday is expected and is not an error.
        if "404" in str(exc):
            rep.days_no_file += 1
            logger.info("bse_scrip_master: no file for %s (holiday?)", target)
            return 0
        rep.days_failed += 1
        logger.warning("bse_scrip_master: fetch failed for %s: %s", target, exc)
        return 0
    if status == 404:
        rep.days_no_file += 1
        return 0

    if looks_like_html(body):
        rep.days_no_file += 1
        logger.info("bse_scrip_master: %s served HTML, not a bhavcopy "
                    "(holiday?)", target)
        return 0

    rows = parse_bse_scrip_master(body)
    if not rows:
        rep.days_failed += 1
        logger.warning("bse_scrip_master: %s parsed to 0 rows (%d bytes)",
                       target, len(body))
        return 0
    if len(rows) < MIN_PLAUSIBLE_ROWS:
        # Write it — a short day is still real data — but surface it, because a
        # truncated file would otherwise look like a mass delisting downstream.
        rep.suspect_days.append(f"{target}:{len(rows)}")
        logger.warning("bse_scrip_master: %s only %d scrips (expected >%d)",
                       target, len(rows), MIN_PLAUSIBLE_ROWS)

    n = await upsert_scrip_master(target, rows, run_id)
    rep.days_written += 1
    rep.rows_written += n
    return n


async def run(target: date | None = None, start: date | None = None,
              end: date | None = None, *, resume: bool = True) -> dict:
    """One day, or a [start, end] backfill."""
    run_id = uuid.uuid4()
    rep = Report()

    if target is not None:
        await ingest_day(target, run_id, rep)
        logger.info("bse_scrip_master %s: %s", target, rep.as_dict())
        return rep.as_dict()

    if start is None or end is None:
        raise ValueError("pass --date, or both --from and --to")

    have = await dates_present(start, end) if resume else set()
    d = start
    while d <= end:
        if d.weekday() >= 5:                     # BSE does not trade weekends
            d += timedelta(days=1)
            continue
        if d in have:
            rep.days_skipped_present += 1
            d += timedelta(days=1)
            continue
        await ingest_day(d, run_id, rep)
        await asyncio.sleep(PAUSE_SECONDS)
        if (rep.days_written + rep.days_no_file) % 25 == 0 and rep.days_written:
            logger.info("bse_scrip_master progress @%s: %s", d, rep.as_dict())
        d += timedelta(days=1)

    logger.info("bse_scrip_master %s..%s: %s", start, end, rep.as_dict())
    return rep.as_dict()
