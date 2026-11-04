"""The price of every open paper position now, and how much to trust it. Read-only towards Kite (gw.ReadOnlyKite has no
order, GTT, margin or session call), and display-only: nothing here fills, exits or marks the ledger.

The rule (owner 29 Oct "Kite close until EOD", 28 Oct "no stale market data"), first that applies:

    session open, a quote on the feed (Redis, else the snapshot)        Kite live           LIVE, or DELAYED when older than
                                                                                            the feed's stale limit
    session open, a contract off the feed (stock options, far strikes,  Kite REST quote()   LIVE / DELAYED by its exchange time
      next-month futures): named contracts only, <= MAX_REST_KEYS
    otherwise the newer of: the saved Kite close of the last session    Kite close          CLOSE (provisional)
      (contracts: their last trade that day over REST)
    and the ledger's own end-of-day mark                                end of day          EOD (wins a tie: it is official)
    nothing                                                             -                   MISSING (the P&L is null)

Freshness, against the feed's own stale limit (2.5 cadences; PNL_STALE_AFTER_SECONDS overrides it):
    feed quotes   from `received_at`, when the feed got the tick (the server clock). NOT the feed's `exchange_ts`: on staging
                  (4 Nov 2026, 09:30 IST) it read 04:00:03+05:30, the container's UTC clock labelled IST (5 h 30 m off), so an
                  age taken from it would call every live quote hours old.
    REST quotes   from Kite's `last_trade_time` (parsed from Kite's IST text, so it is right): the contract's last trade.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services.kite_live_feed import config as cfg
from services.kite_live_feed import day_quote as dq
from services.kite_live_feed import fno_quotes as fq
from services.kite_live_feed import gateway as gw
from services.kite_live_feed import platform_token as pt
from services.kite_live_feed import quote_cache as qc

from .book import Leg

logger = logging.getLogger(__name__)

LIVE, DELAYED, CLOSE, EOD, MISSING = "LIVE", "DELAYED", "CLOSE", "EOD", "MISSING"
SOURCE_TEXT = {
    "kite_live": "Kite live", "kite_rest": "Kite quote (contract off the live feed)", "kite_close": "Kite close (provisional)",
    "kite_rest_close": "Kite last trade of the session (provisional)", "eod": "Exchange end of day",
}
MAX_REST_KEYS = 40
REST_TTL_OPEN_S, REST_TTL_CLOSED_S = 5.0, 300.0

_NFO: Tuple[Optional[str], Dict[Tuple[str, str, Optional[float], str], str], Dict[str, int]] = (None, {}, {})
_NFO_LOCK = asyncio.Lock()
_REST: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_REST_LOCK = asyncio.Lock()


@dataclass
class Quote:
    ltp: Optional[float]
    prev_close: Optional[float]
    status: str
    source: Optional[str]
    at: Optional[str]
    age_seconds: Optional[float]
    day: Optional[str]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f > 0 and f != float("inf") else None


def _when(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=cfg.IST)          # Kite's naive stamps are IST


def stale_after_seconds(status: Optional[dict]) -> float:
    raw = os.environ.get("PNL_STALE_AFTER_SECONDS")
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    try:
        cadence = int((status or {}).get("cadence_seconds") or cfg.cadence_seconds())
    except (TypeError, ValueError):
        cadence = cfg.cadence_seconds()
    return cfg.stale_after_seconds(cadence)


def feed_mode(status: Optional[dict], data_age: Optional[float], stale_after: float) -> str:
    """live | delayed | closed | expired | not_connected | disabled (the shell chip's rule, routes/live_quotes.mode_of)."""
    if not status:
        return "disabled" if not cfg.enabled() else "not_connected"
    st, session = status.get("state"), status.get("session")
    if st in ("expired", "not_connected"):
        return st
    if session == "open":
        return "live" if st == "live" and data_age is not None and data_age <= stale_after else "delayed"
    return "closed"


def live_quote(q: Optional[dict], now: datetime, stale_after: float, mode: str, source: str = "kite_live") -> Optional[Quote]:
    """A feed / REST quote as LIVE or DELAYED, or None when it has no price."""
    if not q:
        return None
    ltp = _num(q.get("ltp") if "ltp" in q else q.get("last_price"))
    if ltp is None:
        return None
    if source == "kite_rest":
        stamp = _when(q.get("exchange_ts") or q.get("exchange_timestamp") or q.get("last_trade_time"))
    else:
        stamp = _when(q.get("received_at"))
    age = round((now - stamp).total_seconds(), 1) if stamp else None
    fresh = mode == "live" and age is not None and age <= stale_after
    if source == "kite_rest":
        fresh = age is not None and age <= stale_after
    day = (stamp or now).astimezone(cfg.IST).date().isoformat()
    return Quote(ltp=ltp, prev_close=_num(q.get("close") if "close" in q else q.get("previous_close")),
                 status=LIVE if fresh else DELAYED, source=SOURCE_TEXT[source],
                 at=stamp.isoformat() if stamp else None, age_seconds=age, day=day)


def choose(*, in_session: bool, live: Optional[Quote], close: Optional[Quote], eod: Optional[Quote]) -> Quote:
    """The rule above. In session a live quote wins; otherwise (or with none) the newer of the Kite close and the
    end-of-day mark, the end-of-day mark on a tie; else MISSING."""
    if in_session and live is not None:
        return live
    picks = [q for q in (close, eod) if q is not None and q.ltp is not None]
    if not picks:
        return Quote(None, None, MISSING, None, None, None, None)
    if len(picks) == 2:
        c, e = picks
        return c if (c.day or "") > (e.day or "") else e
    return picks[0]


def eod_quote(leg: Leg) -> Optional[Quote]:
    if leg.eod_mark is None:
        return None
    basis = {"expiry_intrinsic": "Settled at expiry (intrinsic value)", "final_settle": "Final settlement"}.get(str(leg.eod_basis))
    return Quote(ltp=leg.eod_mark, prev_close=leg.prev_eod, status=EOD, source=basis or SOURCE_TEXT["eod"],
                 at=leg.eod_date, age_seconds=None, day=leg.eod_date)


def settled(leg: Leg) -> bool:
    return leg.eod_basis in ("expiry_intrinsic", "final_settle")


# ── Kite contract names and REST quotes (named contracts only) ──────────────────────────────────────────────────────
TOKEN_REFRESH_S = 60.0
_TOKEN_AT = [0.0]


async def ensure_token(db) -> None:
    """Reload the day's platform token into this worker (only the feed's leader refreshes its own copy; a non-leader worker
    would keep using yesterday's), at most once a minute. Never raises."""
    if time.monotonic() - _TOKEN_AT[0] < TOKEN_REFRESH_S:
        return
    try:
        await pt.refresh_cache(db)
        _TOKEN_AT[0] = time.monotonic()
    except Exception as e:  # noqa: BLE001 — without it the older token is used and a refusal is reported as such
        logger.warning("paper_pnl: token refresh failed (%s)", type(e).__name__)


def _kite():
    key, access = cfg.get_api_key(), cfg.get_token()
    if not key or not access:
        return None
    return gw.default_kite_factory(key, access)


async def _nfo_index(kite, today: str) -> Dict[Tuple[str, str, Optional[float], str], str]:
    """Kite's NFO list keyed by contract identity (fq.index_instruments), read once a day per worker."""
    global _NFO
    if _NFO[0] == today:
        return _NFO[1]
    async with _NFO_LOCK:
        if _NFO[0] != today:
            rows = await asyncio.to_thread(kite.instruments, "NFO")
            tokens: Dict[str, int] = {}
            for r in rows or []:
                try:
                    tokens[str(r["tradingsymbol"])] = int(r["instrument_token"])
                except (KeyError, TypeError, ValueError):
                    continue
            _NFO = (today, fq.index_instruments(rows), tokens)
    return _NFO[1]


async def contract_tokens(kite, legs: Iterable[Leg], today: str) -> Dict[str, Tuple[str, int]]:
    """{position_key: (tradingsymbol, instrument_token)} for futures / option legs Kite lists today."""
    index = await _nfo_index(kite, today)
    out: Dict[str, Tuple[str, int]] = {}
    for l in legs:
        ident = fq.leg_key(l.symbol, l.expiry, l.strike, l.kind, l.option_type)
        ts = index.get(ident) if ident else None
        tok = _NFO[2].get(ts) if ts else None
        if ts and tok:
            out[l.position_key] = (ts, tok)
    return out


def kite_client():
    """The read-only Kite client for the platform session, or None without a key / token."""
    return _kite()


async def _rest_quotes(kite, keys: List[str], ttl: float) -> Dict[str, Dict[str, Any]]:
    """Kite REST quote() rows for "NFO:<tradingsymbol>" keys, each cached `ttl` seconds per worker; one call for the misses."""
    now = time.monotonic()
    out = {k: _REST[k][1] for k in keys if k in _REST and now - _REST[k][0] < ttl}
    missing = [k for k in keys if k not in out][:MAX_REST_KEYS]
    if missing:
        async with _REST_LOCK:
            answer = await asyncio.to_thread(kite.quote, sorted(set(missing)))
            stamp = time.monotonic()
            for k in missing:
                row = (answer or {}).get(k)
                if isinstance(row, dict):
                    _REST[k] = (stamp, row)
                    out[k] = row
    return out


def _rest_row(row: Dict[str, Any]) -> Dict[str, Any]:
    ohlc = row.get("ohlc") if isinstance(row.get("ohlc"), dict) else {}
    return {"ltp": row.get("last_price"), "close": ohlc.get("close"), "volume": row.get("volume"),
            "exchange_ts": row.get("last_trade_time") or row.get("timestamp")}


# ── the one entry point ─────────────────────────────────────────────────────────────────────────────────────────────
async def resolve(legs: Iterable[Leg], *, now: Optional[datetime] = None, feed: Any = None) -> Tuple[Dict[str, Quote], Dict[str, Any]]:
    """({position_key: Quote}, market) for the open legs given. Never raises: an unreadable source is skipped and noted
    in market["notes"]; a leg nobody can price is MISSING."""
    from services.kite_live_feed.feed import get_feed

    now = now or datetime.now(timezone.utc)
    legs = list(legs)
    feed = feed or get_feed()
    notes: List[str] = []
    session_open = dq.in_session(now)
    today = now.astimezone(cfg.IST).date().isoformat()
    try:
        status = await feed.read_status()
        snap = await feed.read_snapshot() or {}
    except Exception as e:  # noqa: BLE001 — the dashboard falls back to end-of-day marks and says so
        logger.warning("paper_pnl: feed status unreadable (%s)", type(e).__name__)
        status, snap = None, {}
        notes.append("The live feed's status could not be read.")
    stale_after = stale_after_seconds(status)
    data_at = _when(snap.get("data_at"))
    data_age = round((now - data_at).total_seconds(), 1) if data_at else None
    mode = feed_mode(status, data_age, stale_after)
    market = {"session": "open" if session_open else ("pre_open" if now.astimezone(cfg.IST).time() < cfg.OPEN
                                                       and now.astimezone(cfg.IST).weekday() < 5 else "closed"),
              "feed": mode, "feed_age_seconds": data_age, "stale_after_seconds": stale_after, "day": today,
              "price_rule": "Live Kite price while the market is open; after 15:30 the Kite close (provisional) until the "
                            "exchange's end-of-day prices are in; otherwise the end-of-day close. Display only: paper fills "
                            "and exits use end-of-day prices.", "notes": notes}

    open_legs = [l for l in legs if not settled(l)]
    stocks = sorted({gw.canon(l.symbol) for l in open_legs if l.kind == "cash"})
    contracts = [l for l in open_legs if l.kind in ("future", "option")]

    live: Dict[str, Quote] = {}
    close: Dict[str, Quote] = {}
    close_day = cfg.last_close(now).astimezone(cfg.IST).date().isoformat()

    # Stocks (and cash legs): the feed in session, the saved Kite close otherwise.
    if stocks:
        if session_open:
            by = {q.get("symbol"): q for q in snap.get("quotes", []) if q.get("symbol") in set(stocks)}
            cached = await qc.read_quotes(stocks)
            if cached is None:
                notes.append("The live quote cache (Redis) is unavailable; the feed's snapshot answered.")
            for s, row in (cached or {}).items():
                have, new = by.get(s), qc.as_quote(row)
                if have is None or str(new.get("received_at") or "") >= str(have.get("received_at") or ""):
                    by[s] = new
            for s in stocks:
                q = live_quote(by.get(s), now, stale_after, mode)
                if q is not None:
                    live[s] = q
        else:
            try:
                doc = await feed.read_close(close_day)
            except Exception as e:  # noqa: BLE001
                doc = None
                notes.append(f"The saved Kite close could not be read ({type(e).__name__}).")
            for q in (doc or {}).get("quotes", []):
                s = q.get("symbol")
                if s in stocks and dq.traded_on(q, close_day) and _num(q.get("ltp")) is not None:
                    close[s] = Quote(ltp=_num(q["ltp"]), prev_close=_num(q.get("close")), status=CLOSE,
                                     source=SOURCE_TEXT["kite_close"], at=(doc or {}).get("data_at"), age_seconds=None, day=close_day)

    # Contracts: the feed's cache by tradingsymbol, then one REST call for the rest (named contracts only).
    by_key: Dict[str, str] = {}
    if contracts:
        kite = None
        try:
            tok = await pt.token_status(feed.db)
            if tok.get("stored") and not tok.get("expired"):
                await ensure_token(feed.db)
            kite = _kite() if tok.get("stored") and not tok.get("expired") else None
            if kite is None:
                notes.append("No Kite session for the platform today: futures and options are priced at end of day.")
            else:
                index = await _nfo_index(kite, today)
                for l in contracts:
                    ident = fq.leg_key(l.symbol, l.expiry, l.strike, l.kind, l.option_type)
                    ts = index.get(ident) if ident else None
                    if ts:
                        by_key[l.position_key] = ts
                    else:
                        notes.append(f"{l.instrument}: no listed contract found; priced at end of day.")
        except Exception as e:  # noqa: BLE001
            notes.append(f"The contract list could not be read ({type(e).__name__}); futures and options are priced at end of day.")
            kite = None
        if by_key:
            cached = await qc.read_quotes(sorted(set(by_key.values()))) if session_open else {}
            rest_keys = [f"NFO:{ts}" for k, ts in by_key.items() if not (session_open and (cached or {}).get(ts))]
            rest: Dict[str, Dict[str, Any]] = {}
            if rest_keys and kite is not None:
                try:
                    rest = await _rest_quotes(kite, rest_keys, REST_TTL_OPEN_S if session_open else REST_TTL_CLOSED_S)
                except Exception as e:  # noqa: BLE001
                    notes.append(f"The Kite quote request failed ({type(e).__name__}); those contracts are priced at end of day.")
            for key, ts in by_key.items():
                row = (cached or {}).get(ts)
                if session_open and row:
                    q = live_quote(qc.as_quote(row), now, stale_after, mode)
                    if q:
                        live[key] = q
                    continue
                r = rest.get(f"NFO:{ts}")
                if not r:
                    continue
                shaped = _rest_row(r)
                if session_open:
                    # Today's last trade, or the previous session's for a contract that has not traded yet today (the
                    # owner's T-1 rule); older than that is not used. A T-1 trade is always DELAYED (it is minutes old).
                    q = live_quote(shaped, now, stale_after, mode, source="kite_rest")
                    if q and (q.day or "") >= close_day:
                        live[key] = q
                else:
                    stamp = _when(shaped.get("exchange_ts"))
                    day = stamp.astimezone(cfg.IST).date().isoformat() if stamp else None
                    if day == close_day and _num(shaped.get("ltp")) is not None:
                        close[key] = Quote(ltp=_num(shaped["ltp"]), prev_close=_num(shaped.get("close")), status=CLOSE,
                                           source=SOURCE_TEXT["kite_rest_close"], at=stamp.isoformat(), age_seconds=None, day=day)

    out: Dict[str, Quote] = {}
    for l in legs:
        if settled(l):
            out[l.position_key] = eod_quote(l) or Quote(None, None, MISSING, None, None, None, None)
            continue
        k = gw.canon(l.symbol) if l.kind == "cash" else l.position_key
        out[l.position_key] = choose(in_session=session_open, live=live.get(k), close=close.get(k), eod=eod_quote(l))
    return out, market


def underlying_quotes(symbols: Iterable[str]) -> List[str]:
    return sorted({gw.canon(s) for s in symbols if s})


async def underlying_prices(symbols: Iterable[str], *, now: Optional[datetime] = None) -> Dict[str, float]:
    """Today's price of strategy underlyings (for their stop / target levels), by the day-quote rule; {} when unreadable."""
    syms = underlying_quotes(symbols)
    if not syms:
        return {}
    got = await dq.day_quotes(syms, now=now)
    return {s: float(q["ltp"]) for s, q in (got.get("quotes") or {}).items() if _num(q.get("ltp")) is not None}


def today_ist(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(cfg.IST).date()
