"""Platform-level live quote feed. Read only.

One asyncio task per backend process; ONE process at a time does the work (a Mongo lease, `kite_live_lease`, renewed
every pass). The leader keeps a quote cache fed by Kite's WebSocket (KiteTicker, 'quote' mode) and, when the socket is
unavailable or silent, by REST `quote()` in batches of at most 500 with at least 1.1 s between calls. Every cadence
(KITE_LIVE_FEED_CADENCE_SECONDS, 2-30, default 5) it publishes one consolidated snapshot to Mongo
(`kite_live_snapshot`, TTL 72 h) and to this process. Followers and the API read the snapshot; they never call Kite.

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
from . import universe as uni

logger = logging.getLogger(__name__)

COL_SNAP, COL_LEASE, COL_WANTED = "kite_live_snapshot", "kite_live_lease", "kite_live_wanted"
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


def make_quote(symbol: str, last: Any, ohlc: Optional[dict], volume: Any, oi: Any, ts: Any, now: datetime) -> Optional[dict]:
    """One normalised quote. ltp is None when Kite gave none (never 0); the change is last minus previous close."""
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
            "volume": _num(volume), "oi": _num(oi) or None, "ts": _iso(ts, now)}


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


def aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class LiveFeed:
    def __init__(self, db, *, holder: Optional[str] = None, clock: Optional[Callable[[], datetime]] = None,
                 sleep=asyncio.sleep, cadence: Optional[int] = None, token_getter=cfg.get_token,
                 key_getter=cfg.get_api_key, kite_factory=gw.default_kite_factory,
                 ticker_factory=gw.default_ticker_factory, load_holidays=cfg.load_holidays,
                 load_nifty500=uni.nifty500_symbols, force_rest: Optional[bool] = None):
        self.db = db
        self.holder = holder or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.cadence = cadence if cadence is not None else cfg.cadence_seconds()
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

    # ── ticks from the WebSocket thread ──────────────────────────────────────
    def _on_tick(self, token: int, tick: dict) -> None:
        sym = self.rev.get(token)
        if not sym:
            return
        now = self.clock()
        q = make_quote(sym, tick.get("last_price"), tick.get("ohlc"), tick.get("volume_traded", tick.get("volume")),
                       tick.get("oi"), tick.get("exchange_timestamp") or tick.get("last_trade_time"), now)
        if q:
            with self._qlock:
                self.quotes[sym] = q
            self.data_at = now

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
            self._set_state("expired", "Kite access token expired; the daily login handshake is needed")
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
        for r in nse:
            if r.get("segment") == "INDICES" or r.get("instrument_type") == "EQ":
                try:
                    tm[gw.canon(r["tradingsymbol"])] = int(r["instrument_token"])
                except (KeyError, TypeError, ValueError):
                    continue
        self._indices = uni.index_symbols(nse)
        try:
            nfo = await asyncio.to_thread(self._kite.instruments, "NFO")
            self._fno = uni.fno_underlyings(nfo)
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

    async def _ensure_universe(self, now: datetime, wanted_changed: bool) -> None:
        due = self._universe_at is None or (now - self._universe_at).total_seconds() >= UNIVERSE_REFRESH_SECONDS
        if not (due or wanted_changed):
            return
        if due:
            try:
                self._n500 = await self.load_nifty500()
            except Exception as e:  # noqa: BLE001 — keep the previous list; the partial universe is reported
                logger.warning("live feed: Nifty 500 list unavailable (%s)", type(e).__name__)
        self.ordered, self.sets, self.unresolved = uni.assemble(
            self._indices, self._wanted, self._n500, self._fno, self.token_map)
        self._universe_at = now if due else self._universe_at
        if self._ticker is not None:
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
            data = await asyncio.to_thread(self._kite.quote, ["NSE:" + s for s in chunk])
            stamp = self.clock()
            with self._qlock:
                for key, v in (data or {}).items():
                    sym = gw.canon(key)
                    q = make_quote(sym, v.get("last_price"), v.get("ohlc"), v.get("volume"), v.get("oi"),
                                   v.get("timestamp"), stamp)
                    if q:
                        self.quotes[sym] = q
                        read += 1
            self.data_at = stamp
        return read

    def _start_ticker(self, key: str, token: str) -> None:
        self._ticker = gw.TickerSource(key, token, self._on_tick, factory=self.ticker_factory)
        self._ws_started = time.monotonic()
        self._ticker.start([self.token_map[s] for s in self.ordered])

    # ── snapshot ─────────────────────────────────────────────────────────────
    def _status_doc(self, now: datetime) -> dict:
        return {"state": self.state, "message": self.message, "session": self.session, "reason": self.reason,
                "source": self.source, "instrument_count": len(self.ordered), "unresolved_count": len(self.unresolved),
                "universe": {k: len(v) for k, v in self.sets.items()}, "holiday_checked": self.holiday_checked,
                "data_at": self.data_at.isoformat() if self.data_at else None, "holder": self.holder,
                "cadence_seconds": self.cadence, "updated_at": now}

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

    async def _write_status(self, now: datetime) -> None:
        try:
            await self.db[COL_SNAP].replace_one({"_id": "status"}, {"_id": "status", **self._status_doc(now)}, upsert=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("live feed: status write failed (%s)", type(e).__name__)

    # ── one pass ─────────────────────────────────────────────────────────────
    async def tick(self) -> Dict[str, Any]:
        now = self.clock().astimezone(timezone.utc)
        stats: Dict[str, Any] = {"leader": False}
        if not await try_acquire_lease(self.db[COL_LEASE], LEASE_NAME, self.holder, now, LEASE_TTL_SECONDS):
            self.leader = False
            self._stop_ticker()
            return stats
        self.leader = stats["leader"] = True
        self.session, self.reason, self.holiday_checked = await self._session(now)
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
            self._set_state("not_connected", "no Kite access token" if not token else "no Kite API key")
            await self._write_status(now)
            return stats
        if self._expired_fp == fp:
            self._next_try = now + timedelta(seconds=30)
            self._set_state("expired", "Kite access token expired; the daily login handshake is needed")
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
        out["published"] = True
        return out

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
    """Create indexes and start the loop in this process. False when disabled (KITE_LIVE_FEED_ENABLED=0)."""
    global _task
    await ensure_indexes(db)
    if not cfg.enabled() or (_task is not None and not _task.done()):
        return False
    feed = get_feed(db)
    _task = asyncio.ensure_future(feed.run())
    logger.info("kite live feed started: cadence=%ss", feed.cadence)
    return True


async def stop(db=None) -> None:
    global _task, _feed
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
