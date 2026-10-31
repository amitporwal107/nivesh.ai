"""Intraday candles (5m / 15m / 30m / 60m) read on demand from Kite historical_data with the platform token.

Why on demand: nothing in the warehouse stores intraday bars on staging (nidp.intraday_bars needs the kite_bars collector, which is
not scheduled there). This read path does NOT depend on warehouse writes. The collector (nidp/services/kite_bars, migration 152)
is untouched; running it on a schedule is an optional way to keep a durable history (see test_reports/OVERRIDE_kite_live_feed.md).

Rules:
  * bars are Kite's own candles, raw (not split/bonus adjusted), labelled source "Kite intraday" with the fetch time as `as_of`;
  * nothing is invented: an invalid candle is dropped, a missing token or a Kite refusal gives an empty list and a reason;
  * the live feed's last price is merged ONLY into a candle that already exists and is still in progress (close, and high/low if
    exceeded); no candle is created from a price alone;
  * Kite's historical limit (~3 requests/second) is respected by a process-wide gate; results are cached for a short time
    (60 s while the session is open, 10 min otherwise); the window is capped per interval (Kite's own limits).

Futures with open interest (`futures_bars`, for GET /api/fno/{symbol}/futures/oi-buildup): the underlying's NFO futures
still listed today (Kite's NFO instrument list, read once a day), nearest expiry first, at most three (current, next, far
month), each read with historical_data oi=1. The same gate, cache and token rules; a bar with a negative or missing OI keeps
its prices and gets OI null.

Options with open interest (`options_intraday`, for GET /api/fno/{symbol}/options/intraday): the same NFO list read gives each
underlying's nearest unexpired option expiry (kept for the day; on the expiry day that day's contracts); the ATM strike from
the cash symbol's reference price (the caller's live quote / saved Kite close, else the last Kite candle), ATM ± `strikes`
listed strikes, CE and PE, each read with historical_data oi=1 through the same gate (22 contracts ≈ 9 s on a cold read) and
cached per (symbol, interval, sessions, strikes). The sums and changes are services/fno_options_intraday.py.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config as cfg
from . import gateway as gw
from . import universe as uni

logger = logging.getLogger(__name__)

# interval -> (Kite name, minutes, max calendar days Kite allows per request)
INTERVALS: Dict[str, Tuple[str, int, int]] = {
    "5m": ("5minute", 5, 100), "15m": ("15minute", 15, 200), "30m": ("30minute", 30, 100), "60m": ("60minute", 60, 400),
}
SOURCE = "Kite intraday"
PROVIDER = "kite-connect-v3"
SPACING_SECONDS = 0.4                      # >= 1/3 s: Kite's historical limit is 3 requests per second
CACHE_OPEN_SECONDS, CACHE_CLOSED_SECONDS = 60, 600
MAX_SESSIONS = 30


def _bar(c: dict) -> Optional[list]:
    """[iso time IST, o, h, l, c, v] or None for a candle that cannot be drawn truthfully."""
    try:
        d = c["date"]
        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        v = float(c.get("volume") or 0.0)
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(d, datetime) or min(o, h, l, cl) <= 0 or h < max(o, cl) or l > min(o, cl):
        return None
    d = d if d.tzinfo else d.replace(tzinfo=cfg.IST)
    return [d.astimezone(cfg.IST).isoformat(), o, h, l, cl, v]


def _oi_bar(c: dict) -> Optional[list]:
    """[iso time IST, o, h, l, c, v, oi] (oi None when Kite sent none) or None for a candle that cannot be drawn."""
    b = _bar(c)
    if b is None:
        return None
    try:
        oi = float(c["oi"]) if c.get("oi") is not None else None
    except (TypeError, ValueError):
        oi = None
    return b + [oi if oi is not None and oi >= 0 else None]


FUTURES_MAX = 3                            # current, next and far month
NFO_REREAD_SECONDS = 1800


def merge_live(bars: List[list], ltp: Optional[float], now: datetime, minutes: int) -> bool:
    """Fold the live price into the in-progress candle. True when it was changed. Never adds a candle."""
    if not bars or ltp is None or ltp <= 0:
        return False
    last = bars[-1]
    start = datetime.fromisoformat(last[0])
    if not (start <= now < start + timedelta(minutes=minutes)):
        return False
    last[4] = ltp
    last[2] = max(last[2], ltp)
    last[3] = min(last[3], ltp)
    return True


class IntradayService:
    def __init__(self, *, token_getter: Callable[[], str] = cfg.get_token, key_getter: Callable[[], str] = cfg.get_api_key,
                 kite_factory=gw.default_kite_factory, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleep=asyncio.sleep):
        self.token_getter, self.key_getter, self.kite_factory, self.clock, self.sleep = token_getter, key_getter, kite_factory, clock, sleep
        self._gate = asyncio.Lock()
        self._last_call = 0.0
        self._inst: Tuple[Optional[date], Dict[str, int]] = (None, {})
        self._nfo: Tuple[Optional[date], Dict[str, List[Dict[str, Any]]]] = (None, {})
        # underlying -> (its nearest unexpired option expiry, that expiry's CE/PE contracts), from the same NFO read
        self._nfo_opts: Tuple[Optional[date], Dict[str, Tuple[str, List[Dict[str, Any]]]]] = (None, {})
        self._nfo_read_at = 0.0
        self._cache: Dict[Tuple[str, str, int], Tuple[float, dict]] = {}

    def _empty(self, symbol: str, interval: str, reason: str, now: datetime) -> Dict[str, Any]:
        return {"symbol": symbol, "interval": interval, "source": SOURCE, "provider": PROVIDER, "as_of": now.isoformat(), "availability": reason,
                "bars": [], "count": 0, "live_merged": False, "in_progress_bar": None, "session_dates": [], "adjusted": False}

    async def _paced(self, fn, *args):
        """Run one Kite call off the loop, never faster than 3 per second across the process."""
        async with self._gate:
            wait = self._last_call + SPACING_SECONDS - time.monotonic()
            if wait > 0:
                await self.sleep(wait)
            try:
                return await asyncio.to_thread(fn, *args)
            finally:
                self._last_call = time.monotonic()

    async def _token_for(self, kite, symbol: str, now: datetime) -> Optional[int]:
        day = now.astimezone(cfg.IST).date()
        if self._inst[0] != day:
            rows = await self._paced(kite.instruments, "NSE")
            m: Dict[str, int] = {}
            for r in rows:
                if r.get("segment") == "INDICES" or r.get("instrument_type") == "EQ":
                    try:
                        m[gw.canon(r["tradingsymbol"])] = int(r["instrument_token"])
                    except (KeyError, TypeError, ValueError):
                        continue
            self._inst = (day, m)
        return self._inst[1].get(gw.canon(symbol))

    async def bars(self, symbol: str, interval: str, sessions: int = 5, *, session_open: bool = False,
                   live_ltp: Optional[float] = None) -> Dict[str, Any]:
        now = self.clock().astimezone(timezone.utc)
        sym = gw.canon(symbol)
        if interval not in INTERVALS:
            raise ValueError("unsupported interval")
        kname, minutes, max_days = INTERVALS[interval]
        sessions = max(1, min(MAX_SESSIONS, int(sessions)))
        token, key = self.token_getter(), self.key_getter()
        if not token or not key:
            return self._empty(sym, interval, "token_missing", now)
        ck = (sym, interval, sessions)
        hit = self._cache.get(ck)
        ttl = CACHE_OPEN_SECONDS if session_open else CACHE_CLOSED_SECONDS
        if hit and time.monotonic() - hit[0] < ttl:
            out = {**hit[1], "bars": [list(b) for b in hit[1]["bars"]]}
        else:
            from services.providers.contract import AUTH_EXPIRED
            from services.providers.kite_adapter import classify
            try:
                kite = self.kite_factory(key, token)
                itoken = await self._token_for(kite, sym, now)
                if itoken is None:
                    return self._empty(sym, interval, "symbol_not_found", now)
                days = min(max_days, sessions * 7 // 5 + 3)
                t_to = now.astimezone(cfg.IST).replace(tzinfo=None)
                rows = await self._paced(kite.historical_data, itoken, t_to - timedelta(days=days), t_to, kname)
            except Exception as e:  # noqa: BLE001 — classified; the message (which could echo request fields) is never returned or logged
                code = classify(e)
                logger.warning("intraday bars: kite call failed (%s, %s)", type(e).__name__, code)
                if code == AUTH_EXPIRED:
                    return self._empty(sym, interval, "token_expired", now)
                raise RuntimeError("upstream_unavailable") from None
            bars = [b for b in (_bar(c) for c in rows or []) if b]
            bars.sort(key=lambda b: b[0])
            keep = sorted({b[0][:10] for b in bars})[-sessions:]
            bars = [b for b in bars if b[0][:10] in keep]
            out = {"symbol": sym, "interval": interval, "source": SOURCE, "provider": PROVIDER, "as_of": now.isoformat(),
                   "availability": "ok" if bars else "no_bars", "bars": bars, "count": len(bars), "live_merged": False,
                   "in_progress_bar": None, "session_dates": keep, "adjusted": False}
            self._cache[ck] = (time.monotonic(), {**out, "bars": [list(b) for b in bars]})
        if session_open and out["bars"]:
            merged = merge_live(out["bars"], live_ltp, now.astimezone(cfg.IST), minutes)
            out["live_merged"] = merged
            out["in_progress_bar"] = out["bars"][-1][0] if merged else None
        out["note"] = "Kite candles, raw prices (not split/bonus adjusted). The live price is merged only into a candle still in progress."
        return out

    async def _futures_for(self, kite, symbol: str, now: datetime) -> List[Dict[str, Any]]:
        """The underlying's futures still listed today, nearest expiry first, at most FUTURES_MAX."""
        day = now.astimezone(cfg.IST).date()
        listed = [c for c in self._nfo[1].get(gw.canon(symbol), []) if c["expiry"] >= day.isoformat()] if self._nfo[0] == day else []
        # After an expiry Kite lists the new far month only later in the morning: a list read before that holds two months,
        # so it is read again (at most every NFO_REREAD_SECONDS) while fewer than three are listed.
        stale = self._nfo[0] == day and len(listed) < FUTURES_MAX and time.monotonic() - self._nfo_read_at > NFO_REREAD_SECONDS
        if self._nfo[0] != day or stale:
            await self._load_nfo(kite, day)
        return [c for c in self._nfo[1].get(gw.canon(symbol), []) if c["expiry"] >= day.isoformat()][:FUTURES_MAX]

    async def _load_nfo(self, kite, day: date) -> None:
        """Read Kite's NFO list once: every underlying's futures, and its nearest unexpired option expiry's contracts."""
        rows = await self._paced(kite.instruments, "NFO")
        self._nfo_read_at = time.monotonic()
        today = day.isoformat()
        m: Dict[str, List[Dict[str, Any]]] = {}
        opts: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for r in rows:
            kind = r.get("instrument_type")
            if kind not in ("FUT", "CE", "PE"):
                continue
            try:
                exp = r["expiry"]
                exp_iso = exp.isoformat() if isinstance(exp, date) else date.fromisoformat(str(exp)[:10]).isoformat()
                name, token = gw.canon(r["name"]), int(r["instrument_token"])
                if kind == "FUT":
                    m.setdefault(name, []).append({"expiry": exp_iso, "token": token,
                                                   "tradingsymbol": r.get("tradingsymbol"), "lot_size": r.get("lot_size")})
                elif exp_iso >= today:
                    strike = float(r["strike"])
                    if strike > 0:
                        opts.setdefault(name, {}).setdefault(exp_iso, []).append(
                            {"strike": strike, "type": kind, "token": token, "tradingsymbol": r.get("tradingsymbol")})
            except (KeyError, TypeError, ValueError):
                continue
        for v in m.values():
            v.sort(key=lambda x: x["expiry"])
        self._nfo = (day, m)
        self._nfo_opts = (day, {name: (min(by), by[min(by)]) for name, by in opts.items()})

    async def _options_for(self, kite, symbol: str, now: datetime) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
        """(the nearest unexpired option expiry, its CE/PE contracts) of `symbol`, or None when Kite lists none."""
        day = now.astimezone(cfg.IST).date()
        if self._nfo_opts[0] != day:
            await self._load_nfo(kite, day)
        return self._nfo_opts[1].get(gw.canon(symbol))

    async def futures_bars(self, symbol: str, interval: str, sessions: int = 3, *, session_open: bool = False) -> Dict[str, Any]:
        """Candles with open interest for the current / next / far month futures of `symbol`. `availability` ok, token_missing,
        token_expired, no_futures or no_bars; `contracts` [{expiry, tradingsymbol, lot_size, bars: [[t, o, h, l, c, v, oi]]}]."""
        now = self.clock().astimezone(timezone.utc)
        sym = gw.canon(symbol)
        if interval not in INTERVALS:
            raise ValueError("unsupported interval")
        kname, _minutes, max_days = INTERVALS[interval]
        sessions = max(1, min(MAX_SESSIONS, int(sessions)))
        base = {"symbol": sym, "interval": interval, "source": "Kite intraday, futures with open interest", "provider": PROVIDER,
                "as_of": now.isoformat(), "contracts": [], "adjusted": False}
        token, key = self.token_getter(), self.key_getter()
        if not token or not key:
            return {**base, "availability": "token_missing"}
        ck = (sym, interval, sessions, "futures")
        hit = self._cache.get(ck)
        ttl = CACHE_OPEN_SECONDS if session_open else CACHE_CLOSED_SECONDS
        if hit and time.monotonic() - hit[0] < ttl:
            return {**hit[1], "contracts": [{**c, "bars": [list(b) for b in c["bars"]]} for c in hit[1]["contracts"]]}
        from services.providers.contract import AUTH_EXPIRED
        from services.providers.kite_adapter import classify
        out_contracts: List[Dict[str, Any]] = []
        try:
            kite = self.kite_factory(key, token)
            listed = await self._futures_for(kite, sym, now)
            if not listed:
                return {**base, "availability": "no_futures"}
            days = min(max_days, sessions * 7 // 5 + 3)
            t_to = now.astimezone(cfg.IST).replace(tzinfo=None)
            for c in listed:
                rows = await self._paced(kite.historical_data_oi, c["token"], t_to - timedelta(days=days), t_to, kname)
                bars = sorted((b for b in (_oi_bar(r) for r in rows or []) if b), key=lambda b: b[0])
                out_contracts.append({"expiry": c["expiry"], "tradingsymbol": c["tradingsymbol"], "lot_size": c["lot_size"], "bars": bars})
        except Exception as e:  # noqa: BLE001 — classified; the message (which could echo request fields) is never returned or logged
            code = classify(e)
            logger.warning("futures bars: kite call failed (%s, %s)", type(e).__name__, code)
            if code == AUTH_EXPIRED:
                return {**base, "availability": "token_expired"}
            raise RuntimeError("upstream_unavailable") from None
        keep = sorted({b[0][:10] for c in out_contracts for b in c["bars"]})[-sessions:]
        for c in out_contracts:
            c["bars"] = [b for b in c["bars"] if b[0][:10] in keep]
        out = {**base, "availability": "ok" if out_contracts and out_contracts[0]["bars"] else "no_bars",
               "contracts": out_contracts, "session_dates": keep}
        self._cache[ck] = (time.monotonic(), {**out, "contracts": [{**c, "bars": [list(b) for b in c["bars"]]} for c in out_contracts]})
        return out

    async def _candle_ref(self, spot: str, interval: str, session_open: bool) -> Optional[Dict[str, Any]]:
        """The cash symbol's last Kite candle close as the reference price, or None."""
        r = await self.bars(spot, interval, 1, session_open=session_open)
        if not r.get("bars"):
            return None
        last = r["bars"][-1]
        return {"price": float(last[4]), "source": "candle", "at": last[0]}

    async def options_intraday(self, symbol: str, interval: str, sessions: int = 2, strikes: int = 5, *,
                               session_open: bool = False, ref_getter=None) -> Dict[str, Any]:
        """The options pane's answer (services/fno_options_intraday.py has the shape): the nearest expiry's CE and PE at the
        ATM strike ± `strikes` listed strikes, Kite candles with OI. `ref_getter` is an async (cash symbol) -> {price, source,
        at} | None giving today's Kite quote; without one, the cash symbol's last Kite candle is the reference. Never raises
        for a Kite failure: `availability` says token_missing, token_expired, no_options, no_bars or upstream_unavailable."""
        from services import fno_options_intraday as foi
        from services.providers.contract import AUTH_EXPIRED
        from services.providers.kite_adapter import classify

        now = self.clock().astimezone(timezone.utc)
        sym = gw.canon(symbol)
        if interval not in INTERVALS:
            raise ValueError("unsupported interval")
        if not 1 <= int(strikes) <= foi.MAX_STRIKES:
            raise ValueError("strikes out of range")
        kname, _minutes, max_days = INTERVALS[interval]
        sessions = max(1, min(MAX_SESSIONS, int(sessions)))
        token, key = self.token_getter(), self.key_getter()
        if not token or not key:
            return foi.empty(sym, interval, sessions, "token_missing", now)
        ck = (sym, interval, sessions, "options", int(strikes))
        hit = self._cache.get(ck)
        ttl = CACHE_OPEN_SECONDS if session_open else CACHE_CLOSED_SECONDS
        if hit and time.monotonic() - hit[0] < ttl:
            return copy.deepcopy(hit[1])
        spot = uni.OPTION_SPOT.get(sym, sym)
        try:
            kite = self.kite_factory(key, token)
            chain = await self._options_for(kite, sym, now)
            if not chain:
                return foi.empty(sym, interval, sessions, "no_options", now)
            expiry, listed = chain
            ref = await ref_getter(spot) if ref_getter else None
            if not ref or not ref.get("price"):
                ref = await self._candle_ref(spot, interval, session_open)
            if not ref:
                return foi.empty(sym, interval, sessions, "no_bars", now, expiry=expiry,
                                 note=f"No Kite price for {spot} (no quote and no candle), so the ATM strike cannot be set.")
            atm, chosen = foi.pick_strikes([o["strike"] for o in listed], float(ref["price"]), int(strikes))
            wanted = foi.contracts_for(listed, chosen)
            # one more session than sent: its last candle is the baseline of the first row's change
            days = min(max_days, (sessions + 1) * 7 // 5 + 3)
            t_to = now.astimezone(cfg.IST).replace(tzinfo=None)
            got: List[Dict[str, Any]] = []
            for c in wanted:
                rows = await self._paced(kite.historical_data_oi, c["token"], t_to - timedelta(days=days), t_to, kname)
                bars = sorted((b for b in (_oi_bar(r) for r in rows or []) if b), key=lambda b: b[0])
                got.append({"tradingsymbol": c["tradingsymbol"], "strike": c["strike"], "type": c["type"], "bars": bars})
        except Exception as e:  # noqa: BLE001 — classified; the message (which could echo request fields) is never returned or logged
            code = classify(e)
            logger.warning("options intraday: kite call failed (%s, %s)", type(e).__name__, code)
            return foi.empty(sym, interval, sessions, "token_expired" if code == AUTH_EXPIRED else "upstream_unavailable", now)
        out = foi.answer(sym, interval, sessions, expiry, atm, chosen, int(strikes), ref, got, now)
        self._cache[ck] = (time.monotonic(), copy.deepcopy(out))
        return out
