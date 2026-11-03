"""Today's price for a stock or a futures contract before the exchange's end-of-day file is in. Read only.

The owner's rule (29 Oct 2026), in one place for every stock and F&O screen:

    market open (09:15-15:30 IST)        the live Kite quote: the feed's snapshot, Redis first; a bar still in progress
    after the close, before the EOD      the saved Kite close (Mongo kite_live_close, written once just after 15:30 IST)
    once the exchange's EOD rows are in  the end-of-day data; nothing from here is added

`day_quotes` reads one trading day's quotes, `join_bar` appends that day's bar to an end-of-day series only when it joins
the series, and `extend_daily` does both for one symbol. A bar from here is PROVISIONAL and says so: raw Kite prices, the
last traded price at the close (the exchange's official close in the evening file can differ slightly). It joins only when
Kite's previous close equals the series' last close, so a split or bonus that is not yet in the adjusted series, or a
missing session, keeps it out. Nothing that fills a paper order reads it: the paper engine reads the exchange's bars only.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import config as cfg
from . import gateway as gw

logger = logging.getLogger(__name__)

JOIN_TOLERANCE = 0.0005           # 0.05 %: Kite's previous close and the series' last close are the same exchange close
SOURCE_TEXT = {
    "kite_live": "Kite live",
    "kite_close": "Kite close",
}


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _ist_day(ts: Any) -> Optional[str]:
    """The IST date of an ISO stamp (Kite's stamps are IST), or None."""
    if not ts:
        return None
    try:
        d = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=cfg.IST)
    return d.astimezone(cfg.IST).date().isoformat()


def in_session(now: datetime) -> bool:
    """09:15-15:30 IST on a weekday (holidays are caught by the feed not being live)."""
    t = now.astimezone(cfg.IST)
    return t.weekday() < 5 and cfg.OPEN <= t.time() <= cfg.CLOSE


def traded_on(q: Optional[dict], day: str) -> bool:
    """The quote traded on `day`: a positive day volume (Kite resets it each session) and, when Kite stamped it, a stamp on
    that day. Kite's quote() answers a price for an instrument that never traded today; this keeps that price out."""
    if not q or (_num(q.get("ltp")) or 0) <= 0 or (_num(q.get("volume")) or 0) <= 0:
        return False
    stamp = _ist_day(q.get("exchange_ts"))
    return stamp is None or stamp == day


def _fresh(snap: dict, status: dict, now: datetime) -> bool:
    at = snap.get("data_at")
    try:
        d = datetime.fromisoformat(str(at)) if at else None
    except ValueError:
        d = None
    if d is None:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    try:
        cadence = int(status.get("cadence_seconds") or cfg.cadence_seconds())
    except (TypeError, ValueError):
        cadence = cfg.cadence_seconds()
    return status.get("state") == "live" and (now - d).total_seconds() <= cfg.stale_after_seconds(cadence)


async def day_quotes(symbols: Iterable[str], *, now: Optional[datetime] = None, feed: Any = None) -> Dict[str, Any]:
    """Today's quotes for `symbols` (cash stocks, indices, the futures the feed carries), by the rule above:

        {"source": "kite_live" | "kite_close" | None, "day": "YYYY-MM-DD", "as_of": ISO | None,
         "quotes": {SYMBOL: quote}, "why": None | "feed_not_live" | "no_saved_close" | "unreadable"}

    A quote is the feed's shape (ltp, open, high, low, close = the PREVIOUS close, volume, oi, exchange_ts, ...). Only symbols
    that traded that day are in `quotes`. Never raises: a read failure answers no quotes with why "unreadable"."""
    from . import quote_cache as qc
    from .feed import get_feed

    now = now or datetime.now(timezone.utc)
    syms = [s for s in dict.fromkeys(gw.canon(x) for x in symbols) if s]
    out: Dict[str, Any] = {"source": None, "day": None, "as_of": None, "quotes": {}, "why": None}
    try:
        feed = feed or get_feed()
        if in_session(now):
            out["day"] = now.astimezone(cfg.IST).date().isoformat()
            status = await feed.read_status() or {}
            snap = await feed.read_snapshot() or {}
            if not _fresh(snap, status, now):
                out["why"] = "feed_not_live"
                return out
            by = {q.get("symbol"): q for q in snap.get("quotes", []) if q.get("symbol") in set(syms)}
            cached = await qc.read_quotes(syms) if syms else {}
            for s, row in (cached or {}).items():
                have, new = by.get(s), qc.as_quote(row)
                if have is None or str(new.get("received_at") or "") >= str(have.get("received_at") or ""):
                    by[s] = {**new, "symbol": s}
            out.update(source="kite_live", as_of=snap.get("data_at"))
        else:
            out["day"] = cfg.last_close(now).astimezone(cfg.IST).date().isoformat()
            doc = await feed.read_close(out["day"])
            if not doc:
                out["why"] = "no_saved_close"
                return out
            by = {q.get("symbol"): q for q in doc.get("quotes", []) if q.get("symbol") in set(syms)}
            out.update(source="kite_close", as_of=doc.get("data_at"))
    except Exception as e:  # noqa: BLE001 — a screen without today's price still shows the exchange's days
        logger.warning("day quotes: unreadable (%s)", type(e).__name__)
        out["why"] = "unreadable"
        return out
    out["quotes"] = {s: by[s] for s in syms if traded_on(by.get(s), out["day"])}
    return out


def _weekdays_between(a: str, b: str) -> List[date]:
    """Weekdays strictly between two ISO days."""
    d, end, out = date.fromisoformat(a) + timedelta(days=1), date.fromisoformat(b), []
    while d < end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def day_bar(q: dict, day: str) -> Optional[list]:
    """[day, open, high, low, close, volume] from a quote, close = the last price. The high and low take in the last price
    (a snapshot's high can trail its last trade by a tick: that trade is real, so the range includes it). None without an
    open or a price."""
    o, h, l, c, v = (_num(q.get(k)) for k in ("open", "high", "low", "ltp", "volume"))
    if o is None or c is None or o <= 0 or c <= 0:
        return None
    h = max(x for x in (h, o, c) if x is not None)
    l = min(x for x in (l, o, c) if x is not None and x > 0)
    return [day, o, h, l, c, v or 0.0]


def join_bar(bars: List[list], q: Optional[dict], day: Optional[str], *, source: Optional[str] = None,
             as_of: Optional[str] = None, holidays: Optional[Set[date]] = None) -> Tuple[List[list], Dict[str, Any]]:
    """`bars` ([[day, o, h, l, c, v]], oldest first, the exchange's end-of-day series) with `day`'s bar from quote `q` appended
    when it joins, and what happened:

        {"used": True, "source", "day", "provisional": True, "at", "price", "text"}         appended
        {"used": False, "why": eod_in | no_quote | not_traded_today | does_not_join | gap_unchecked | bad_candle, "text"}

    eod_in: the series already has that day (the exchange's prices win). does_not_join: Kite's previous close is not the
    series' last close. gap_unchecked: a weekday sits between the two days and the holidays were not given (or it was not a
    holiday)."""
    if not bars or not day:
        return bars, {"used": False, "why": "no_quote", "text": None}
    last_day = str(bars[-1][0])[:10]
    if last_day >= day:
        return bars, {"used": False, "why": "eod_in", "text": None}
    if not q:
        return bars, {"used": False, "why": "no_quote", "text": None}
    if not traded_on(q, day):
        return bars, {"used": False, "why": "not_traded_today", "text": None}
    gap = _weekdays_between(last_day, day)
    if gap and (holidays is None or any(d not in holidays for d in gap)):
        return bars, {"used": False, "why": "gap_unchecked",
                      "text": f"The end-of-day series ends {last_day}; a session before {day} is missing, so the {SOURCE_TEXT.get(source or '', 'Kite')} price is not joined."}
    prev, last_close = _num(q.get("close")), _num(bars[-1][4])
    if prev is None or not last_close or abs(prev - last_close) > JOIN_TOLERANCE * last_close:
        return bars, {"used": False, "why": "does_not_join",
                      "text": f"Kite's previous close ({prev}) is not the end-of-day close of {last_day} ({last_close}): a split, bonus or "
                              "missing session, so today's Kite price is not joined to the adjusted series."}
    bar = day_bar(q, day)
    if bar is None:
        return bars, {"used": False, "why": "bad_candle", "text": None}
    word = SOURCE_TEXT.get(source or "", "Kite")
    text = (f"{day}: {word} (the session is open; this candle is still forming)" if source == "kite_live"
            else f"{day}: {word}, provisional until the exchange's end-of-day file")
    return [*bars, bar], {"used": True, "source": source, "day": day, "provisional": True,
                          "at": q.get("exchange_ts") or as_of, "price": bar[4], "text": text}


async def holidays_between(a: str, b: str) -> Optional[Set[date]]:
    """NSE cash holidays strictly between two days from the data platform, or None when unreadable."""
    from services.copilot_tools import daas_client
    try:
        status, body = await daas_client.get_raw("/holidays", {"segment": "CM", "from": a, "to": b})
    except Exception as e:  # noqa: BLE001
        logger.warning("day quotes: holidays unreadable (%s)", type(e).__name__)
        return None
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), list):
        return None
    out: Set[date] = set()
    for r in body["data"]:
        try:
            out.add(date.fromisoformat(str(r.get("holiday_date"))[:10]))
        except (TypeError, ValueError):
            continue
    return out


async def extend_daily(bars: List[list], symbol: str, *, now: Optional[datetime] = None, feed: Any = None,
                       quotes: Optional[Dict[str, Any]] = None) -> Tuple[List[list], Dict[str, Any]]:
    """One symbol's end-of-day series with today's Kite bar appended when the rule allows it (see `join_bar`). `quotes` is a
    `day_quotes` answer the caller already read (a list route reads once for all its symbols)."""
    sym = gw.canon(symbol)
    if not bars:
        return bars, {"used": False, "why": "no_quote", "text": None}
    dq = quotes if quotes is not None else await day_quotes([sym], now=now, feed=feed)
    day = dq.get("day")
    if not day or str(bars[-1][0])[:10] >= day:
        return bars, {"used": False, "why": "eod_in" if day else (dq.get("why") or "no_quote"), "text": None}
    q = (dq.get("quotes") or {}).get(sym)
    if q is None:
        return bars, {"used": False, "why": dq.get("why") or "no_quote", "text": None}
    hol = None
    if _weekdays_between(str(bars[-1][0])[:10], day):
        hol = await holidays_between(str(bars[-1][0])[:10], day)
    return join_bar(bars, q, day, source=dq.get("source"), as_of=dq.get("as_of"), holidays=hol)
