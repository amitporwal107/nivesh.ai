"""Trade Desk › Chart Analysis › Live chart: market events as signals on the chart, with the stock's reaction. Read only.

    GET /api/desk/chart-events/{symbol}?from=YYYY-MM-DD&to=YYYY-MM-DD      (default: the last 90 days → 30 days ahead)

Contract C of test_reports/live_chart_comprehensive_TESTCASES.md. Each source is read from the data platform concurrently,
each with its own time limit; services/desk_chart_events.py turns the rows into events, merges them and works out each
event's reaction from the symbol's daily bars:

    events_calendar    DaaS /events/{symbol}          NSE event calendar: results and board meetings, AGMs
    corporate_actions  DaaS /corporate-actions        ex-dates of dividends, splits, bonuses, buybacks, rights, demergers
    filings            DaaS /announcements            exchange filings over the whole window (the Filings feed's articles
                                                      read stops at 30 days and turns a failed read into an empty list, so
                                                      it is not used here); 'regulatory' / 'other' rows left out as there
    macro              DaaS /desk/macro-calendar      India and US releases rated high impact, one call per month
    fno_expiry         DaaS /fno/{symbol}/expiries    the symbol's contract expiries (NIFTY's monthly ones without F&O)
    fii_dii            DaaS /market-pulse/fii-dii     daily FII / DII cash net; flow days by `fii_dii_rule`
    prices             DaaS /prices/adjusted/{symbol} daily bars for the reactions, plus today's Kite bar when it joins
                       (services/kite_live_feed/day_quote.extend_daily: live in the session, the saved Kite close after it)

A source that fails, times out or is not configured never fails the route: `sources[name]` says "unavailable: <why>" and
its events are absent. `notes` names anything partial (a page cap reached, a month without stored macro releases, the
holiday list unread). Signed-in users only. Nothing is written; nothing is sent to a broker.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, HTTPException, Path as PathParam, Query, Request

from deps import get_current_user
from services import desk_chart_events as ce
from services.copilot_tools import daas_client
from services.kite_live_feed import config as kite_cfg
from services.kite_live_feed import day_quote as dq

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/desk/chart-events", tags=["desk"])

SymbolPath = PathParam(..., pattern=r"^[A-Za-z0-9&\-]{1,32}$")
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
SOURCE_TIMEOUT = 15.0                 # seconds, per source
DAAS_TIMEOUT = 12.0                   # seconds, per DaaS call
BAR_WARMUP_DAYS = 45                  # calendar days of bars read before `from` (20 sessions for the volume average)
ACTION_MARGIN_DAYS = 10               # ex-date margin read around the window (a record date can trail its ex-date)
FILINGS_LIMIT = 2000
CALENDAR_LIMIT = 500
FLOW_DAYS = 365                       # calendar days of daily flows read (≈ 250 sessions)
MACRO_PARAMS = {"country": "IN,US", "impact": "H"}
MARKET_UNDERLYING = "NIFTY"
SOURCE_KEYS = ("events_calendar", "filings", "corporate_actions", "macro", "fno_expiry", "fii_dii")
OK = "ok"


class SourceUnavailable(Exception):
    """A source could not answer; `why` is shown to the reader (never an exception's own text)."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def _now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(kite_cfg.IST)


async def _daas(path: str, params: Dict[str, Any], key: str, *, empty_on_404: bool = False) -> Dict[str, Any]:
    """The data platform's 200 answer carrying `key`, else SourceUnavailable with the reason."""
    if not daas_client.is_configured():
        raise SourceUnavailable("the data platform is not configured")
    try:
        status, body = await daas_client.get_raw(path, params, timeout=DAAS_TIMEOUT)
    except daas_client.DaasError as e:
        logger.warning("chart events: DaaS %s failed (%s)", path, type(e).__name__)
        raise SourceUnavailable("the data platform did not answer")
    if status == 404 and empty_on_404:
        return {key: []}
    if status != 200:
        logger.warning("chart events: DaaS %s answered HTTP %s", path, status)
        raise SourceUnavailable(f"the data platform answered HTTP {status}")
    if not isinstance(body, dict) or not isinstance(body.get(key), list):
        raise SourceUnavailable("the data platform's answer had an unexpected shape")
    return body


# ── readers (one per source; each raises SourceUnavailable) ──────────────────

async def read_calendar(sym: str, lo: date, hi: date) -> List[Dict[str, Any]]:
    body = await _daas(f"/events/{sym}", {"from_date": lo.isoformat(), "limit": CALENDAR_LIMIT}, "data", empty_on_404=True)
    return body["data"]


async def read_actions(sym: str, lo: date, hi: date) -> List[Dict[str, Any]]:
    body = await _daas("/corporate-actions", {"symbol": sym, "ex_from": (lo - timedelta(days=ACTION_MARGIN_DAYS)).isoformat(),
                                              "ex_to": (hi + timedelta(days=ACTION_MARGIN_DAYS)).isoformat(), "limit": 500}, "data")
    return body["data"]


async def read_filings(sym: str, lo: date, hi: date) -> List[Dict[str, Any]]:
    # the warehouse filters on the UTC date: one day earlier keeps the IST morning of `lo`; the IST date is checked after
    body = await _daas("/announcements", {"symbol": sym, "filed_from": (lo - timedelta(days=1)).isoformat(),
                                          "filed_to": hi.isoformat(), "limit": FILINGS_LIMIT}, "data")
    return body["data"]


async def read_macro(lo: date, hi: date) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every month's releases (the month before `lo` too: a US evening release lands on the next IST day) and the months
    the data platform says have none stored."""
    ms = ce.months(lo - timedelta(days=1), hi)
    bodies = await asyncio.gather(*(_daas("/desk/macro-calendar", {"month": m, **MACRO_PARAMS}, "events") for m in ms))
    rows: List[Dict[str, Any]] = []
    empty: List[str] = []
    for m, b in zip(ms, bodies):
        rows += b["events"]
        if not b["events"] and any("no macro releases are stored" in str(g) for g in (b.get("gaps") or [])):
            empty.append(m)
    return rows, empty


async def read_expiries(sym: str) -> List[Dict[str, Any]]:
    body = await _daas(f"/fno/{sym}/expiries", {}, "data", empty_on_404=True)
    return body["data"]


async def read_flows() -> List[Dict[str, Any]]:
    body = await _daas("/market-pulse/fii-dii", {"days": FLOW_DAYS}, "daily")
    return body["daily"]


async def read_bars(sym: str, start: date, now: datetime) -> Tuple[List[list], Optional[str]]:
    """Adjusted daily bars from `start`, oldest first, with today's Kite bar appended when it joins; and that bar's day."""
    from routes.research_chart_live import _bar
    body = await _daas(f"/prices/adjusted/{sym}", {"limit": 1000, "start": start.isoformat()}, "data", empty_on_404=True)
    bars = sorted((b for b in (_bar(r) for r in body["data"]) if b is not None), key=lambda b: b[0])
    if not bars:
        raise SourceUnavailable(f"no daily bars are stored for {sym}")
    bars, today = await dq.extend_daily(bars, sym, now=now)
    return bars, (today.get("day") if today.get("used") else None)


async def read_holidays(start: date, end: date) -> Tuple[Optional[Set[date]], bool]:
    from routes.desk_live_chart import read_holidays as _read
    return await _read(start, end)


async def _guarded(aw: Awaitable[Any]) -> Tuple[Any, Optional[str]]:
    """(result, None) or (None, why): a source's failure stays inside its own slot."""
    try:
        return await asyncio.wait_for(aw, timeout=SOURCE_TIMEOUT), None
    except SourceUnavailable as e:
        return None, e.why
    except asyncio.TimeoutError:
        return None, f"no answer within {SOURCE_TIMEOUT:g} s"
    except Exception as e:  # noqa: BLE001 — one source's bug must not take the chart's other events down
        logger.warning("chart events: source failed (%s)", type(e).__name__)
        return None, "the source could not be read"


@router.get("/{symbol}")
async def chart_events(request: Request, symbol: str = SymbolPath,
                       from_: Optional[str] = Query(None, alias="from", pattern=DATE_PATTERN, description="YYYY-MM-DD"),
                       to: Optional[str] = Query(None, pattern=DATE_PATTERN, description="YYYY-MM-DD")) -> Dict[str, Any]:
    await get_current_user(request)
    sym = symbol.upper()
    now = _now_ist()
    try:
        lo, hi = ce.window(from_, to, now.date())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    bars_from = lo - timedelta(days=ce.AVG_SESSIONS + BAR_WARMUP_DAYS)

    (cal, cal_err), (acts, acts_err), (fil, fil_err), (mac, mac_err), (exp, exp_err), (flows, flows_err), \
        (bars, bars_err), (hol, hol_err) = await asyncio.gather(
            _guarded(read_calendar(sym, lo, hi)), _guarded(read_actions(sym, lo, hi)), _guarded(read_filings(sym, lo, hi)),
            _guarded(read_macro(lo, hi)), _guarded(read_expiries(sym)), _guarded(read_flows()),
            _guarded(read_bars(sym, bars_from, now)), _guarded(read_holidays(bars_from, hi)))

    sources: Dict[str, str] = {}
    notes: List[str] = []
    events: List[Dict[str, Any]] = []

    def done(key: str, err: Optional[str]) -> bool:
        sources[key] = OK if err is None else f"unavailable: {err}"
        return err is None

    if done("events_calendar", cal_err):
        events += ce.from_calendar(cal, lo, hi)
    if done("corporate_actions", acts_err):
        events += ce.from_actions(acts, lo, hi)
    if done("filings", fil_err):
        events += ce.from_filings(fil, lo, hi)
        if len(fil) >= FILINGS_LIMIT:
            notes.append(f"filings: the first {FILINGS_LIMIT} of the window are shown (newest first); older ones are not")
    if done("macro", mac_err):
        rows, empty = mac
        events += ce.from_macro(rows, lo, hi)
        if empty:
            notes.append("macro: no releases are stored for " + ", ".join(empty) + " (the macro ingester has not loaded them)")
    if exp_err is None and not exp:
        # no F&O contracts of its own: the market's monthly expiry days (NIFTY), read the same way
        nifty, exp_err = await _guarded(read_expiries(MARKET_UNDERLYING))
        if exp_err is None:
            events += ce.from_expiries(nifty, lo, hi, MARKET_UNDERLYING, monthly_only=True, chart_symbol=sym)
            notes.append(f"fno_expiry: {sym} has no F&O contracts; {MARKET_UNDERLYING}'s monthly expiries are shown")
    elif exp_err is None:
        events += ce.from_expiries(exp, lo, hi, sym)
    done("fno_expiry", exp_err)
    rule = ce.flow_rule_text()
    if flows_err is None:
        flow_events, rule, flows_err = ce.flow_days(flows, lo, hi)
        events += flow_events
    done("fii_dii", flows_err)

    merged = ce.merge(events)
    holidays = hol[0] if hol_err is None and hol and hol[1] else None
    if bars_err is None:
        bar_rows, kite_day = bars
        if holidays is None:
            notes.append("prices: the NSE holiday list could not be read, so an event on a weekday without a bar has no reaction")
        ce.attach_reactions(merged, bar_rows, kite_day=kite_day, holidays=holidays)
    sources["prices"] = OK if bars_err is None else f"unavailable: {bars_err}"

    return {"symbol": sym, "from": lo.isoformat(), "to": hi.isoformat(), "as_of": now.isoformat(), "events": merged,
            "sources": {k: sources[k] for k in (*SOURCE_KEYS, "prices")}, "fii_dii_rule": rule, "notes": notes,
            "read_only": True}
