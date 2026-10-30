"""Platform-level live quote feed. Read only.

One asyncio task per backend process; ONE process at a time does the work (a Mongo lease, `kite_live_lease`, renewed
every pass). The leader keeps a quote cache fed by Kite's WebSocket (KiteTicker, 'quote' mode) and, when the socket is
unavailable or silent, by REST `quote()` in batches of at most 500 with at least 1.1 s between calls. Every cadence
(KITE_LIVE_FEED_CADENCE_SECONDS, 2-120, default 30) it publishes one consolidated snapshot to Mongo
(`kite_live_snapshot`, TTL 72 h) and to this process. Followers and the API read the snapshot; they never call Kite.

The universe is indices, Nifty 500, F&O underlyings, the near-month futures and, for LIVE_OPTION_UNDERLYINGS (default NIFTY
and BANKNIFTY), the options of the LIVE_OPTION_EXPIRIES nearest expiries within LIVE_OPTION_STRIKES_EACH_SIDE strikes of the
money, re-centred on every universe rebuild. Futures and options are in 'full' mode (open interest and market depth); quotes
keep the top of book (bid/ask and their quantities) when Kite sends depth.

Besides the snapshot, a second task on the leader (`run_cache`, every second) writes the quotes that changed to Redis, one
key per symbol (`quote_cache`), and at each minute of the open session one replay document to `kite_live_minute`.

It runs the market only during the NSE session (holidays from nidp.nse_holidays through the data platform), plus ONE
final snapshot after the close. A missing or expired token is a state ('not_connected' / 'expired'), not a crash: the
token is re-read on every attempt, with exponential backoff. Nothing here places, modifies or cancels an order, and no
token or key is ever logged: only exception class names are.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from . import config as cfg
from . import gateway as gw
from . import platform_token as pt
from . import quote_cache as qc
from . import token_alert as ta
from . import universe as uni

logger = logging.getLogger(__name__)

COL_SNAP, COL_LEASE, COL_WANTED = "kite_live_snapshot", "kite_live_lease", "kite_live_wanted"
# One document per trading day, written when the final snapshot after the close is published: the day's closing Kite
# quotes (cash, indices and the near-month futures), kept for a year so a close outlives the 72 h `latest` snapshot.
COL_CLOSE = "kite_live_close"
CLOSE_TTL_SECONDS = 400 * 24 * 3600
# An intraday series kept from now on, because Kite's own history cannot give it back for expired contracts: every
# INTRADAY_SNAPSHOT_MINUTES of an open session, one document with the near-month futures' and the two main indices' price,
# open interest and volume. Point-in-time by construction (written when seen); 180 days; one document is about 20 KB.
COL_INTRADAY = "kite_live_intraday"
INTRADAY_SNAPSHOT_MINUTES = 5
INTRADAY_TTL_SECONDS = 180 * 24 * 3600
INTRADAY_INDICES = ("NIFTY 50", "NIFTY BANK")
# One document per minute of the open session (`_id` "YYYY-MM-DDTHH:MM" IST, the first write wins), with the compact rows of
# the indices, futures and options on the feed, for replay; kept LIVE_MINUTE_TTL_DAYS (default 90).
COL_MINUTE = "kite_live_minute"
CACHE_FLUSH_SECONDS = 1.0               # Redis writes are batched into at most one pipeline per second
SNAPSHOT_TTL_SECONDS = 72 * 3600
LEASE_NAME, LEASE_TTL_SECONDS = "kite_live_feed", 45
UNIVERSE_REFRESH_SECONDS = 15 * 60
WANTED_TTL_SECONDS = 30 * 60
WANTED_MAX = 1000
BACKOFF_MAX_SECONDS = 300
IDLE_SECONDS = 15
WS_RETRY_SECONDS = 60


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _iso(ts: Any, default: datetime) -> str:
    if isinstance(ts, datetime):
        d = ts if ts.tzinfo else ts.replace(tzinfo=cfg.IST)      # Kite stamps are naive IST
    else:
        d = default
    return d.astimezone(cfg.IST).isoformat()


def _stamp(ts: Any) -> Optional[str]:
    """Kite's own stamp as IST ISO, or None when Kite gave none (never the receive time)."""
    if isinstance(ts, str) and ts:
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    return _iso(ts, datetime.now(timezone.utc)) if isinstance(ts, datetime) else None


def top_of_book(depth: Any) -> Dict[str, Any]:
    """bid/ask and their quantities from depth buy[0]/sell[0]. No depth, an empty level or a zero price gives None, never 0."""
    out: Dict[str, Any] = {"bid": None, "ask": None, "bid_qty": None, "ask_qty": None}
    if not isinstance(depth, dict):
        return out
    for side, price_key, qty_key in (("buy", "bid", "bid_qty"), ("sell", "ask", "ask_qty")):
        levels = depth.get(side)
        if not isinstance(levels, list) or not levels or not isinstance(levels[0], dict):
            continue
        price = _num(levels[0].get("price"))
        if price is None or price <= 0:
            continue
        qty = _num(levels[0].get("quantity"))
        out[price_key], out[qty_key] = price, (int(qty) if qty is not None and qty > 0 else None)
    return out


def make_quote(symbol: str, last: Any, ohlc: Optional[dict], volume: Any, oi: Any, ts: Any, now: datetime,
               depth: Any = None) -> Optional[dict]:
    """One normalised quote. ltp is None when Kite gave none (never 0); the change is last minus previous close.
    `ts` is Kite's stamp, else the receive time; `exchange_ts` is Kite's stamp only (None without one); `received_at` is when
    the feed got it; bid/ask come from the depth when Kite sent one."""
    ltp = _num(last)
    if ltp is None or ltp <= 0:
        return None
    o = ohlc or {}
    close = _num(o.get("close"))
    close = close if close and close > 0 else None
    change = round(ltp - close, 4) if close is not None else None
    return {"symbol": symbol, "ltp": ltp, "change": change,
            "change_pct": round(change / close * 100.0, 4) if change is not None else None,
            "open": _num(o.get("open")), "high": _num(o.get("high")), "low": _num(o.get("low")), "close": close,
            "volume": _num(volume), "oi": _num(oi) or None, "ts": _iso(ts, now), **top_of_book(depth),
            "exchange_ts": _stamp(ts), "received_at": now.astimezone(cfg.IST).isoformat(timespec="milliseconds")}


def backoff_seconds(fails: int, cadence: int) -> int:
    return int(min(BACKOFF_MAX_SECONDS, cadence * (2 ** max(1, fails))))


async def try_acquire_lease(coll, name: str, holder: str, now: datetime, ttl_seconds: int) -> bool:
    """Take or renew lease `name`: succeeds when it is ours or expired. One atomic upsert; a rival holding an unexpired
    lease makes the upsert collide on _id, which is "not acquired"."""
    try:
        res = await coll.update_one(
            {"_id": name, "$or": [{"holder": holder}, {"expires_at": {"$lte": now}}]},
            {"$set": {"holder": holder, "expires_at": now + timedelta(seconds=ttl_seconds), "heartbeat_at": now}}, upsert=True)
    except DuplicateKeyError:
        return False
    return bool(res.matched_count or res.upserted_id)


async def ensure_indexes(db) -> None:
    await db[COL_SNAP].create_index("updated_at", expireAfterSeconds=SNAPSHOT_TTL_SECONDS, background=True)
    await db[COL_WANTED].create_index("expires_at", expireAfterSeconds=0, background=True)
    await db[COL_CLOSE].create_index("saved_at", expireAfterSeconds=CLOSE_TTL_SECONDS, background=True)
    await db[COL_INTRADAY].create_index("saved_at", expireAfterSeconds=INTRADAY_TTL_SECONDS, background=True)
    try:
        await db[COL_MINUTE].create_index("saved_at", expireAfterSeconds=cfg.minute_ttl_days() * 86400, background=True)
    except Exception as e:  # noqa: BLE001 — e.g. the TTL setting changed after the index exists (needs collMod); the feed still starts
        logger.warning("live feed: %s TTL index not (re)created (%s)", COL_MINUTE, type(e).__name__)
    await pt.ensure_indexes(db)


def aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


_MESSAGES = {
    "kite": {"no_token": "no Kite access token", "no_key": "no Kite API key",
             "expired": "Kite access token expired; the daily login handshake is needed"},
    "truedata": {"no_token": "no TrueData WebSocket login (TRUEDATA_WS_USERNAME / TRUEDATA_WS_PASSWORD)",
                 "no_key": "no TrueData REST login (TRUEDATA_USERNAME / TRUEDATA_PASSWORD)",
                 "expired": "TrueData refused the WebSocket login (wrong login, expired validity or another connection)"},
}


class LiveFeed:
    def __init__(self, db, *, holder: Optional[str] = None, clock: Optional[Callable[[], datetime]] = None,
                 sleep=asyncio.sleep, cadence: Optional[int] = None, token_getter=cfg.get_token,
                 key_getter=cfg.get_api_key, kite_factory=gw.default_kite_factory,
                 ticker_factory=gw.default_ticker_factory, load_holidays=cfg.load_holidays,
                 load_nifty500=uni.nifty500_symbols, force_rest: Optional[bool] = None, notifier=None,
                 provider: str = "kite"):
        self.db = db
        # "kite" (default) or "truedata" (services/truedata_live/serve.py injects TrueData's client and ticker): with
        # TrueData there is no Kite platform token to refresh and no morning Kite-login alert, and the states say TrueData.
        self.provider = provider
        self.holder = holder or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.cadence = cadence if cadence is not None else cfg.cadence_seconds()
        self._lease_ttl = max(LEASE_TTL_SECONDS, int(2 * self.cadence + 15))     # must outlive the gap between passes
        self.token_getter, self.key_getter = token_getter, key_getter
        self.kite_factory, self.ticker_factory = kite_factory, ticker_factory
        self.load_holidays, self.load_nifty500 = load_holidays, load_nifty500
        self.force_rest = cfg.force_rest() if force_rest is None else force_rest
        import threading
        self._qlock = threading.Lock()
        self.quotes: Dict[str, dict] = {}
        self.token_map: Dict[str, int] = {}
        self.rev: Dict[int, str] = {}
        self.ordered: List[str] = []
        self.sets: Dict[str, List[str]] = {}
        self.unresolved: List[str] = []
        self._indices: List[str] = []
        self._fno: List[str] = []
        self._n500: List[str] = []
        self._last_intraday_bucket: Optional[str] = None
        self._futs: Dict[str, dict] = {}         # near-month futures: tradingsymbol -> {symbol, token, underlying, expiry, lot_size}
        self.option_underlyings = cfg.option_underlyings()
        self.option_expiries, self.option_strikes = cfg.option_expiries(), cfg.option_strikes_each_side()
        self.cache_ttl = cfg.quote_cache_ttl_seconds()
        self._opt_chains: Dict[str, Dict[str, List[dict]]] = {}   # underlying -> expiry -> listed contracts (nearest expiries)
        self._opt_meta: Dict[str, dict] = {}     # tradingsymbol -> contract, for every contract of those chains
        self._opts: List[str] = []               # the window on the feed now (ATM +/- N strikes, CE and PE)
        self._opt_picked: List[dict] = []
        self._opt_missing: List[str] = []        # underlyings left out for want of a spot price (retried every pass)
        self._chains: Dict[tuple, Dict[str, str]] = {}            # (underlying, expiry) -> {"strike|type": "NFO:SYMBOL"}
        self._chain_dirty = False
        self._chain_keys: set = set()            # chain hashes written to Redis (to delete one that left the window)
        self._chain_at = float("-inf")
        self._index_syms: set = set()
        self._dirty: set = set()                 # symbols with a new quote since the last Redis write (guarded by _qlock)
        self._written: Dict[str, float] = {}     # symbol -> epoch seconds of its last Redis write
        self._cache_at = float("-inf")
        self._cache_warned_at = float("-inf")
        self._last_minute: Optional[str] = None
        self._minute_warned: Optional[str] = None
        self._inst_day: Optional[date] = None
        self._universe_at: Optional[datetime] = None
        self._wanted: List[str] = []
        self._requested: Dict[str, float] = {}
        self._kite = None
        self._ticker: Optional[gw.TickerSource] = None
        self._ws_retry_at = 0.0
        self._ws_started = 0.0
        self._fp = ""
        self._expired_fp = ""
        self._fails = 0
        self._next_try: Optional[datetime] = None
        self._cursor = 0
        self._holidays: Dict[date, set] = {}
        self._cache_read: Optional[tuple] = None
        self.leader = False
        self.state, self.message, self.source, self.session, self.reason = "starting", "", None, "closed", ""
        self.holiday_checked = True
        self.data_at: Optional[datetime] = None
        self.snapshot: Optional[dict] = None
        self.alerter = ta.TokenAlerter(db, notifier=notifier or ta.default_notifier)

    # ── ticks from the WebSocket thread ──────────────────────────────────────
    def _on_tick(self, token: int, tick: dict) -> None:
        sym = self.rev.get(token)
        if not sym:
            return
        now = self.clock()
        q = make_quote(sym, tick.get("last_price"), tick.get("ohlc"), tick.get("volume_traded", tick.get("volume")),
                       tick.get("oi"), tick.get("exchange_timestamp") or tick.get("last_trade_time"), now, tick.get("depth"))
        if q:
            self._decorate(sym, q, tick.get("oi_day_high"), tick.get("oi_day_low"), "ws")
            with self._qlock:
                self.quotes[sym] = q
                self._dirty.add(sym)
            self.data_at = now

    def _decorate(self, sym: str, q: dict, oi_high: Any, oi_low: Any, source: str) -> None:
        """Every quote says how it arrived (ws | rest). A futures quote names its underlying, expiry and lot size and carries the
        day's OI range; an option quote names its underlying, expiry, strike, CE/PE and lot size."""
        q["source"] = source
        f = self._futs.get(sym)
        if f:
            q.update({"instrument": "FUT", "underlying": f["underlying"], "expiry": f["expiry"],
                      "oi_high": _num(oi_high) or None, "oi_low": _num(oi_low) or None, "lot_size": f.get("lot_size")})
            return
        o = self._opt_meta.get(sym)
        if o:
            q.update({"instrument": "OPT", "underlying": o["underlying"], "expiry": o["expiry"], "strike": o["strike"],
                      "option_type": o["option_type"], "lot_size": o.get("lot_size")})

    def _qkey(self, sym: str) -> str:
        return ("NFO:" if sym in self._futs or sym in self._opt_meta else "NSE:") + sym

    def _full_tokens(self) -> set:
        return {self.token_map[s] for s in list(self._futs) + list(self._opt_meta) if s in self.token_map}

    def _kind(self, sym: str) -> str:
        if sym in self._futs:
            return "FUT"
        if sym in self._opt_meta:
            return "OPT"
        return "INDEX" if sym in self._index_syms else "EQ"

    # ── pieces ───────────────────────────────────────────────────────────────
    async def _session(self, now: datetime):
        day = now.astimezone(cfg.IST).date()
        hol = self._holidays.get(day)
        checked = True
        if hol is None:
            try:
                hol = await self.load_holidays(day)
                self._holidays = {day: hol}
            except Exception as e:  # noqa: BLE001 — said, not assumed
                logger.warning("live feed: holiday list unavailable (%s)", type(e).__name__)
                hol, checked = set(), False
        s, r = cfg.session_of(now, hol)
        return s, r, checked

    def _set_state(self, state: str, message: str = "") -> None:
        self.state, self.message = state, message

    def _fail(self, exc: Exception, now: datetime) -> None:
        from services.providers.contract import AUTH_EXPIRED, RATE_LIMITED
        from services.providers.kite_adapter import classify
        code = classify(exc)
        logger.warning("live feed: kite call failed: %s (%s)", type(exc).__name__, code)
        self._stop_ticker()
        if code == AUTH_EXPIRED:
            self._expired_fp = self._fp
            self._next_try = now + timedelta(seconds=30)
            self._set_state("expired", _MESSAGES[self.provider]["expired"])
            return
        self._fails += 1
        self._next_try = now + timedelta(seconds=backoff_seconds(self._fails, self.cadence))
        self._set_state("error", "Kite rate limit, retrying" if code == RATE_LIMITED else f"Kite read failed ({code})")

    def _stop_ticker(self) -> None:
        if self._ticker is not None:
            self._ticker.stop()
            self._ticker = None

    async def _load_instruments(self, now: datetime) -> None:
        day = now.astimezone(cfg.IST).date()
        if self._inst_day == day and self.token_map:
            return
        nse = await asyncio.to_thread(self._kite.instruments, "NSE")
        tm: Dict[str, int] = {}
        idx: set = set()
        for r in nse:
            if r.get("segment") == "INDICES" or r.get("instrument_type") == "EQ":
                try:
                    tm[gw.canon(r["tradingsymbol"])] = int(r["instrument_token"])
                except (KeyError, TypeError, ValueError):
                    continue
                if r.get("segment") == "INDICES":
                    idx.add(gw.canon(r["tradingsymbol"]))
        self._indices = uni.index_symbols(nse)
        self._index_syms = idx
        self._futs, self._opt_chains, self._opt_meta = {}, {}, {}
        try:
            nfo = await asyncio.to_thread(self._kite.instruments, "NFO")
            self._fno = uni.fno_underlyings(nfo)
            self._futs = {f["symbol"]: f for f in uni.near_month_futures(nfo, now.astimezone(cfg.IST).date())}
            for s, f in self._futs.items():
                tm[s] = f["token"]
            self._opt_chains = uni.option_contracts(nfo, self.option_underlyings, now.astimezone(cfg.IST).date(),
                                                    self.option_expiries)
            self._opt_meta = {c["symbol"]: c for by_day in self._opt_chains.values() for rows in by_day.values() for c in rows}
            for s, c in self._opt_meta.items():
                tm[s] = c["token"]
        except Exception as e:  # noqa: BLE001 — F&O set is optional; the failure is exposed in status
            if self._classify(e) == "AUTH_EXPIRED":
                raise
            logger.warning("live feed: NFO instruments unavailable (%s)", type(e).__name__)
        self.token_map = tm
        self.rev = {v: k for k, v in tm.items()}
        self._inst_day = day
        self._universe_at = None

    @staticmethod
    def _classify(e: Exception) -> str:
        from services.providers.kite_adapter import classify
        return classify(e)

    async def _refresh_wanted(self, now: datetime) -> bool:
        rows = await self.db[COL_WANTED].find({"expires_at": {"$gt": now}}).to_list(length=WANTED_MAX)
        wanted = sorted(r["_id"] for r in rows)
        changed = wanted != self._wanted
        self._wanted = wanted
        return changed

    def _spot(self, underlying: str) -> Optional[float]:
        """The at-the-money reference: the index quote (NIFTY 50 for NIFTY, NIFTY BANK for BANKNIFTY, the cash quote for a
        stock), else the near-month future's. None when the feed has neither yet."""
        fut = next((s for s, f in self._futs.items() if f["underlying"] == underlying), None)
        with self._qlock:
            q = self.quotes.get(uni.OPTION_SPOT.get(underlying, underlying)) or (self.quotes.get(fut) if fut else None)
        return _num(q.get("ltp")) if q else None

    def _select_options(self) -> None:
        picked, self._opt_missing = uni.select_options(
            self._opt_chains, {u: self._spot(u) for u in self._opt_chains}, self.option_strikes)
        self._opt_picked, self._opts = picked, [c["symbol"] for c in picked]

    def _build_chains(self) -> None:
        """The chain index for the window actually subscribed (an option the cap dropped is not listed)."""
        on = set(self.ordered)
        chains: Dict[tuple, Dict[str, str]] = {}
        for c in self._opt_picked:
            if c["symbol"] in on:
                chains.setdefault((c["underlying"], c["expiry"]), {})[qc.strike_field(c["strike"], c["option_type"])] = "NFO:" + c["symbol"]
        if chains != self._chains:
            self._chains, self._chain_dirty = chains, True

    async def _ensure_universe(self, now: datetime, wanted_changed: bool) -> None:
        due = self._universe_at is None or (now - self._universe_at).total_seconds() >= UNIVERSE_REFRESH_SECONDS
        pending = any(self._spot(u) is not None for u in self._opt_missing)    # a spot arrived for options left out
        if not (due or wanted_changed or pending):
            return
        if due:
            try:
                self._n500 = await self.load_nifty500()
            except Exception as e:  # noqa: BLE001 — keep the previous list; the partial universe is reported
                logger.warning("live feed: Nifty 500 list unavailable (%s)", type(e).__name__)
        self._select_options()                                # re-centred on the latest spot at every rebuild
        self.ordered, self.sets, self.unresolved = uni.assemble(
            self._indices, self._wanted, self._n500, self._fno, self.token_map, list(self._futs), self._opts)
        self._build_chains()
        self._universe_at = now if due else self._universe_at
        if self._ticker is not None:
            self._ticker.full_tokens = self._full_tokens()
            self._ticker.set_tokens([self.token_map[s] for s in self.ordered])
        await self.db[COL_SNAP].replace_one(
            {"_id": "universe"}, {"_id": "universe", "sets": self.sets, "updated_at": now}, upsert=True)

    def _priority(self) -> List[str]:
        seen, out = set(), []
        for s in self.sets.get("indices", []) + self.sets.get("wanted", []):
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    async def _rest_cycle(self, now: datetime, full: bool = False) -> int:
        """One round of REST quote() batches; returns symbols read. Prioritises indices + requested symbols, then rotates
        through the rest, as many batches as fit in one cadence (all of them when `full`)."""
        prio = self._priority()
        ps = set(prio)
        rest = [s for s in self.ordered if s not in ps]
        batches_allowed = 10 ** 6 if full else max(1, int((self.cadence - 0.3) / cfg.REST_SPACING_SECONDS))
        room = max(0, batches_allowed * cfg.REST_BATCH - len(prio))
        if rest and not full and room < len(rest):
            k = self._cursor % len(rest)
            take = (rest[k:] + rest[:k])[:room]
            self._cursor = (k + len(take)) % len(rest)
        else:
            take = rest
        todo = prio + take
        read = 0
        for i in range(0, len(todo), cfg.REST_BATCH):
            if i:
                await self.sleep(cfg.REST_SPACING_SECONDS)
            chunk = todo[i:i + cfg.REST_BATCH]
            data = await asyncio.to_thread(self._kite.quote, [self._qkey(s) for s in chunk])
            stamp = self.clock()
            with self._qlock:
                for key, v in (data or {}).items():
                    sym = gw.canon(key)
                    q = make_quote(sym, v.get("last_price"), v.get("ohlc"), v.get("volume"), v.get("oi"),
                                   v.get("timestamp"), stamp, v.get("depth"))
                    if q:
                        self._decorate(sym, q, v.get("oi_day_high"), v.get("oi_day_low"), "rest")
                        self.quotes[sym] = q
                        self._dirty.add(sym)
                        read += 1
            self.data_at = stamp
        return read

    def _start_ticker(self, key: str, token: str) -> None:
        self._ticker = gw.TickerSource(key, token, self._on_tick, factory=self.ticker_factory)
        self._ticker.full_tokens = self._full_tokens()
        self._ws_started = time.monotonic()
        self._ticker.start([self.token_map[s] for s in self.ordered])

    # ── snapshot ─────────────────────────────────────────────────────────────
    def _status_doc(self, now: datetime) -> dict:
        return {"state": self.state, "message": self.message, "session": self.session, "reason": self.reason,
                "source": self.source, "instrument_count": len(self.ordered), "unresolved_count": len(self.unresolved),
                "universe": {k: len(v) for k, v in self.sets.items()}, "holiday_checked": self.holiday_checked,
                "data_at": self.data_at.isoformat() if self.data_at else None, "holder": self.holder,
                "cadence_seconds": self.cadence, "token_alert": self.alerter.state(), "provider": self.provider,
                "updated_at": now}

    async def _publish(self, now: datetime, final: bool = False) -> None:
        syms = set(self.ordered)
        with self._qlock:
            items = [q for s, q in self.quotes.items() if s in syms]
        doc = {"_id": "latest", "as_of": now.isoformat(), "data_at": self.data_at.isoformat() if self.data_at else None,
               "session": self.session, "source": self.source, "final": final, "count": len(items),
               "quotes": items, "updated_at": now}
        self.snapshot = {k: v for k, v in doc.items() if k != "_id"}
        try:
            await self.db[COL_SNAP].replace_one({"_id": "latest"}, doc, upsert=True)
        except Exception as e:  # noqa: BLE001 — in-process snapshot still serves; followers see the older one
            logger.warning("live feed: snapshot write failed (%s)", type(e).__name__)
        if final:
            await self._save_close(doc, now)

    async def _save_close(self, snap: dict, now: datetime) -> None:
        """Keep the closing quotes: one document per trading day, replaced if the final read is repeated that day. A failed
        write is logged and never stops the feed (the `latest` snapshot still serves the close)."""
        day = cfg.last_close(now).astimezone(cfg.IST).date().isoformat()
        try:
            await self.db[COL_CLOSE].replace_one(
                {"_id": day}, {**{k: v for k, v in snap.items() if k != "_id"}, "_id": day, "date": day, "saved_at": now}, upsert=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("live feed: closing quotes write failed (%s)", type(e).__name__)

    async def _write_status(self, now: datetime) -> None:
        try:
            await self.db[COL_SNAP].replace_one({"_id": "status"}, {"_id": "status", **self._status_doc(now)}, upsert=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("live feed: status write failed (%s)", type(e).__name__)

    # ── one pass ─────────────────────────────────────────────────────────────
    async def tick(self) -> Dict[str, Any]:
        stats = await self._tick_inner()
        if stats.get("leader") and self.provider == "kite":
            await self._alert_pass()
        return stats

    async def _alert_pass(self) -> None:
        """The morning token alert. Valid = the last Kite call worked (live or market_closed); never raises into the feed."""
        try:
            if self.state in ("starting", "error"):                  # nothing known about the token yet, or a non-auth failure
                return
            out = await self.alerter.run_pass(self.clock(), valid=self.state in ("live", "market_closed"), reason=self.reason)
            if out.get("sent") or out.get("confirmed"):
                await self._write_status(self.clock().astimezone(timezone.utc))
        except Exception as e:  # noqa: BLE001
            logger.warning("live feed: token alert pass failed (%s)", type(e).__name__)

    async def _tick_inner(self) -> Dict[str, Any]:
        now = self.clock().astimezone(timezone.utc)
        stats: Dict[str, Any] = {"leader": False}
        if not await try_acquire_lease(self.db[COL_LEASE], LEASE_NAME, self.holder, now, self._lease_ttl):
            self.leader = False
            self._stop_ticker()
            return stats
        self.leader = stats["leader"] = True
        self.session, self.reason, self.holiday_checked = await self._session(now)
        if self.provider == "kite":
            try:
                await pt.refresh_cache(self.db, now)                # a token stored by the daily login, on any container
            except Exception as e:  # noqa: BLE001
                logger.warning("live feed: platform token cache refresh failed (%s)", type(e).__name__)
        token, key = self.token_getter(), self.key_getter()
        fp = cfg.fingerprint(token)
        if fp != self._fp:                                    # a new (or removed) token: forget the old session and any backoff
            self._stop_ticker()
            self._kite, self._fp, self._expired_fp, self._fails, self._inst_day, self._next_try = None, fp, "", 0, None, None
        if self._next_try is not None and now < self._next_try:
            stats["waiting"] = True
            await self._write_status(now)
            return stats
        if not token or not key:
            self._stop_ticker()
            self._next_try = now + timedelta(seconds=30)
            self._set_state("not_connected", _MESSAGES[self.provider]["no_token" if not token else "no_key"])
            await self._write_status(now)
            return stats
        if self._expired_fp == fp:
            self._next_try = now + timedelta(seconds=30)
            self._set_state("expired", _MESSAGES[self.provider]["expired"])
            await self._write_status(now)
            return stats
        try:
            if self._kite is None:
                self._kite = self.kite_factory(key, token)
            await self._load_instruments(now)
            changed = await self._refresh_wanted(now)
            await self._ensure_universe(now, changed)
            if self.session == "open":
                stats.update(await self._open_cycle(now, key, token))
            else:
                self._stop_ticker()
                self.source = None
                stats.update(await self._closed_cycle(now))
            self._fails, self._next_try = 0, None
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — classified; the loop never dies
            self._fail(e, now)
        await self._write_status(now)
        return stats

    async def _open_cycle(self, now: datetime, key: str, token: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if not self.force_rest and self._ticker is None and time.monotonic() >= self._ws_retry_at and self.ordered:
            try:
                self._start_ticker(key, token)
            except Exception as e:  # noqa: BLE001 — REST carries the feed meanwhile
                logger.warning("live feed: websocket start failed (%s)", type(e).__name__)
                self._ticker, self._ws_retry_at = None, time.monotonic() + WS_RETRY_SECONDS
        if self._ticker is not None and self._ticker.auth_failed:
            raise TokenException("websocket refused the access token")
        if self._ticker is not None and self._ticker.healthy():
            self.source = "ws"
        else:
            self.source = "rest"
            out["rest_read"] = await self._rest_cycle(now)
            if self._ticker is not None and not self._ticker.connected and time.monotonic() - self._ws_started > WS_RETRY_SECONDS:
                self._stop_ticker()                           # restart it next pass
                self._ws_retry_at = time.monotonic() + WS_RETRY_SECONDS
        self._set_state("live", "")
        await self._publish(now)
        await self._save_intraday(now)
        out["published"] = True
        return out

    async def _save_intraday(self, now: datetime) -> None:
        """Keep this INTRADAY_SNAPSHOT_MINUTES bucket's futures and index quotes (price, OI, volume), once per bucket. A failed write is
        logged (the class name only) and retried on the next pass; it never stops the feed."""
        t = now.astimezone(cfg.IST)
        bucket = t.replace(minute=t.minute - t.minute % INTRADAY_SNAPSHOT_MINUTES, second=0, microsecond=0)
        key = bucket.strftime("%Y-%m-%dT%H:%M")
        if key == self._last_intraday_bucket:
            return
        keep = set(self.sets.get("futures", [])) | {s for s in self.sets.get("indices", []) if s in INTRADAY_INDICES}
        with self._qlock:
            items = [q for s, q in self.quotes.items() if s in keep]
        if not items:
            return
        rows = []
        for q in items:
            r = {"s": q["symbol"], "p": q["ltp"], "o": q.get("oi"), "v": q.get("volume"), "c": q.get("close"), "t": q.get("ts")}
            if q.get("instrument") == "FUT":
                r.update({"u": q.get("underlying"), "x": q.get("expiry")})
            rows.append(r)
        doc = {"_id": key, "day": bucket.date().isoformat(), "bucket": key, "as_of": now.isoformat(),
               "data_at": self.data_at.isoformat() if self.data_at else None, "source": self.source, "count": len(rows), "rows": rows, "saved_at": now}
        try:
            await self.db[COL_INTRADAY].replace_one({"_id": key}, doc, upsert=True)
            self._last_intraday_bucket = key
        except Exception as e:  # noqa: BLE001
            logger.warning("live feed: intraday snapshot write failed (%s)", type(e).__name__)

    async def _closed_cycle(self, now: datetime) -> Dict[str, Any]:
        """Idle outside the session, except ONE final snapshot once the last close has passed."""
        lc = cfg.last_close(now)
        have = self.snapshot or await self._read_mongo_latest()
        done = aware(self.data_at) or (self._parse(have.get("data_at")) if have else None)
        if self.snapshot is None and have:
            self.snapshot = have
            for q in have.get("quotes", []):
                self.quotes.setdefault(q["symbol"], q)
        if self.ordered and (done is None or done < lc) and now >= lc + timedelta(seconds=60):
            self.source = "rest"
            n = await self._rest_cycle(now, full=True)
            self._set_state("market_closed", "final snapshot after the close")
            await self._publish(now, final=True)
            return {"final": True, "rest_read": n}
        self._set_state("market_closed", self.reason)
        return {}

    @staticmethod
    def _parse(v: Any) -> Optional[datetime]:
        try:
            return aware(datetime.fromisoformat(str(v)))
        except (TypeError, ValueError):
            return None

    async def _read_mongo_latest(self) -> Optional[dict]:
        return await self.db[COL_SNAP].find_one({"_id": "latest"}, {"_id": 0})

    async def run(self) -> None:
        cache = asyncio.ensure_future(self.run_cache())
        try:
            while True:
                t0 = time.monotonic()
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.warning("live feed tick failed: %s", type(e).__name__)
                period = self.cadence if self.session == "open" and self.state in ("live", "error") else IDLE_SECONDS
                await self.sleep(max(0.2, period - (time.monotonic() - t0)))
        finally:
            cache.cancel()

    # ── Redis quote cache + 1-minute replay snapshots (leader only, every second) ──
    async def run_cache(self) -> None:
        while True:
            try:
                await self.cache_pass()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — the cache never stops the feed
                t = time.monotonic()
                if t - self._cache_warned_at >= 60:
                    self._cache_warned_at = t
                    logger.warning("live quote cache pass failed: %s", type(e).__name__)
            await self.sleep(CACHE_FLUSH_SECONDS)

    async def cache_pass(self) -> Dict[str, Any]:
        if not self.leader:
            with self._qlock:
                self._dirty.clear()
            return {}
        now = self.clock().astimezone(timezone.utc)
        return {"cached": await self._flush_cache(now), "minute": await self._save_minute(now)}

    def _open_now(self, now: datetime) -> bool:
        """Open session per the leader's last pass AND the clock (self.session can lag the 15:30 close by a pass)."""
        hol = self._holidays.get(now.astimezone(cfg.IST).date(), set())
        return self.session == "open" and self.state == "live" and cfg.session_of(now, hol)[0] == "open"

    async def _flush_cache(self, now: datetime) -> int:
        """Quotes that changed since the last write go to Redis in one pipeline, at most once per CACHE_FLUSH_SECONDS. During
        the session a quote not rewritten for half the TTL is rewritten as it is (same received_at), so a quiet contract stays
        cached while the leader lives; when the leader stops, every key expires within the TTL. A failed write keeps the
        symbols pending for the next pass. Returns the number of rows written."""
        t = now.timestamp()
        if t - self._cache_at < CACHE_FLUSH_SECONDS:
            return 0
        self._cache_at = t
        on = set(self.ordered)
        keep_alive = self._open_now(now)
        half = self.cache_ttl / 2.0
        self._written = {s: at for s, at in self._written.items() if s in on}      # forget symbols that left the feed
        with self._qlock:
            dirty, self._dirty = self._dirty, set()
            todo = {s for s in dirty if s in on}
            if keep_alive:
                todo |= {s for s, at in self._written.items() if s in on and t - at >= half}
            items = [self.quotes[s] for s in todo if s in self.quotes]
        chains: Dict[str, Dict[str, str]] = {}
        if self._chain_dirty or (keep_alive and t - self._chain_at >= half):
            chains = {qc.chain_key(u, x): m for (u, x), m in self._chains.items()}
            chains.update({k: {} for k in self._chain_keys - set(chains)})          # a chain that left the window is deleted
        rows = [qc.cache_row(q, self._kind(q["symbol"]), self.session) for q in items]
        if not rows and not chains:
            return 0
        if not await qc.write(rows, chains, self.cache_ttl):
            with self._qlock:
                self._dirty |= dirty
            return 0
        for r in rows:
            self._written[r["symbol"]] = t
        if chains:
            self._chain_keys = {k for k, m in chains.items() if m}
            self._chain_dirty, self._chain_at = False, t
        return len(rows)

    async def _save_minute(self, now: datetime) -> bool:
        """At the first pass of each minute of the open session, one replay document: the compact rows of the indices,
        futures and options on the feed. Inserted, so the first write of a minute wins (another leader's is never replaced).
        A failed write is logged once for that minute (class name only) and retried on the next pass."""
        if not self._open_now(now):
            return False
        t = now.astimezone(cfg.IST)
        key = t.strftime("%Y-%m-%dT%H:%M")
        if key == self._last_minute:
            return False
        keep = set(self.sets.get("indices", [])) | set(self.sets.get("futures", [])) | set(self.sets.get("options", []))
        with self._qlock:
            items = [q for s, q in self.quotes.items() if s in keep]
        if not items:
            return False
        rows = [qc.minute_row(q) for q in items]
        doc = {"_id": key, "day": t.date().isoformat(), "minute": key, "as_of": now.isoformat(),
               "data_at": self.data_at.isoformat() if self.data_at else None, "source": self.source,
               "count": len(rows), "rows": rows, "saved_at": now}
        try:
            await self.db[COL_MINUTE].insert_one(doc)
        except DuplicateKeyError:
            self._last_minute = key                               # another leader wrote this minute first: theirs stays
            return False
        except Exception as e:  # noqa: BLE001
            if self._minute_warned != key:
                self._minute_warned = key
                logger.warning("live feed: minute snapshot write failed (%s)", type(e).__name__)
            return False
        self._last_minute = key
        return True

    # ── reads for the API ────────────────────────────────────────────────────
    async def read_snapshot(self) -> Optional[dict]:
        if self.leader and self.snapshot is not None:
            return self.snapshot
        c = self._cache_read
        if c and time.monotonic() - c[0] < 1.0:
            return c[1]
        doc = await self._read_mongo_latest()
        self._cache_read = (time.monotonic(), doc)
        return doc

    async def read_close(self, day: Optional[str] = None) -> Optional[dict]:
        """The saved closing quotes of one trading day (YYYY-MM-DD), or the newest saved day when none is given."""
        coll = self.db[COL_CLOSE]
        if day is None:
            rows = await coll.find({}, {"date": 1}).to_list(length=500)
            days = sorted(str(r["_id"]) for r in rows if r.get("_id"))
            if not days:
                return None
            day = days[-1]
        return await coll.find_one({"_id": day}, {"_id": 0})

    async def read_status(self) -> Optional[dict]:
        if self.leader:
            return self._status_doc(self.clock())
        return await self.db[COL_SNAP].find_one({"_id": "status"}, {"_id": 0})

    async def read_universe(self) -> Dict[str, List[str]]:
        if self.sets:
            return self.sets
        doc = await self.db[COL_SNAP].find_one({"_id": "universe"}, {"_id": 0})
        return (doc or {}).get("sets", {})

    async def request_symbols(self, symbols: List[str]) -> None:
        """Ask the leader to carry these symbols (kept 30 min). Throttled: a symbol is written at most every 5 min."""
        now_m, now = time.monotonic(), self.clock().astimezone(timezone.utc)
        fresh = [s for s in {gw.canon(x) for x in symbols} if s and now_m - self._requested.get(s, -1e9) > 300]
        if not fresh or len(self._requested) > 5000:
            return
        for s in fresh:
            self._requested[s] = now_m
        try:
            for s in fresh[:WANTED_MAX]:
                await self.db[COL_WANTED].update_one({"_id": s}, {"$set": {"expires_at": now + timedelta(seconds=WANTED_TTL_SECONDS)}}, upsert=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("live feed: wanted write failed (%s)", type(e).__name__)


class TokenException(Exception):
    """The WebSocket was refused for its token. The name matters: providers.kite_adapter.classify() maps it to AUTH_EXPIRED."""


_task: Optional["asyncio.Task[None]"] = None
_feed: Optional[LiveFeed] = None


def get_feed(db=None) -> LiveFeed:
    """The process's feed (created on first use so the API works even when the loop is disabled here)."""
    global _feed
    if _feed is None:
        if db is None:
            from deps import db as _db
            db = _db
        _feed = LiveFeed(db)
    return _feed


async def start(db) -> bool:
    """Create indexes and start the loop in this process. False when disabled (KITE_LIVE_FEED_ENABLED=0). When the
    market-data switch (backend/config/market_data_source.json) resolves to `truedata`, the same feed starts on TrueData's
    WebSocket instead of Kite's (services/truedata_live/serve.py); otherwise a switched-off Kite feed does not start."""
    global _task
    await ensure_indexes(db)
    if not cfg.enabled() or (_task is not None and not _task.done()):
        return False
    from nidp.shared import market_data_source as mds
    if not mds.feed_is_on("kite_live_feed"):
        if mds.resolve().effective == "truedata":                 # TrueData serves: the same feed on TrueData's socket
            from services.truedata_live import serve
            return await serve.start_serving(db)
        logger.info("kite live feed not started: %s", mds.switched_off_message("kite_live_feed"))
        return False
    feed = get_feed(db)
    _task = asyncio.ensure_future(feed.run())
    logger.info("kite live feed started: cadence=%ss", feed.cadence)
    return True


async def stop(db=None) -> None:
    global _task, _feed
    try:
        from services.truedata_live import serve
        await serve.stop_serving()
    except Exception:  # noqa: BLE001
        pass
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except BaseException:  # noqa: BLE001
            pass
    if _feed is not None:
        _feed._stop_ticker()
        if db is not None:
            try:
                await db[COL_LEASE].update_one({"_id": LEASE_NAME, "holder": _feed.holder},
                                               {"$set": {"expires_at": datetime.now(timezone.utc)}})
            except Exception:  # noqa: BLE001
                pass
    _task = _feed = None
