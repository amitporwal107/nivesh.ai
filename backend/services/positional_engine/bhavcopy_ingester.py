"""NSE Bhavcopy ingester (best-effort, optional).

Pulls the daily 'sec_bhavdata_full' file from NSE archives — a single CSV
with OHLC, volume, and DELIV_PER for every cash-segment symbol. This is
the cheapest authoritative source for the positional engine.

The fetcher is intentionally **best-effort**: if NSE blocks the request
(geofencing / TLS rotation / rate limits), it returns 0 written and logs
the error. Operators can fall back to manual CSV upload via the API.

**A file is never stamped with a date it does not carry.** NSE answers a
holiday URL with the previous session's file (verified 2026-10-27:
sec_bhavdata_full_02102026.csv holds DATE1 01-Oct-2026 on every row, and
..._20102026.csv holds 19-Oct-2026). Stamping the requested date made 14
holiday "sessions" that copied the day before. The parser now reads each
row's own DATE1 and refuses a file whose trade date is not the one asked
for, and `ingest` refuses a date the NSE calendar says is not a session.

We do NOT depend on any non-stdlib network library — uses urllib only.
"""
from __future__ import annotations

import csv
import io
import logging
import urllib.request
from datetime import date, datetime
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple

from . import ohlcv_store, session_calendar

logger = logging.getLogger(__name__)

# NSE archive URL pattern (public, ~13:00 IST daily).
BHAV_URL_FMT = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch(url: str, timeout: int = 30) -> Optional[str]:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        logger.warning("bhavcopy fetch failed for %s: %s", url, e)
        return None


class BhavcopyDateMismatch(ValueError):
    """The file's own trade date (DATE1) is not the date that was requested, or cannot be read."""

    def __init__(self, requested: date, found: Set[Optional[date]], detail: str = ""):
        self.requested = requested
        self.found = found
        shown = ", ".join(sorted(d.isoformat() if d else "unreadable" for d in found)) or "none"
        super().__init__(detail or f"file trade date {shown} != requested {requested.isoformat()}")


def _trade_date(raw: Optional[str]) -> Optional[date]:
    """DATE1 as NSE writes it (' 01-Oct-2026'); None when blank or unparseable."""
    try:
        return datetime.strptime((raw or "").strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def parse_bhavcopy_csv(blob: str, on_date: date) -> List[dict]:
    """Parse NSE sec_bhavdata_full CSV → list of bar dicts.

    The file ships EQ + BE + SM + ST series. We keep EQ and BE (regular
    and trade-to-trade); skip SM/ST (SME) and others.

    Raises BhavcopyDateMismatch unless every row's DATE1 is `on_date`: the
    bars carry the file's own trade date, never only the requested one.
    """
    reader = csv.DictReader(io.StringIO(blob))
    if "DATE1" not in {(f or "").strip() for f in (reader.fieldnames or [])}:
        raise BhavcopyDateMismatch(on_date, set(), "the file has no DATE1 (trade date) column")
    out: List[dict] = []
    file_dates: Set[Optional[date]] = set()
    for row in reader:
        # Column names in the bhavcopy have leading spaces
        clean = {(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        row_date = _trade_date(clean.get("DATE1"))
        file_dates.add(row_date)
        series = (clean.get("SERIES") or "").upper()
        if series not in ("EQ", "BE"):
            continue
        sym = clean.get("SYMBOL")
        if not sym:
            continue
        try:
            bar = {
                "nse_symbol": sym.upper(),
                "bar_date": row_date,          # the file's own trade date (checked == on_date below)
                "open":  float(clean["OPEN_PRICE"]),
                "high":  float(clean["HIGH_PRICE"]),
                "low":   float(clean["LOW_PRICE"]),
                "close": float(clean["CLOSE_PRICE"]),
                "volume": int(float(clean.get("TTL_TRD_QNTY") or 0)),
                "delivery_qty": (int(float(clean["DELIV_QTY"]))
                                  if (clean.get("DELIV_QTY") or "").replace(".", "").isdigit()
                                  else None),
                "delivery_pct": (float(clean["DELIV_PER"])
                                  if clean.get("DELIV_PER") not in (None, "", "-")
                                  else None),
                "source": "bhavcopy",
            }
        except (ValueError, KeyError) as e:
            logger.debug("skipping bhavcopy row %s: %s", sym, e)
            continue
        out.append(bar)
    if file_dates and file_dates != {on_date}:
        raise BhavcopyDateMismatch(on_date, file_dates)
    return out


SessionCheck = Callable[[date], Awaitable[Tuple[bool, str]]]


async def fetch_session(on_date: date, *, session_check: Optional[SessionCheck] = None,
                        fetch: Optional[Callable[[str], Optional[str]]] = None) -> Tuple[Dict, List[dict]]:
    """Fetch + parse the bhavcopy for `on_date` WITHOUT writing: (result, bars). result["status"] is "ok" when `bars`
    are that session's own EQ/BE bars; otherwise one of the refusals `ingest` documents, and `bars` is empty. The repair
    tool fetches every missing session this way before it opens its one transaction."""
    out: Dict = {"date": on_date.isoformat(), "rows_written": 0}
    check = session_check or session_calendar.check_session
    try:
        is_session, why = await check(on_date)
    except session_calendar.CalendarUnavailable as e:
        logger.warning("bhavcopy %s refused: session calendar unavailable (%s)", on_date, e)
        return {**out, "status": "calendar_unavailable", "reason": str(e)}, []
    if not is_session:
        logger.warning("bhavcopy %s refused: not an NSE session (%s)", on_date, why)
        return {**out, "status": "not_a_session", "reason": why}, []

    url = BHAV_URL_FMT.format(ddmmyyyy=on_date.strftime("%d%m%Y"))
    blob = (fetch or _fetch)(url)
    if not blob:
        return {**out, "status": "not_published", "reason": "NSE answered no file"}, []
    try:
        bars = parse_bhavcopy_csv(blob, on_date)
    except BhavcopyDateMismatch as e:
        logger.warning("bhavcopy %s refused, nothing written: %s", on_date, e)
        return {**out, "status": "date_mismatch", "reason": str(e),
                "file_dates": sorted(d.isoformat() for d in e.found if d)}, []
    if not bars:
        logger.warning("bhavcopy %s parsed 0 rows", on_date)
        return {**out, "status": "no_rows", "reason": "the file holds no EQ/BE rows"}, []
    return {**out, "status": "ok", "rows": len(bars)}, bars


async def ingest(on_date: date, *, session_check: Optional[SessionCheck] = None,
                 fetch: Optional[Callable[[str], Optional[str]]] = None) -> Dict:
    """Fetch + parse + persist the bhavcopy for `on_date`, refusing anything that is not that session's file.

    Returns {"date", "status", "rows_written", "reason"?, "file_dates"?}. status is one of:
      written               the file's trade date is `on_date`; its EQ/BE bars were upserted
      not_a_session         the NSE calendar says `on_date` is a weekend or holiday: NSE is not asked
      calendar_unavailable  the calendar could not be read or does not cover the date: NSE is not asked
      not_published         NSE did not answer with a file
      date_mismatch         the file carries another trade date (a holiday URL answered with the day before)
      no_rows               the file holds no EQ/BE rows
    Nothing is written unless the status is "written".
    """
    res, bars = await fetch_session(on_date, session_check=session_check, fetch=fetch)
    if res["status"] != "ok":
        return res
    n = await ohlcv_store.upsert_bars(bars)
    return {"date": res["date"], "rows_written": n, "status": "written"}


async def ingest_for_date(on_date: date) -> int:
    """Fetch + parse + persist bhavcopy for `on_date`. Returns rows written (0 when refused; see `ingest`)."""
    return (await ingest(on_date))["rows_written"]


async def backfill_missing(start: date, end: date) -> Dict:
    """Ingest every warehouse session in [start, end] that stock_ohlcv has no bars for, each through `ingest` (so a
    file is still refused unless it carries that session's trade date). Idempotent: once the sessions are in, a rerun
    finds nothing missing and fetches nothing."""
    out: Dict = {"window": [start.isoformat(), end.isoformat()]}
    try:
        sessions = await session_calendar.warehouse_sessions(start, end)
    except session_calendar.CalendarUnavailable as e:
        logger.warning("backfill %s..%s: warehouse sessions unavailable (%s): nothing ingested", start, end, e)
        return {**out, "ok": False, "error": "warehouse_sessions_unavailable", "reason": str(e)}
    have = await ohlcv_store.dates_between(start, end)
    if have is None:
        return {**out, "ok": False, "error": "no_pg_pool"}
    missing = sorted(sessions - have)
    results = [await ingest(d) for d in missing]
    if missing:
        logger.info("backfill %s..%s: %d missing session(s): %s", start, end, len(missing),
                    ", ".join(f"{r['date']}={r['status']}" for r in results))
    return {**out, "ok": all(r["status"] == "written" for r in results), "warehouse_sessions": len(sessions),
            "missing": [d.isoformat() for d in missing], "results": results}
