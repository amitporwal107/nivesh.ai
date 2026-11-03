"""Results week — data loaders. Reads only.

Each loader is failure-isolated: a source that fails returns no data and a gap (a sentence naming what is missing and
why); the caller nulls that block and the rest of the answer still stands (TC-B13). Only the results calendar
(DaaS expectations) is essential: with every window failing there is nothing to show, and the caller says so.

DaaS load: a build reads ~1,800 small DaaS answers (quarters, past reactions, futures and options per F&O stock).
daas_client opens a new connection (TLS through the public edge) per call: measured on staging 27 Oct, 60 reads took
6.7 s that way and 1.0 s over one keep-alive client. So a build runs inside `pooled()`, which gives every read here
(`daas_get`) one shared keep-alive client, with daas_client's own credentials and DaasError; outside it `daas_get` is
daas_client.get_raw. Reads run with bounded concurrency (DAAS_CONCURRENCY) and are cached (TTL per source), so the live
route's rebuild every few minutes does not refetch eight quarters for 500 stocks.
"""
from __future__ import annotations

import asyncio
import re
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
WINDOW_DAYS = 3                 # DaaS /desk/events-calendar/expectations answers at most 3 days per call
DAAS_CONCURRENCY = 8
EXPECTATIONS_TIMEOUT_S = 60.0
NIFTY = "Nifty 50"
BUILDUP_FALLBACK_DAYS = 5       # live view: the newest build-up day with rows, at most this many weekdays back
TECH_MAX_AGE_DAYS = 7
FIN_QUARTERS = 8
TTL_S = {"financials": 1800.0, "history": 6 * 3600.0, "buildup": 600.0, "nifty": 600.0,
         "fno_day": 600.0, "fno_past": 12 * 3600.0, "expiries": 6 * 3600.0}
FNO_PAGE = 1000                 # one expiry's option strikes for a stock fit in one page (MANKIND Nov: 92 rows)
ANALYSIS_COLLECTION = "event_ai_analysis"
ISOLATED = "tools_off+isolated"
RESULTS_TYPE = "RESULT"         # case-insensitive match on event_type

_cache: Dict[Tuple, Tuple[float, Any]] = {}


_POOL: ContextVar[Optional[httpx.AsyncClient]] = ContextVar("results_week_daas_pool", default=None)


@asynccontextmanager
async def pooled() -> AsyncIterator[None]:
    """One keep-alive DaaS client for every read made inside the block (one build)."""
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=DAAS_CONCURRENCY,
                                                     max_keepalive_connections=DAAS_CONCURRENCY)) as client:
        token = _POOL.set(client)
        try:
            yield
        finally:
            _POOL.reset(token)


RATE_LIMIT_RETRIES = 3                # a 429 from DaaS is retried after 1, 2 and 4 seconds (staging 28 Oct: the desk's
RATE_LIMIT_BACKOFF_S = 1.0            # ideas engine and a results-week build together hit the DaaS rate limit)


async def daas_get(path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 20.0) -> Tuple[int, Any]:
    """(HTTP status, parsed JSON or None) like daas_client.get_raw; over the build's pooled client when there is one.
    A 429 (rate limited) is retried with back-off before it is returned. Connectivity failures raise DaasError."""
    st, body = await _daas_get_once(path, params, timeout)
    for i in range(RATE_LIMIT_RETRIES):
        if st != 429:
            break
        await asyncio.sleep(RATE_LIMIT_BACKOFF_S * (2 ** i))
        st, body = await _daas_get_once(path, params, timeout)
    return st, body


async def _daas_get_once(path: str, params: Optional[Dict[str, Any]], timeout: float) -> Tuple[int, Any]:
    client = _POOL.get()
    if client is None:
        return await daas_client.get_raw(path, params, timeout=timeout)
    base, key = daas_client._creds()
    try:
        resp = await client.get(f"{base}/v1{path}", params=params, timeout=timeout,
                                headers={"X-API-Key": key, "Accept": "application/json"})
    except httpx.TimeoutException:
        raise daas_client.DaasError(f"DAAS request timed out after {timeout}s: {path}")
    except httpx.HTTPError as exc:
        raise daas_client.DaasError(f"DAAS connectivity error on {path}: {exc}")
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body


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
            st, body = await daas_get("/desk/events-calendar/expectations",
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

    async def fetch(sym: str, cons: bool):
        # the same read as daas_client.get_quarterly_financials (period_type quarterly: no fiscal-year rows)
        st, body = await daas_get(f"/financials/{sym}", {"limit": FIN_QUARTERS, "consolidated": str(cons).lower(),
                                                         "period_type": "quarterly"})
        if st == 404:
            return []
        if st != 200 or not isinstance(body, dict):
            raise daas_client.DaasError(f"/financials/{sym} HTTP {st}", status_code=st)
        rows = body.get("data") or body.get("rows") or []
        return rows if isinstance(rows, list) else []

    async def one(sym: str, cons: bool):
        async with gate:
            try:
                out[sym] = await _cached("financials", (sym, cons), lambda: fetch(sym, cons))
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
        st, body = await daas_get("/desk/events-calendar/history", {"symbol": sym, "type": "RESULTS"})
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
        st, body = await daas_get("/desk/fno-buildup", {"date": d.isoformat()}, timeout=30.0)
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


async def fno_contracts(sym: str, on: date, kind: str, expiry: Optional[str] = None, *, past: bool = False) -> List[Dict[str, Any]]:
    """One day's contracts of one underlying from DaaS /fno/{symbol} (kind STF futures | STO options). Raises on failure.
    A past day never changes, so it is cached longer."""
    params: Dict[str, Any] = {"on": on.isoformat(), "instrument_type": kind, "limit": FNO_PAGE}
    if expiry:
        params["expiry"] = expiry

    async def fetch():
        st, body = await daas_get(f"/fno/{sym}", params, timeout=20.0)
        if st == 200 and isinstance(body, dict) and isinstance(body.get("data"), list):
            if str(body.get("as_of") or "")[:10] not in ("", on.isoformat()):
                return []                       # the platform answered another day: nothing for this one
            return [r for r in body["data"] if isinstance(r, dict)]
        if st == 404:
            return []
        raise daas_client.DaasError(f"/fno/{sym} HTTP {st}", status_code=st)

    return await _cached("fno_past" if past else "fno_day", (sym, on.isoformat(), kind, expiry or ""), fetch)


async def fno_expiries(sym: str) -> List[date]:
    """Every expiry the warehouse holds for the underlying (DaaS /fno/{symbol}/expiries), ascending. Read, never computed."""
    async def fetch():
        st, body = await daas_get(f"/fno/{sym}/expiries", {}, timeout=20.0)
        if st == 200 and isinstance(body, dict) and isinstance(body.get("data"), list):
            out = []
            for r in body["data"]:
                try:
                    out.append(date.fromisoformat(str(r.get("expiry_date"))[:10]))
                except ValueError:
                    continue
            return sorted(set(out))
        raise daas_client.DaasError(f"/fno/{sym}/expiries HTTP {st}", status_code=st)
    return await _cached("expiries", (sym,), fetch)


async def fno_deep(symbols: Iterable[str], day: date, sessions: Sequence[date]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Per F&O underlying on `day`: the futures of every expiry, the options of the expiry scoring.options_expiry picks,
    and — inside the rollover window — the futures on the same number of sessions before each of its last 5 expiries.
    ({symbol: {futures, options, options_exp, past}}, per-symbol gaps). Reads are bounded (DAAS_CONCURRENCY) and cached."""
    from . import scoring as sc

    gate = asyncio.Semaphore(DAAS_CONCURRENCY)
    ss = sorted(sessions)
    out: Dict[str, Dict[str, Any]] = {}
    gaps: Dict[str, str] = {}

    async def read(coro_fn):
        async with gate:
            return await coro_fn()

    async def one(sym: str):
        rec: Dict[str, Any] = {"futures": None, "options": None, "options_exp": None, "past": []}
        out[sym] = rec
        try:
            rec["futures"] = await read(lambda: fno_contracts(sym, day, "STF"))
        except Exception as e:  # noqa: BLE001
            gaps[sym] = f"futures contracts could not be read (DaaS {_why(e)})"
            return
        legs = sc._contract_day(rec["futures"])
        rec["options_exp"] = sc.options_expiry(legs, day)
        if rec["options_exp"]:
            try:
                rec["options"] = await read(lambda: fno_contracts(sym, day, "STO", rec["options_exp"]))
            except Exception as e:  # noqa: BLE001
                gaps[sym] = f"options {rec['options_exp']} could not be read (DaaS {_why(e)})"
        if not legs:
            return
        try:
            near = date.fromisoformat(str(legs[0].get("expiry_date"))[:10])
        except ValueError:
            return
        n = sum(1 for s in ss if day < s <= near)
        if near < day or n > sc.ROLLOVER_WINDOW_SESSIONS:
            return
        try:
            exps = await read(lambda: fno_expiries(sym))
        except Exception as e:  # noqa: BLE001
            gaps[sym] = f"past expiries could not be read (DaaS {_why(e)})"
            return
        prev = [e for e in exps if e < near and e <= day][-sc.ROLLOVER_PAST_EXPIRIES:]
        for e in prev:
            if e not in ss or ss.index(e) - n < 0:
                continue                         # outside the loaded calendar
            d_k = ss[ss.index(e) - n]
            try:
                rows = await read(lambda: fno_contracts(sym, d_k, "STF", past=True))
            except Exception as ex:  # noqa: BLE001
                gaps[sym] = f"past rollover readings could not all be read (DaaS {_why(ex)})"
                continue
            rec["past"].append((e.isoformat(), d_k.isoformat(), rows))

    await asyncio.gather(*(one(s) for s in dict.fromkeys(symbols)))
    return out, gaps


async def nifty(start: date, end: date) -> Tuple[Dict[date, float], Optional[str]]:
    async def fetch():
        # the same read as daas_client.get_index_eod_history, but a failure raises instead of reading as "no rows"
        rows: List[Dict[str, Any]] = []
        offset = 0
        while offset < 5000:
            st, body = await daas_get(f"/indices/{quote(NIFTY)}/eod", {"limit": 500, "offset": offset, "start": start.isoformat(),
                                                               "end": end.isoformat()})
            if st != 200 or not isinstance(body, dict):
                raise daas_client.DaasError(f"index EOD HTTP {st}", status_code=st)
            page = body.get("data") or body.get("rows") or []
            rows.extend(page)
            if len(page) < 500:
                break
            offset += 500
        return rows
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
        return {}, "Nifty 50 closes could not be read (DaaS index EOD answered no rows)"
    return out, None


# ── DaaS: the first results filing on the exchange ──────────────────────────────────────────────────────────────

RESULT_SUBJECT = re.compile(r"outcome of board meeting|financial result|integrated filing", re.I)
ANN_PAGE = 500


async def first_results_filings(start: date, end: date) -> Tuple[Dict[str, List[datetime]], Optional[str]]:
    """{symbol: [broadcast times of "earnings"-classified exchange filings whose subject is a board-meeting outcome or
    financial results]} for filings dated in [start, end], from DaaS /announcements (one bulk read, paged). The results
    are often public on the exchange well before the figures reach the stored quarters (BAJAJ-AUTO 27 Oct: filed 15:21
    IST, figures stored with 16:14 IST): the earliest public filing decides when the market could react."""
    async def fetch():
        rows: List[Dict[str, Any]] = []
        offset = 0
        while offset < 10 * ANN_PAGE:
            st, body = await daas_get("/announcements", {"category": "earnings", "filed_from": start.isoformat(),
                                                         "filed_to": end.isoformat(), "limit": ANN_PAGE, "offset": offset}, timeout=30.0)
            if st != 200 or not isinstance(body, dict):
                raise daas_client.DaasError(f"announcements HTTP {st}", status_code=st)
            page = body.get("data") or []
            rows.extend(page)
            if len(page) < ANN_PAGE:
                break
            offset += ANN_PAGE
        return rows
    try:
        rows = await _cached("results_filings", (start.isoformat(), end.isoformat()), fetch)
    except Exception as e:  # noqa: BLE001
        return {}, f"exchange results filings could not be read ({_why(e)}): reactions are timed from the stored figures"
    out: Dict[str, List[datetime]] = {}
    for r in rows or []:
        if not isinstance(r, dict) or not RESULT_SUBJECT.search(str(r.get("subject") or "")):
            continue
        from . import scoring as sc
        t = sc.parse_ts(r.get("broadcast_at")) or sc.parse_ts(r.get("filed_at"))
        sym = str(r.get("ticker_symbol") or "").upper()
        if t and sym:
            out.setdefault(sym, []).append(t)
    return out, None


# ── Mongo: the filing analysis ────────────────────────────────────────────────────────────────────────────────────

def _is_analysis(d: Dict[str, Any]) -> bool:
    m = d.get("mode") or ""
    return m == "single_full" or m.endswith("_compact")


async def filing_analysis(db, symbols: Iterable[str], start: datetime, end: datetime) -> Tuple[Dict[str, List[Dict[str, Any]]], Optional[str]]:
    """{symbol: [results analyses (event_type containing "RESULT"; single_full or *_compact; tools off and isolated) with
    event_ts in [start, end)]}.
    (data, gap). A failed read is a gap, never "not analysed"."""
    syms = list(dict.fromkeys(symbols))
    if not syms:
        return {}, None
    # event_type is written by the analysis model: RESULTS, QUARTERLY RESULTS, RESULTS AND DIVIDEND, … (staging 27 Oct).
    q = {"event_type": {"$regex": RESULTS_TYPE, "$options": "i"}, "symbol": {"$in": syms}, "tool_isolation": ISOLATED,
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
