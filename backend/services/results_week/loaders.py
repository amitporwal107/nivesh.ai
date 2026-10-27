"""Results week — data loaders. Reads only.

Each loader is failure-isolated: a source that fails returns no data and a gap (a sentence naming what is missing and
why); the caller nulls that block and the rest of the answer still stands (TC-B13). Only the results calendar
(DaaS expectations) is essential: with every window failing there is nothing to show, and the caller says so.

DaaS load: per-symbol reads run with bounded concurrency (DAAS_CONCURRENCY) and are cached (TTL per source) so the
live route's rebuild every few minutes does not refetch eight quarters for 500 stocks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
WINDOW_DAYS = 3                 # DaaS /desk/events-calendar/expectations answers at most 3 days per call
DAAS_CONCURRENCY = 6
EXPECTATIONS_TIMEOUT_S = 60.0
NIFTY = "Nifty 50"
BUILDUP_FALLBACK_DAYS = 5       # live view: the newest build-up day with rows, at most this many weekdays back
TECH_MAX_AGE_DAYS = 7
FIN_QUARTERS = 8
TTL_S = {"financials": 1800.0, "history": 6 * 3600.0, "buildup": 600.0, "nifty": 600.0}
ANALYSIS_COLLECTION = "event_ai_analysis"
ISOLATED = "tools_off+isolated"

_cache: Dict[Tuple, Tuple[float, Any]] = {}


class SourceUnavailable(RuntimeError):
    """The results calendar could not be read at all: there is nothing to answer with."""


def clear_cache() -> None:
    _cache.clear()


async def _cached(kind: str, key: Tuple, fetch: Callable[[], Awaitable[Any]]) -> Any:
    k = (kind, *key)
    hit = _cache.get(k)
    if hit and time.monotonic() - hit[0] < TTL_S[kind]:
        return hit[1]
    val = await fetch()
    _cache[k] = (time.monotonic(), val)
    return val


def _why(e: BaseException) -> str:
    if isinstance(e, daas_client.DaasError):
        return f"HTTP {e.status_code}" if e.status_code else "unreachable"
    return type(e).__name__


# ── windows and sessions ──────────────────────────────────────────────────────────────────────────────────────────

def week_of(day: date) -> Tuple[date, date]:
    """Monday .. Saturday of the date's week."""
    mon = day - timedelta(days=day.weekday())
    return mon, mon + timedelta(days=5)


def windows(start: date, end: date) -> List[Tuple[date, date]]:
    out, d = [], start
    while d <= end:
        hi = min(d + timedelta(days=WINDOW_DAYS - 1), end)
        out.append((d, hi))
        d = hi + timedelta(days=1)
    return out


async def sessions(start: date, end: date) -> Tuple[List[date], Optional[str]]:
    """NSE cash-market sessions in [start, end] from the holiday list (services/positional_engine/session_calendar).
    The list failing → weekdays, with a gap (a holiday may then be counted as a session)."""
    from services.positional_engine import session_calendar as cal

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    try:
        hol: Dict[date, str] = {}
        for y in sorted({d.year for d in days}):
            hol.update(await cal.holidays_for_year(y))
        return [d for d in days if cal.classify(d, hol)[0]], None
    except Exception as e:  # noqa: BLE001 — CalendarUnavailable or anything under it
        logger.warning("results week: NSE holiday list unavailable (%s)", type(e).__name__)
        return [d for d in days if d.weekday() < 5], "NSE holiday list unavailable: every weekday is taken as a session"


# ── DaaS ──────────────────────────────────────────────────────────────────────────────────────────────────────────

async def expectations(wins: Sequence[Tuple[date, date]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[str]]:
    """(events, per-window meta, the first answer's label/method/sources/gaps, gaps). Raises SourceUnavailable when
    every window failed."""
    async def one(lo: date, hi: date):
        try:
            st, body = await daas_client.get_raw("/desk/events-calendar/expectations",
                                                 {"from": lo.isoformat(), "to": hi.isoformat(), "universe": "all"},
                                                 timeout=EXPECTATIONS_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            return lo, hi, None, _why(e)
        if st == 200 and isinstance(body, dict) and isinstance(body.get("events"), list):
            return lo, hi, body, None
        return lo, hi, None, f"HTTP {st}"

    answers = await asyncio.gather(*(one(lo, hi) for lo, hi in wins))
    events: List[Dict[str, Any]] = []
    meta: List[Dict[str, Any]] = []
    gaps: List[str] = []
    first: Dict[str, Any] = {}
    for lo, hi, body, err in answers:
        m = {"from": lo.isoformat(), "to": hi.isoformat(), "ok": body is not None}
        if body is None:
            m["error"] = err
            gaps.append(f"results calendar {lo.isoformat()} to {hi.isoformat()} could not be read (DaaS {err}): its meetings are missing")
        else:
            m.update(as_of=body.get("as_of"), counts=body.get("counts"), count=body.get("count"))
            events.extend(e for e in body["events"] if isinstance(e, dict) and e.get("symbol"))
            if not first:
                first = {k: body.get(k) for k in ("label", "method", "sources", "gaps")}
        meta.append(m)
    if not any(m["ok"] for m in meta):
        raise SourceUnavailable("; ".join(gaps) or "no window")
    return events, meta, first, gaps


async def quarterly(symbols: Dict[str, bool]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str], Optional[str]]:
    """{symbol: newest-first quarterly rows} on the basis each result is reported on (True = consolidated).
    (rows, per-symbol gaps, source gap when every read failed)."""
    gate = asyncio.Semaphore(DAAS_CONCURRENCY)
    out: Dict[str, List[Dict[str, Any]]] = {}
    gaps: Dict[str, str] = {}

    async def one(sym: str, cons: bool):
        async with gate:
            try:
                out[sym] = await _cached("financials", (sym, cons),
                                         lambda: daas_client.get_quarterly_financials(sym, limit=FIN_QUARTERS, consolidated=cons))
            except Exception as e:  # noqa: BLE001
                gaps[sym] = f"quarterly results could not be read (DaaS {_why(e)})"

    await asyncio.gather(*(one(s, c) for s, c in symbols.items()))
    src = "quarterly results could not be read for any stock" if symbols and len(gaps) == len(symbols) else None
    return out, gaps, src


async def history(symbols: Iterable[str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], Optional[str]]:
    """{symbol: DaaS /desk/events-calendar/history body for RESULTS}."""
    syms = list(dict.fromkeys(symbols))
    gate = asyncio.Semaphore(DAAS_CONCURRENCY)
    out: Dict[str, Dict[str, Any]] = {}
    gaps: Dict[str, str] = {}

    async def fetch(sym: str):
        st, body = await daas_client.get_raw("/desk/events-calendar/history", {"symbol": sym, "type": "RESULTS"})
        if st == 200 and isinstance(body, dict):
            return body
        if st == 404:
            return {"occurrences": [], "n": 0}
        raise daas_client.DaasError(f"history HTTP {st}", status_code=st)

    async def one(sym: str):
        async with gate:
            try:
                out[sym] = await _cached("history", (sym,), lambda: fetch(sym))
            except Exception as e:  # noqa: BLE001
                gaps[sym] = f"past results reactions could not be read (DaaS {_why(e)})"

    await asyncio.gather(*(one(s) for s in syms))
    src = "past results reactions could not be read for any stock" if syms and len(gaps) == len(syms) else None
    return out, gaps, src


async def buildup(day: date, *, fallback: bool) -> Tuple[Dict[str, Dict[str, Any]], Optional[str], Optional[str]]:
    """({symbol: build-up row}, the day the rows are for, gap). With `fallback` (the live view) a date whose F&O
    bhavcopy is not loaded yet shows the newest earlier day with rows, labelled; without it (the nightly snapshot) only
    the date itself counts."""
    async def fetch(d: date):
        st, body = await daas_client.get_raw("/desk/fno-buildup", {"date": d.isoformat()}, timeout=30.0)
        if st == 200 and isinstance(body, dict) and isinstance(body.get("rows"), list):
            return body
        raise daas_client.DaasError(f"fno-buildup HTTP {st}", status_code=st)

    tries = [day]
    if fallback:
        d = day
        while len(tries) <= BUILDUP_FALLBACK_DAYS:
            d -= timedelta(days=1)
            if d.weekday() < 5:
                tries.append(d)
    for d in tries:
        try:
            body = await _cached("buildup", (d.isoformat(),), lambda: fetch(d))
        except Exception as e:  # noqa: BLE001
            return {}, None, f"OI build-up could not be read (DaaS {_why(e)})"
        rows = [r for r in body["rows"] if isinstance(r, dict) and r.get("symbol")]
        if rows and str(body.get("as_of") or "")[:10] == d.isoformat():
            gap = None if d == day else f"OI build-up for {day.isoformat()} is not loaded yet (the F&O bhavcopy lands ~22:15 IST): showing {d.isoformat()}"
            return {str(r["symbol"]).upper(): r for r in rows}, d.isoformat(), gap
    return {}, None, f"OI build-up for {day.isoformat()} is not loaded yet (the F&O bhavcopy lands ~22:15 IST)"


async def nifty(start: date, end: date) -> Tuple[Dict[date, float], Optional[str]]:
    async def fetch():
        return await daas_client.get_index_eod_history(NIFTY, start=start.isoformat(), end=end.isoformat())
    try:
        rows = await _cached("nifty", (start.isoformat(), end.isoformat()), fetch)
    except Exception as e:  # noqa: BLE001
        return {}, f"Nifty 50 closes could not be read ({_why(e)})"
    out: Dict[date, float] = {}
    for r in rows or []:
        try:
            c = float(r.get("close_price"))
            out[date.fromisoformat(str(r.get("as_of_date"))[:10])] = c
        except (TypeError, ValueError):
            continue
    if not out:
        _cache.pop(("nifty", start.isoformat(), end.isoformat()), None)
        return {}, "Nifty 50 closes could not be read (DaaS index EOD answered none)"
    return out, None


# ── Mongo: the filing analysis ────────────────────────────────────────────────────────────────────────────────────

def _is_analysis(d: Dict[str, Any]) -> bool:
    m = d.get("mode") or ""
    return m == "single_full" or m.endswith("_compact")


async def filing_analysis(db, symbols: Iterable[str], start: datetime, end: datetime) -> Tuple[Dict[str, List[Dict[str, Any]]], Optional[str]]:
    """{symbol: [RESULTS analyses (single_full or *_compact, tools off and isolated) with event_ts in [start, end)]}.
    (data, gap). A failed read is a gap, never "not analysed"."""
    syms = list(dict.fromkeys(symbols))
    if not syms:
        return {}, None
    q = {"event_type": "RESULTS", "symbol": {"$in": syms}, "tool_isolation": ISOLATED,
         "event_ts": {"$gte": start.astimezone(timezone.utc).replace(tzinfo=None), "$lt": end.astimezone(timezone.utc).replace(tzinfo=None)}}
    proj = {"_id": 0, "symbol": 1, "announcement_id": 1, "mode": 1, "event_ts": 1, "analyzed_at": 1, "net_impact_score": 1,
            "net_band": 1, "confidence_score": 1, "materiality_score": 1, "analysis.sum": 1, "exchange_category": 1,
            "event_subtype": 1}
    try:
        docs = await db[ANALYSIS_COLLECTION].find(q, proj).to_list(length=20 * len(syms))
    except Exception as e:  # noqa: BLE001
        logger.warning("results week: event_ai_analysis read failed (%s)", type(e).__name__)
        return {}, f"filing analysis (Mongo {ANALYSIS_COLLECTION}) could not be read ({type(e).__name__})"
    out: Dict[str, List[Dict[str, Any]]] = {}
    for d in docs:
        if _is_analysis(d):
            out.setdefault(str(d.get("symbol") or "").upper(), []).append(d)
    return out, None


# ── app Postgres: prices and the AI scanner's technicals ──────────────────────────────────────────────────────────

async def prices(symbols: Iterable[str], start: date, end: date) -> Tuple[Dict[str, Dict[date, Tuple[Optional[float], Optional[float]]]], Optional[str]]:
    """{symbol: {bar_date: (close, volume)}} from stock_ohlcv."""
    from services import pg_client

    syms = list(dict.fromkeys(symbols))
    if not syms:
        return {}, None
    try:
        pool = await pg_client.get_pool()
        if pool is None:
            return {}, "stock prices (stock_ohlcv) could not be read: no database pool"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT nse_symbol, bar_date, close_price, volume FROM stock_ohlcv "
                "WHERE nse_symbol = ANY($1::text[]) AND bar_date >= $2 AND bar_date <= $3", syms, start, end)
    except Exception as e:  # noqa: BLE001
        logger.warning("results week: stock_ohlcv read failed (%s)", type(e).__name__)
        return {}, f"stock prices (stock_ohlcv) could not be read ({type(e).__name__})"
    out: Dict[str, Dict[date, Tuple[Optional[float], Optional[float]]]] = {}
    for r in rows:
        c, v = r["close_price"], r["volume"]
        out.setdefault(r["nse_symbol"], {})[r["bar_date"]] = (float(c) if c is not None else None, float(v) if v is not None else None)
    return out, None


async def prices_loaded(day: date) -> Optional[bool]:
    """Does stock_ohlcv hold the date's session? None when it cannot be read."""
    from services import pg_client
    try:
        pool = await pg_client.get_pool()
        if pool is None:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS n FROM stock_ohlcv WHERE bar_date = $1", day)
    except Exception:  # noqa: BLE001
        return None
    return bool(row and row["n"])


async def technicals(symbols: Iterable[str], day: date) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """{symbol: the AI scanner's latest stock_technical_features row on or before the date (within a week)}."""
    from services import pg_client

    syms = list(dict.fromkeys(symbols))
    if not syms:
        return {}, None
    try:
        pool = await pg_client.get_pool()
        if pool is None:
            return {}, "AI scanner technicals could not be read: no database pool"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ON (nse_symbol) nse_symbol, as_of_date, stage, final_score, confidence "
                "FROM stock_technical_features WHERE nse_symbol = ANY($1::text[]) AND as_of_date <= $2 AND as_of_date > $3 "
                "ORDER BY nse_symbol, as_of_date DESC", syms, day, day - timedelta(days=TECH_MAX_AGE_DAYS))
    except Exception as e:  # noqa: BLE001
        logger.warning("results week: stock_technical_features read failed (%s)", type(e).__name__)
        return {}, f"AI scanner technicals (stock_technical_features) could not be read ({type(e).__name__})"
    return {r["nse_symbol"]: dict(r) for r in rows}, None


# ── Mongo: the signed-in user's Chartink hits (the desk's Chartink section) ───────────────────────────────────────

async def chartink_for(db, user_id: str, day: date) -> Tuple[Optional[Dict[str, List[str]]], Dict[str, Any]]:
    """({symbol: [scan names]} for the user's hits stored on the date, or None when there are none to show; meta).
    Reads the desk's own store (services/chartink_desk); never fetches from Chartink."""
    from services.chartink_desk import hits as hits_mod
    from services.chartink_desk import store as ck_store

    meta: Dict[str, Any] = {"source": "your Chartink dashboard (desk Chartink section): confirmation only, never scored",
                            "connected": None, "scan_date": None, "symbols": 0, "note": None}
    try:
        src = await ck_store.get_source(db, user_id)
        if src is None:
            meta.update(connected=False, note="No Chartink dashboard is connected.")
            return None, meta
        sd, docs = await hits_mod.latest_hits(db, user_id, day.isoformat())
    except Exception as e:  # noqa: BLE001
        logger.warning("results week: chartink hits read failed (%s)", type(e).__name__)
        meta["note"] = f"Chartink hits could not be read ({type(e).__name__})"
        meta["failed"] = True
        return None, meta
    meta["connected"] = True
    if not docs:
        meta["note"] = f"No Chartink hits are stored for {day.isoformat()} (the scans were not refreshed that day)."
        return None, meta
    by = hits_mod.group(docs, src.get("scans") or [])
    fetched = [d.get("fetched_at") for d in docs if d.get("fetched_at")]
    meta.update(scan_date=sd, symbols=len(by), fetched_at=max(fetched) if fetched else None,
                mode="end_of_day_snapshot" if fetched and hits_mod.is_eod(sd, min(fetched)) else "fetched_at")
    return {sym: [s["name"] for s in e["scans"]] for sym, e in by.items()}, meta
