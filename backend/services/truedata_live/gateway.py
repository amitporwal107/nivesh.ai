"""TrueData behind the live feed's Kite-shaped seam (TS-1 … TS-8 in test_reports/truedata_serving_TESTCASES.md).

Owner, 30 Oct 2026: "Please switch completely to True data". When the market-data switch has TrueData serving, the same
`services/kite_live_feed/feed.LiveFeed` runs (snapshot, close, quote cache, chains, minute and intraday documents, status:
all unchanged) with two injected pieces from here:
  * `TrueDataAsKite`, its read-only client: `instruments("NSE" | "NFO")` is TrueData's symbol master (REST getAllSymbols)
    in Kite's row shape AND Kite's naming (stocks and indices as they are, NIFTY26NOVFUT, monthly NIFTY26NOV22900CE, weekly
    NIFTY26N0322900CE), so every cache key, chain and screen keeps working. `quote()` answers {}: TrueData's bulk quote is
    an add-on we do not have, so without the WebSocket the feed publishes nothing new and its age reads delayed.
  * `TrueDataKiteTicker`, its ticker: KiteTicker's surface (on_connect / on_ticks / on_close / on_error callbacks,
    connect(threaded=True), subscribe, unsubscribe, set_mode, close) over TrueData's WebSocket on its own thread, like
    KiteTicker. touchline / trade / bidask become Kite ticks; a crossed bid/ask is never put in a tick's depth. Every
    message is also handed to `dq` (the data-quality checks, services/truedata_live/serve.py).
TrueData allows one connection per login and `maxsymbols` symbols: the ticker subscribes the feed's tokens in the order
given (the feed's priority) up to that limit and lists the rest as over the limit. Nothing here places an order; no
password or token is logged, stored or returned (errors are logged by class name).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from nidp.shared.sources import truedata as td

from . import checks as ck
from . import protocol as pr

logger = logging.getLogger(__name__)

MONTH_CODES = "123456789OND"                     # Kite's weekly-option month letter: Jan 1 … Sep 9, Oct O, Nov N, Dec D
_MON = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
INDEX_TOKEN_BASE = 2_000_000_000                 # indices have no symbol id in the master: tokens of our own, above TrueData's
DEFAULT_INDICES = ("NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE", "NIFTY MID SELECT", "INDIA VIX", "NIFTY NEXT 50",
                   "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA", "NIFTY FMCG", "NIFTY METAL", "NIFTY REALTY", "NIFTY ENERGY",
                   "NIFTY PSU BANK")
_CONTINUOUS = re.compile(r"^(?P<u>.+)-(I|II|III)$")
# Kite's historical intervals -> TrueData's bar sizes
KITE_INTERVALS = {"minute": "1min", "3minute": "3min", "5minute": "5min", "10minute": "10min", "15minute": "15min",
                  "30minute": "30min", "60minute": "60min", "day": "eod"}


def _naive_ist(v: Any) -> datetime:
    """TrueData takes naive IST times; Kite callers pass datetimes (aware or naive IST) or dates."""
    if isinstance(v, datetime):
        return (v.astimezone(pr.IST) if v.tzinfo else v).replace(tzinfo=None)
    return datetime(v.year, v.month, v.day)


# ── names ────────────────────────────────────────────────────────────────────
def strike_text(strike: float) -> str:
    k = float(strike)
    return str(int(k)) if k.is_integer() else f"{k:.2f}".rstrip("0").rstrip(".")


def kite_future_symbol(underlying: str, expiry: date) -> str:
    return f"{underlying.upper()}{expiry:%y}{_MON[expiry.month - 1]}FUT"


def kite_option_symbol(underlying: str, expiry: date, strike: float, right: str, monthly: bool) -> str:
    """Kite's tradingsymbol: monthly NIFTY26NOV22900CE, weekly NIFTY26N0322900CE (checked against Kite's own symbols on the
    staging feed, 30 Oct 2026: NIFTY26N0322300CE, BANKNIFTY26NOV56200CE, BANKNIFTY26DEC53200CE)."""
    u, r = underlying.upper(), right.upper()
    if r not in ("CE", "PE"):
        raise ValueError(f"option right must be CE or PE, not {right!r}")
    if monthly:
        return f"{u}{expiry:%y}{_MON[expiry.month - 1]}{strike_text(strike)}{r}"
    return f"{u}{expiry:%y}{MONTH_CODES[expiry.month - 1]}{expiry.day:02d}{strike_text(strike)}{r}"


def monthly_expiries(expiries: Iterable[date]) -> set:
    """The last expiry of each calendar month: Kite names those options with the month (NOV), the rest with the day."""
    last: Dict[Tuple[int, int], date] = {}
    for e in expiries:
        k = (e.year, e.month)
        if k not in last or e > last[k]:
            last[k] = e
    return set(last.values())


def _day(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def indices_from_env(env: Optional[Dict[str, str]] = None) -> List[str]:
    env = os.environ if env is None else env
    raw = (env.get("TRUEDATA_INDICES") or "").strip()
    return [" ".join(s.upper().split()) for s in raw.split(",") if s.strip()] if raw else list(DEFAULT_INDICES)


def instrument_rows(eq: List[dict], fo: List[dict], indices: Iterable[str]
                    ) -> Tuple[List[dict], List[dict], Dict[str, str], Dict[str, ck.SymbolMeta]]:
    """TrueData's master → (NSE rows, NFO rows, {Kite tradingsymbol: TrueData symbol}, {TrueData symbol: SymbolMeta}).
    TS-1, TS-2, TS-3. A row without a symbol id, a usable expiry or a strike is left out, never guessed."""
    nse: List[dict] = []
    nfo: List[dict] = []
    names: Dict[str, str] = {}
    meta: Dict[str, ck.SymbolMeta] = {}
    for i, name in enumerate(dict.fromkeys(indices)):
        nse.append({"tradingsymbol": name, "instrument_token": INDEX_TOKEN_BASE + i, "segment": "INDICES",
                    "exchange": "NSE", "instrument_type": "EQ", "name": name, "expiry": "", "strike": 0.0,
                    "lot_size": 0, "tick_size": 0.05})
        names[name] = name
        meta[name] = ck.SymbolMeta(kind="INDEX")
    for r in eq:
        sym, token = str(r.get("symbol") or "").strip().upper(), _int(r.get("symbolid"))
        if not sym or token is None or str(r.get("series") or "").upper() != "EQ":
            continue
        tick = _float(r.get("tick_size"))
        nse.append({"tradingsymbol": sym, "instrument_token": token, "segment": "NSE", "exchange": "NSE",
                    "instrument_type": "EQ", "name": r.get("company") or sym, "expiry": "", "strike": 0.0,
                    "lot_size": 1, "tick_size": tick})
        names[sym] = sym
        meta[sym] = ck.SymbolMeta("EQ", tick, _float(r.get("circuit_low")), _float(r.get("circuit_high")))
    opt_expiries: Dict[str, set] = {}
    for r in fo:
        if str(r.get("series") or "").upper() in ("CE", "PE"):
            u, e = str(r.get("underlying") or "").upper(), _day(r.get("expiry_date"))
            if u and e:
                opt_expiries.setdefault(u, set()).add(e)
    monthly = {u: monthly_expiries(days) for u, days in opt_expiries.items()}
    for r in fo:
        series = str(r.get("series") or "").upper()
        token, u, e = _int(r.get("symbolid")), str(r.get("underlying") or "").upper(), _day(r.get("expiry_date"))
        lot, tick = _int(r.get("lotsize")), _float(r.get("tick_size"))
        if token is None or not u or e is None:
            continue
        if series == "XX" and _CONTINUOUS.match(str(r.get("symbol") or "")):
            ksym = kite_future_symbol(u, e)
            nfo.append({"tradingsymbol": ksym, "instrument_token": token, "segment": "NFO-FUT", "exchange": "NFO",
                        "instrument_type": "FUT", "name": u, "expiry": e, "strike": 0.0, "lot_size": lot,
                        "tick_size": tick})
            names[ksym] = td.future_symbol(u, e)
            meta[names[ksym]] = ck.SymbolMeta("FUT", tick)
        elif series in ("CE", "PE"):
            strike, tsym = _float(r.get("strike")), str(r.get("symbol") or "").strip().upper()
            if not strike or strike <= 0 or not tsym:
                continue
            ksym = kite_option_symbol(u, e, strike, series, e in monthly.get(u, set()))
            nfo.append({"tradingsymbol": ksym, "instrument_token": token, "segment": "NFO-OPT", "exchange": "NFO",
                        "instrument_type": series, "name": u, "expiry": e, "strike": strike, "lot_size": lot,
                        "tick_size": tick})
            names[ksym] = tsym
            meta[tsym] = ck.SymbolMeta("OPT", tick, _float(r.get("circuit_low")), _float(r.get("circuit_high")))
    return nse, nfo, names, meta


class TrueDataAsKite:
    """The live feed's read-only client, from TrueData. instruments() reloads the master once per IST day."""

    def __init__(self, client=None, indices: Optional[Iterable[str]] = None, clock: Callable[[], datetime] = None):
        self._client = client or td.TrueDataClient()
        self._indices = list(indices) if indices is not None else indices_from_env()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._day: Optional[date] = None
        self._rows: Dict[str, List[dict]] = {}
        self.names: Dict[str, str] = {}          # Kite tradingsymbol -> TrueData symbol
        self.tokens: Dict[int, str] = {}         # instrument token -> TrueData symbol
        self.meta: Dict[str, ck.SymbolMeta] = {}
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, List[dict]]:
        day = self._clock().astimezone(pr.IST).date()
        with self._lock:
            if self._day != day or not self._rows:
                eq = self._client.symbol_master("eq")
                fo = self._client.symbol_master("fo")
                nse, nfo, names, meta = instrument_rows(eq, fo, self._indices)
                self._rows, self.names, self.meta, self._day = {"NSE": nse, "NFO": nfo}, names, meta, day
                self.tokens = {r["instrument_token"]: names[r["tradingsymbol"]] for r in nse + nfo}
            return self._rows

    def instruments(self, exchange: str) -> List[dict]:
        return list(self._load().get(str(exchange).upper(), []))

    def quote(self, keys: List[str]) -> Dict[str, dict]:
        return {}

    # Kite's historical_data / historical_data_oi, from TrueData's REST bars (TI-1 … TI-3). TrueData's history is ADJUSTED
    # for corporate actions; the intraday service labels it so. Its 5/15-minute bars name the volume column "Volume".
    def historical_data(self, instrument_token: int, from_date, to_date, interval: str) -> List[dict]:
        return self._history(instrument_token, from_date, to_date, interval, oi=False)

    def historical_data_oi(self, instrument_token: int, from_date, to_date, interval: str) -> List[dict]:
        return self._history(instrument_token, from_date, to_date, interval, oi=True)

    def _history(self, instrument_token: int, from_date, to_date, interval: str, oi: bool) -> List[dict]:
        self._load()
        sym = self.tokens.get(int(instrument_token))
        if sym is None:
            raise td.TrueDataError(td.IDENTIFIER_NOT_RESOLVED, "no TrueData symbol for that instrument token")
        if interval not in KITE_INTERVALS:
            raise td.TrueDataError(td.INVALID_REQUEST, f"interval {interval!r} has no TrueData equivalent")
        rows = self._client.bars(sym, _naive_ist(from_date), _naive_ist(to_date), KITE_INTERVALS[interval])
        out = []
        for r in rows:
            t = pr.parse_ts(r.get("timestamp"))
            if t is None:
                continue
            c = {"date": t, "open": _float(r.get("open")), "high": _float(r.get("high")), "low": _float(r.get("low")),
                 "close": _float(r.get("close")), "volume": _float(r.get("volume", r.get("Volume")))}
            if oi:
                c["oi"] = _float(r.get("oi"))
            out.append(c)
        return out

    def profile(self) -> dict:
        return {"broker": "truedata"}


# ── ticks ────────────────────────────────────────────────────────────────────
def _depth(bid: Optional[float], bid_qty: Optional[float], ask: Optional[float], ask_qty: Optional[float]) -> Optional[dict]:
    """Kite's depth with one level, or None when either side is missing or the book is crossed (TS-6)."""
    if not bid or not ask or bid <= 0 or ask <= 0 or bid > ask + ck.EPS:
        return None
    return {"buy": [{"price": bid, "quantity": bid_qty or 0}], "sell": [{"price": ask, "quantity": ask_qty or 0}]}


def kite_tick(token: int, row: Dict[str, Any]) -> Optional[dict]:
    """A parsed touchline / trade row (protocol.py) as a Kite tick (TS-5). None without a positive last price."""
    ltp = row.get("ltp")
    if not ltp or ltp <= 0:
        return None
    return {"instrument_token": token, "last_price": ltp,
            "ohlc": {"open": row.get("open"), "high": row.get("high"), "low": row.get("low"), "close": row.get("prev_close")},
            "volume_traded": row.get("volume"), "oi": row.get("oi"), "exchange_timestamp": row.get("ts"),
            "depth": _depth(row.get("bid"), row.get("bid_qty"), row.get("ask"), row.get("ask_qty"))}


def _default_connect(creds: Dict[str, str]):
    from .shadow import _default_connect as connect
    return connect(creds)


class TrueDataKiteTicker:
    """KiteTicker's surface over TrueData's WebSocket (TS-5 … TS-8). Callbacks run on this ticker's own thread, as
    KiteTicker's do; services/kite_live_feed/gateway.TickerSource wraps it unchanged."""

    def __init__(self, creds: Dict[str, str], tokens_to_symbols: Callable[[], Dict[int, str]], *, dq=None,
                 connect: Optional[Callable] = None, clock: Callable[[], datetime] = None, login_timeout: float = 20.0):
        self._creds = creds
        self._names = tokens_to_symbols
        self._dq = dq
        self._connect = connect or _default_connect
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._login_timeout = login_timeout
        self.on_connect = self.on_ticks = self.on_close = self.on_error = None
        self.on_reconnect = self.on_noreconnect = None
        self._want: List[int] = []                # tokens asked for, in order
        self._subscribed: List[int] = []          # tokens actually subscribed (≤ maxsymbols)
        self.over_limit: List[str] = []
        self.login: Optional[pr.LoginInfo] = None
        self._id_token: Dict[str, int] = {}       # TrueData session symbol id -> token
        self._last: Dict[int, dict] = {}          # token -> last tick sent (a bidask updates its depth)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self._stop = False
        self._lock = threading.Lock()

    # KiteTicker API
    def connect(self, threaded: bool = True) -> None:
        self._stop = False
        self._thread = threading.Thread(target=self._thread_main, name="truedata-ticker", daemon=True)
        self._thread.start()

    def subscribe(self, tokens: Iterable[int]) -> None:
        with self._lock:
            for t in tokens:
                if t not in self._want:
                    self._want.append(t)
        self._schedule(self._resubscribe())

    def unsubscribe(self, tokens: Iterable[int]) -> None:
        drop = set(tokens)
        with self._lock:
            self._want = [t for t in self._want if t not in drop]
        self._schedule(self._resubscribe())

    def set_mode(self, mode: str, tokens: Iterable[int]) -> None:
        """TrueData has one mode: every tick carries OI and the top of book."""

    def close(self, code: Any = None, reason: Any = None) -> None:
        self._stop = True
        self._schedule(self._logout())

    # plumbing
    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:  # noqa: BLE001 — reported to the feed as a close, never raised on the thread
            self._emit(self.on_error, 0, type(e).__name__)
            self._emit(self.on_close, 1006, type(e).__name__)
        finally:
            self._loop.close()
            self._loop = None

    def _schedule(self, coro) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        if threading.current_thread() is self._thread:
            loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    def _emit(self, cb, *args) -> None:
        if cb is None:
            return
        try:
            cb(self, *args)
        except Exception as e:  # noqa: BLE001 — a failing callback must not kill the ticker thread
            logger.debug("truedata ticker callback failed: %s", type(e).__name__)

    async def _send(self, payload: dict) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps(payload))

    async def _logout(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"method": "logout"}))
            await ws.close()
        except Exception as e:  # noqa: BLE001
            logger.debug("truedata ticker logout: %s", type(e).__name__)

    async def _resubscribe(self) -> None:
        """Subscribe the first `maxsymbols` wanted tokens; send only the difference (TS-7)."""
        if self._ws is None or self.login is None:
            return
        names = self._names()
        with self._lock:
            want = [t for t in self._want if t in names]
        limit = self.login.maxsymbols or len(want)
        keep, extra = want[:limit], want[limit:]
        add = [t for t in keep if t not in self._subscribed]
        drop = [t for t in self._subscribed if t not in keep]
        self._subscribed = keep
        self.over_limit = [names[t] for t in extra]
        if drop:
            await self._send({"method": "removesymbol", "symbols": [names[t] for t in drop if t in names]})
        for i in range(0, len(add), 50):
            await self._send({"method": "addsymbol", "symbols": [names[t] for t in add[i:i + 50]]})

    async def _main(self) -> None:
        async with self._connect(self._creds) as ws:
            info = None
            while info is None:                                  # heartbeats can come before the login reply
                raw = await asyncio.wait_for(ws.recv(), timeout=self._login_timeout)
                msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                if pr.kind_of(msg) == "heartbeat":
                    continue
                info = pr.parse_login(msg)
            self.login = info
            if self._dq is not None:
                self._dq.on_login(info, self._clock())
            if not info.ok:
                # TS-8: a refused login is an auth failure for the feed (it reports and backs off); a duplicate login
                # ("already connected") is the same: retrying at once would only knock the other session off.
                self._emit(self.on_error, 403, "truedata login refused")
                self._emit(self.on_close, 1006, "truedata login refused (token)")
                return
            self._ws = ws
            self._emit(self.on_connect, {"login": info.public()})
            await self._resubscribe()
            while not self._stop:
                raw = await ws.recv()
                self._handle(raw, self._clock())
        self._ws = None
        self._emit(self.on_close, 1000, "closed")

    def _handle(self, raw: Any, now: datetime) -> None:
        if self._dq is not None:
            self._dq.on_message(raw, now)
        try:
            msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except ValueError:
            return
        kind = pr.kind_of(msg)
        ticks: List[dict] = []
        try:
            if kind == "heartbeat":
                self._emit(self.on_ticks, [])                    # a heartbeat counts as liveness for the feed
                return
            if kind == "touchline":
                by_name = {v: k for k, v in self._names().items()}
                for row in pr.parse_touchline(msg):
                    token = by_name.get(str(row.get("symbol") or "").upper())
                    if token is None:
                        continue
                    self._id_token[str(row["symbol_id"])] = token
                    t = kite_tick(token, row)
                    if t:
                        ticks.append(t)
            elif kind == "trade":
                row = pr.parse_trade(msg)
                token = self._id_token.get(str(row.get("symbol_id")))
                t = kite_tick(token, row) if token is not None else None
                if t:
                    ticks.append(t)
            elif kind == "bidask":
                row = pr.parse_bidask(msg)
                token = self._id_token.get(str(row.get("symbol_id")))
                last = self._last.get(token) if token is not None else None
                if last is not None:
                    t = dict(last)
                    t["depth"] = _depth(row.get("bid"), row.get("bid_qty"), row.get("ask"), row.get("ask_qty"))
                    ticks.append(t)
        except pr.Malformed as e:
            logger.debug("truedata ticker: malformed %s (%s)", kind, e)
            return
        for t in ticks:
            self._last[t["instrument_token"]] = t
        if ticks:
            self._emit(self.on_ticks, ticks)
