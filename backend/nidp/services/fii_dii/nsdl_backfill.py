"""Backfill nidp.fii_dii_flows from NSDL's FPI archive.

Why:
    The NSE-sourced series has holes — 14 of 47 trading days were missing
    between 2026-05-25 and 2026-08-17 because NSE's Akamai edge 403s this
    egress IP intermittently. NSDL publishes the same institutional-flow
    picture from the custodian side and keeps an archive, so the holes can
    be closed retrospectively.

How:
    `Archive.aspx` is ASP.NET WebForms: GET once to harvest __VIEWSTATE /
    __EVENTVALIDATION, then POST with __EVENTTARGET=btnSubmit1 and the
    date in `hdnDate` (`txtDate` is disabled in the DOM and is not posted
    on its own). One response covers a short window ending on the
    requested date — usually ~3 reporting days — so walking backwards in
    strides covers a range in few requests.

    Date format matters: "05-08-2026" is read as 08-May-2026. Use ISO or
    dd-MMM-yyyy.

Usage:
    python -m nidp.services.fii_dii.nsdl_backfill --from 2026-05-25 --to 2026-08-17
"""
from __future__ import annotations

import argparse
import asyncio
import html
import logging
import re
import urllib.parse
import uuid
from datetime import date, datetime, timedelta

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S
from nidp.shared.storage.pg import get_pool

from .nsdl_parser import parse_nsdl_fpi
from .writer import upsert_fii_dii

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
NSDL_FPI_SOURCE = "NSDL_FPI"
_STRIDE_DAYS = 3          # one response covers ~3 reporting days


def _hidden(page: str, name: str) -> str:
    m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), page)
    return html.unescape(m.group(1)) if m else ""


async def fetch_archive(session: aiohttp.ClientSession, target: date) -> bytes:
    """Run the two-step postback and return the result HTML."""
    headers = {"User-Agent": DEFAULT_UA, "Referer": ARCHIVE_URL}
    async with session.get(ARCHIVE_URL, headers=headers) as r:
        page = (await r.read()).decode("utf-8", "replace")

    form = {
        "__EVENTTARGET": "btnSubmit1",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": _hidden(page, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _hidden(page, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _hidden(page, "__EVENTVALIDATION"),
        # dd-MMM-yyyy — an all-numeric dd-mm-yyyy is misparsed as mm-dd
        "txtDate": target.strftime("%d-%b-%Y"),
        "hdnDate": target.strftime("%d-%b-%Y"),
        "hdnFlag": "",
        "HdnValexceldata": "",
    }
    post_headers = dict(headers)
    post_headers["Content-Type"] = "application/x-www-form-urlencoded"
    async with session.post(ARCHIVE_URL,
                            data=urllib.parse.urlencode(form),
                            headers=post_headers) as r:
        return await r.read()


async def missing_days(frm: date, to: date) -> list[date]:
    """Trading days in range that prices_eod has but fii_dii_flows lacks."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT p.as_of_date AS d
              FROM nidp.prices_eod p
             WHERE p.as_of_date BETWEEN $1 AND $2
               AND NOT EXISTS (SELECT 1 FROM nidp.fii_dii_flows f
                                WHERE f.as_of_date = p.as_of_date
                                  AND f.segment = 'EQUITY_CASH')
             ORDER BY 1
            """,
            frm, to,
        )
    return [r["d"] for r in rows]


async def backfill(frm: date, to: date) -> int:
    gaps = await missing_days(frm, to)
    if not gaps:
        logger.info("fii_dii backfill: no gaps between %s and %s", frm, to)
        return 0
    logger.info("fii_dii backfill: %d missing day(s): %s",
                len(gaps), ", ".join(str(d) for d in gaps))

    wanted = set(gaps)
    collected: dict[date, list[dict]] = {}
    run_id = uuid.uuid4()
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Walk backwards in strides; each response covers a short window,
        # so anchoring on the newest outstanding gap converges quickly.
        cursor = max(gaps)
        seen_anchors: set[date] = set()
        while wanted and cursor >= frm and cursor not in seen_anchors:
            seen_anchors.add(cursor)
            try:
                body = await fetch_archive(session, cursor)
            except Exception:  # noqa: BLE001
                logger.exception("fii_dii backfill: fetch failed for %s", cursor)
                cursor -= timedelta(days=_STRIDE_DAYS)
                continue
            for row in parse_nsdl_fpi(body):
                d = datetime.strptime(row["as_of_date"], "%Y-%m-%d").date()
                if d in wanted:
                    collected.setdefault(d, []).append(
                        {**row, "source": NSDL_FPI_SOURCE})
            wanted = {d for d in wanted if d not in collected}
            if wanted:
                cursor = max(d for d in wanted)
            await asyncio.sleep(1.0)          # be polite to NSDL

    rows = [r for day in sorted(collected) for r in collected[day]]
    if not rows:
        logger.warning("fii_dii backfill: archive returned nothing usable")
        return 0
    written = await upsert_fii_dii(rows, run_id, source=NSDL_FPI_SOURCE)
    logger.info("fii_dii backfill: wrote %d row(s) covering %d day(s); "
                "still missing: %s", written, len(collected),
                ", ".join(str(d) for d in sorted(wanted)) or "none")
    return written


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", required=True, type=_d)
    ap.add_argument("--to", dest="to", required=True, type=_d)
    args = ap.parse_args()
    asyncio.run(backfill(args.frm, args.to))
