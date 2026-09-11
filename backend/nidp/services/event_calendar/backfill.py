"""Backfill event_calendar history from NSE's board-meetings feed.

    python -m nidp.services.event_calendar.backfill --from 2024-06-01 --to 2026-10-31

The live calendar only reaches back to LIVE_SINCE, so a model trained on
it sees one results season. Meetings dated before LIVE_SINCE are inserted
with first_seen_at NULL (NIDP did not observe them live). Meetings on or
after it already exist, so they only get intimated_at filled in — the
snapshot never overwrites what the live ingester captured.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date
from typing import Any

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from .fetcher import fetch_board_meetings
from .writer import stamp_existing, upsert_events

logger = logging.getLogger(__name__)

# First event_date in nidp.event_calendar when intimated_at was introduced
# (2026-09-11); everything from here on was captured by the live ingester.
LIVE_SINCE = date(2026, 5, 19)


def split_by_live_coverage(events: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """(history to insert, live-era rows to stamp)."""
    history = [e for e in events if e["event_date"] < LIVE_SINCE]
    live_era = [e for e in events if e["event_date"] >= LIVE_SINCE]
    return history, live_era


async def backfill(from_date: date, to_date: date) -> dict[str, int]:
    meetings = await fetch_board_meetings(from_date, to_date)
    history, live_era = split_by_live_coverage(meetings)
    inserted = await upsert_events(history, backfill=True)
    stamped = await stamp_existing(live_era)
    result = {"meetings": len(meetings), "history_rows_written": inserted,
              "live_rows_stamped": stamped, "rows_written": inserted + stamped}
    logger.info("event_calendar_backfill %s", result)
    return result


async def _main(args: argparse.Namespace) -> None:
    try:
        result = await run_with_job_log(
            "event_calendar_backfill", backfill, args.from_date, args.to_date,
            target_date=args.to_date,
        )
        print(json.dumps(result))
    finally:
        await close_pool()


def main() -> None:
    setup_logging(service="event_calendar_backfill")
    p = argparse.ArgumentParser(description="Backfill nidp.event_calendar from NSE board meetings")
    p.add_argument("--from", dest="from_date", type=date.fromisoformat, required=True)
    p.add_argument("--to", dest="to_date", type=date.fromisoformat, required=True)
    asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    main()
