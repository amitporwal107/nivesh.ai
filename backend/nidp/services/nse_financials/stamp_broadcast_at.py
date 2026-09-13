"""Stamp nse_financials_quarterly.broadcast_at from NSE's financial-results listing.

broadcast_at -- when the market could first see a quarter's numbers -- was NULL on every
row, so no fundamental was usable point-in-time: a backtest that uses a quarter from its
period-end date trades on numbers that were not yet public. Two causes:
  * the parser read "broadcastDate"; NSE sends "broadCastDate" (fixed in parser.py);
  * the rows that exist were written by the Screener and Yahoo backfills, which carry no
    filing time at all.

Two NSE listings carry the broadcast timestamp, and which one depends on the date:
  * /api/corporates-financial-results -- the Reg-33 results listing. It dies with SEBI's
    move to Integrated Filing: 2,547 filings broadcast in Feb 2025, then 8 in May 2025.
  * /api/integrated-filing-results (type "Integrated Filing- Financials") -- carries every
    quarter since (3,477 filings in May 2025, 3,075 in Aug 2026).
Both filter on the BROADCAST date, so late filers land where they belong (AHLWEST filed its
March-2021 results on 30-Jun-2024). Revisions under Integrated Filing carry no
broadcast_Date -- only the original does -- so they are skipped, not misdated.

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
_INTEGRATED = f"{_NSE}/api/integrated-filing-results"
_INTEGRATED_REFERER = f"{_NSE}/companies-listing/corporate-integrated-filing"
_INTEGRATED_TYPE = "Integrated Filing- Financials"
_INTEGRATED_PAGE = 10000   # a peak month is ~3,300 filings; a short page raises, never truncates
# Integrated Filing took over during Q1 2025. The windows overlap on purpose: the earliest
# broadcast wins, so reading both listings for Jan-Mar 2025 cannot double-count or misdate.
_INTEGRATED_FROM = date(2025, 1, 1)
_LEGACY_UNTIL = date(2025, 3, 31)
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


def normalize_integrated(row: dict) -> Optional[dict]:
    """Map an Integrated Filing record onto the legacy listing's field names."""
    if not isinstance(row, dict) or (row.get("type") or "").strip() != _INTEGRATED_TYPE:
        return None
    return {
        "symbol": row.get("symbol"),
        "toDate": row.get("qe_Date"),              # '31-MAR-2025'; %b parses either case
        "broadCastDate": row.get("broadcast_Date"),  # None on revisions -> skipped
    }


def source_windows(from_date: date, to_date: date) -> list[tuple[str, date, date]]:
    """Which listing to read for which part of [from_date, to_date]."""
    out: list[tuple[str, date, date]] = []
    if from_date <= _LEGACY_UNTIL:
        out.append(("legacy", from_date, min(to_date, _LEGACY_UNTIL)))
    if to_date >= _INTEGRATED_FROM:
        out.append(("integrated", max(from_date, _INTEGRATED_FROM), to_date))
    return out


async def fetch_integrated(from_date: date, to_date: date) -> list[dict]:
    """Every Integrated Filing (Financials) broadcast in [from_date, to_date], normalized."""
    records: list[dict] = []
    start = from_date
    while start <= to_date:
        end = min(start + timedelta(days=_WINDOW_DAYS), to_date)
        url = (f"{_INTEGRATED}?index=equities&type={_INTEGRATED_TYPE.replace(' ', '%20')}"
               f"&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}&size={_INTEGRATED_PAGE}")
        text, status = await fetch_text(url, referer=_INTEGRATED_REFERER)
        if status != 200:
            raise RuntimeError(f"integrated listing HTTP {status} for {start}..{end}")
        data = json.loads(text)
        rows = (data.get("data") or []) if isinstance(data, dict) else []
        total = data.get("totalCount") if isinstance(data, dict) else None
        if total is not None and len(rows) < int(total):
            raise RuntimeError(
                f"integrated listing truncated for {start}..{end}: {len(rows)} of {total}")
        normalized = [n for n in (normalize_integrated(r) for r in rows) if n]
        records.extend(normalized)
        logger.info("stamp_broadcast: integrated %s..%s -> %d filings", start, end, len(normalized))
        start = end + timedelta(days=1)
    return records


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
    records: list[dict] = []
    for source, start, end in source_windows(from_date, to_date):
        fetch = fetch_listing if source == "legacy" else fetch_integrated
        records.extend(await fetch(start, end))
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
