"""Stamp nse_financials_quarterly.broadcast_at from NSE's financial-results listing.

broadcast_at -- when the market could first see a quarter's numbers -- was NULL on every
row, so no fundamental was usable point-in-time: a backtest that uses a quarter from its
period-end date trades on numbers that were not yet public. Two causes:
  * the parser read "broadcastDate"; NSE sends "broadCastDate" (fixed in parser.py);
  * the rows that exist were written by the Screener and Yahoo backfills, which carry no
    filing time at all.

NSE's /api/corporates-financial-results lists every results filing with its broadcast
timestamp. Its date filter applies to the BROADCAST date, so late filers land where they
belong (AHLWEST filed its March-2021 results on 30-Jun-2024).

The timestamp is keyed on (symbol, period_end) and is the EARLIEST broadcast for that key,
across both bases and any later revision: a quarter's results are public once either the
consolidated or the standalone filing is out (they are filed minutes apart), and a revised
filing does not make the original un-public. Only rows whose broadcast_at IS NULL are
touched, so a timestamp from a better source is never overwritten.

Usage:
    python -m nidp.services.nse_financials.stamp_broadcast_at --from 2022-01-01 --to 2026-09-13
    python -m nidp.services.nse_financials.stamp_broadcast_at --from 2026-08-01 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from nidp.shared.logging_setup import setup_logging
from nidp.shared.sources.nse_fetcher import close as close_fetcher
from nidp.shared.sources.nse_fetcher import fetch_text
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_NSE = "https://www.nseindia.com"
_LISTING = f"{_NSE}/api/corporates-financial-results"
_REFERER = f"{_NSE}/companies-listing/corporate-filings-financial-results"
_PERIODS = ("Quarterly", "Annual")
_WINDOW_DAYS = 30          # NSE does not truncate a month; stay at or under it

_UPDATE_SQL = """
UPDATE nidp.nse_financials_quarterly
   SET broadcast_at = $3
 WHERE symbol = $1 AND period_end = $2 AND broadcast_at IS NULL
"""


def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_broadcast(s: Any) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(str(s).strip(), fmt).replace(tzinfo=_IST)
        except ValueError:
            continue
    return None


def earliest_broadcasts(records: Iterable[dict]) -> dict[tuple[str, date], datetime]:
    """(symbol, period_end) -> earliest broadcast time, from raw listing records.

    Unlike parser.parse_filing_list this keeps filings without an XBRL link: the filing
    time is what matters here, not the numbers.
    """
    out: dict[tuple[str, date], datetime] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        symbol = (r.get("symbol") or "").strip().upper()
        period_end = _parse_date(r.get("toDate"))
        ts = _parse_broadcast(r.get("broadCastDate") or r.get("broadcastDate"))
        if not symbol or not period_end or not ts:
            continue
        key = (symbol, period_end)
        if key not in out or ts < out[key]:
            out[key] = ts
    return out


async def fetch_listing(from_date: date, to_date: date) -> list[dict]:
    """Every results filing broadcast in [from_date, to_date], both periods."""
    records: list[dict] = []
    for period in _PERIODS:
        start = from_date
        while start <= to_date:
            end = min(start + timedelta(days=_WINDOW_DAYS), to_date)
            url = (f"{_LISTING}?index=equities&period={period}"
                   f"&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}")
            text, status = await fetch_text(url, referer=_REFERER)
            if status != 200:
                raise RuntimeError(f"results listing HTTP {status} for {period} {start}..{end}")
            data = json.loads(text)
            rows = data if isinstance(data, list) else data.get("data", [])
            records.extend(rows)
            logger.info("stamp_broadcast: %s %s..%s -> %d filings", period, start, end, len(rows))
            start = end + timedelta(days=1)
    return records


async def run(from_date: date, to_date: date, dry_run: bool = False) -> dict:
    records = await fetch_listing(from_date, to_date)
    earliest = earliest_broadcasts(records)
    summary = {"filings": len(records), "periods": len(earliest), "rows_stamped": 0}
    if dry_run:
        logger.info("stamp_broadcast: dry run -- %s", summary)
        return summary
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for (symbol, period_end), ts in earliest.items():
                status = await conn.execute(_UPDATE_SQL, symbol, period_end, ts)
                summary["rows_stamped"] += int(status.split()[-1])
    logger.info("stamp_broadcast: done -- %s", summary)
    return summary


def main() -> None:
    setup_logging("stamp_broadcast_at")
    p = argparse.ArgumentParser(description="Stamp broadcast_at from NSE's results listing")
    p.add_argument("--from", dest="from_date", required=True, type=date.fromisoformat)
    p.add_argument("--to", dest="to_date", type=date.fromisoformat, default=date.today())
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    async def _go() -> None:
        try:
            await run(a.from_date, a.to_date, a.dry_run)
        finally:
            await close_fetcher()
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
