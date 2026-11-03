"""Intraday candle values for the realtime scan dashboard (docs/scan_builder/DESIGN.md §8): the 15-minute and 1-hour
conditions of the Chartink-style widgets, computed on today's Kite candles.

    await intraday_values(symbols, "15minute" | "60minute", needs, lookback_days=N) -> IntradayResult

`needs` are (key, measure, params, offset) tuples, e.g. ("ema21", "ema", {"source": "close", "period": 21}, 0). Offset 0 is the
latest candle (the one in progress during the session), 1 the one before. Measures: open, high, low, close, volume, ema / sma
(source, period), rsi (period), adx / di_plus / di_minus (period), supertrend (period, multiplier), first_high (the high of the
latest session's FIRST candle; offset ignored) and close_in_range ((close − low) ÷ (high − low) × 100 of the candle at the offset;
missing when high = low). Every indicator is services/scan_builder/indicators.py on right-aligned (K, N) arrays, so the daily
engine and this module share one definition. Wilder indicators need history: for ADX(14) on 1-hour candles ask for ≥ 20 sessions
(7 candles a session; the seed's weight after 140 candles is < 0.03 %).

Where the candles come from: Kite historical_data with the platform token, through the app's own reader
(services/kite_live_feed/intraday.py IntradayService.bars: instrument tokens, candle validation, session trimming; raw prices, not
split/bonus adjusted). During the session the live price (the live quote cache) is folded into the candle still in progress
(close, and high/low when exceeded), as the chart does; no candle is ever made from a price alone. The day's Kite login is stored
in Mongo and only the live feed's leader refreshes its own copy, so each worker reloads it (platform_token.refresh_cache) at most
every TOKEN_REFRESH_S, and at once after Kite calls the token expired.

Never in the way of the 10-second refresh: an answer comes from cache at once and stale symbols are refreshed in the background
(first call with nothing cached waits up to FIRST_WAIT_S for whatever arrives; the rest are listed in `missing` with a "loading"
warning). Freshness during the session: 15-minute candles ≤ 60 s old, 1-hour ≤ 300 s; outside it they are re-read once after the
close, then kept (the latest candles are the last session's, which `as_of` and a warning say).

Across the 4 uvicorn workers (Redis, the live quote cache's server):
  nivesh:sb:intraday:bars:<interval>:<sessions>:<SYMBOL>   the candles + fetch time (JSON), read by every worker
  nivesh:sb:intraday:claim:<interval>:<sessions>:<SYMBOL>  SET NX for CLAIM_S: one worker fetches a symbol per cycle
  nivesh:sb:intraday:next_call_at                          one spacing gate (Lua): this feature's Kite historical calls start
                                                           ≥ SPACING_S apart across ALL workers (≤ 1.5 calls/s; Kite allows ~3/s
                                                           per key and the chart and F&O screens share it)
Without Redis each worker keeps its own copy and spaces its calls LOCAL_SPACING_S apart (the same total for four workers).
When the symbols asked for need more calls than the budget allows, refreshes simply take longer; `warnings` says how old the
oldest candles in the answer are.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from services.kite_live_feed import config as cfg
from services.kite_live_feed import gateway as gw
from services.kite_live_feed.intraday import merge_live

from . import indicators as I

logger = logging.getLogger(__name__)

Need = Tuple[str, str, Dict[str, Any], int]

# our interval name -> (the app reader's interval key, minutes per candle)
INTERVALS: Dict[str, Tuple[str, int]] = {"15minute": ("15m", 15), "60minute": ("60m", 60)}
INTERVAL_LABEL = {"15minute": "15-minute", "60minute": "1-hour"}
FRESH_OPEN_S: Dict[str, float] = {"15minute": 60.0, "60minute": 300.0}
CLOSED_MAX_AGE_S = 6 * 3600.0
AFTER_CLOSE_SETTLE_S = 120.0          # candles read in the 2 minutes after 15:30 may still lack the last one
SPACING_S = 1 / 1.5                   # this feature's Kite historical calls, all workers together
LOCAL_SPACING_S = SPACING_S * 4       # no Redis: each of the 4 workers paces itself
CLAIM_S = 20
FIRST_WAIT_S = 3.0
INTERVAL_RANK = {"15minute": 0, "60minute": 1}     # read order among equally overdue candles
TOKEN_REFRESH_S = 300.0               # reload the day's stored Kite login into this worker at most this often
CACHE_TTL_S = 2 * 86400
LIVE_QUOTE_MAX_AGE_S = 120.0
MAX_LOOKBACK = 30                     # the app reader's own cap (MAX_SESSIONS)
PREFIX = "nivesh:sb:intraday:"
SOURCE = ("Kite intraday candles (raw prices, not split/bonus adjusted); during the session the live price is merged into the "
          "candle still in progress")

_PRICE = ("open", "high", "low", "close", "volume")
MEASURES = set(_PRICE) | {"ema", "sma", "rsi", "adx", "di_plus", "di_minus", "supertrend", "first_high", "close_in_range"}


@dataclass
class IntradayResult:
    values: Dict[str, Dict[str, Optional[float]]]
    as_of: Optional[str]                  # IST start time of the latest candle used
    source: str
    warnings: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


@dataclass
class Entry:
    fetched_at: float                     # wall clock (epoch seconds) of the Kite read
    bars: List[list]                      # [iso IST start, open, high, low, close, volume], oldest first
    availability: str = "ok"              # ok | no_bars | symbol_not_found


def _encode(e: Entry) -> str:
    return json.dumps({"t": e.fetched_at, "a": e.availability, "b": e.bars}, separators=(",", ":"))


def _decode(raw: Optional[str]) -> Optional[Entry]:
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return Entry(fetched_at=float(d["t"]), bars=[list(b) for b in d.get("b") or []], availability=str(d.get("a") or "ok"))
    except (TypeError, ValueError, KeyError):
        return None


def _ckey(interval: str, sessions: int, symbol: str) -> str:
    return f"{interval}:{sessions}:{symbol}"


def in_session(now: datetime) -> bool:
    """09:15–15:30 IST on a weekday (a holiday shows as no new candles)."""
    t = now.astimezone(cfg.IST)
    return t.weekday() < 5 and cfg.OPEN <= t.time() <= cfg.CLOSE


# ── shared store: Redis across workers, or this process alone ───────────────────────────────────────────────────────────

_RESERVE_LUA = """
local t = tonumber(redis.call('GET', KEYS[1]) or '0') or 0
local now = tonumber(ARGV[1])
if t < now then t = now end
redis.call('SET', KEYS[1], string.format('%.6f', t + tonumber(ARGV[2])), 'EX', tonumber(ARGV[3]))
return string.format('%.6f', t)
"""


class LocalStore:
    """In-process stand-in with the same interface (tests share one between simulated workers)."""

    def __init__(self, wall: Callable[[], float] = time.time):
        self._kv: Dict[str, Tuple[str, float]] = {}
        self._wall = wall

    def _live(self, key: str) -> Optional[str]:
        v = self._kv.get(key)
        if v is not None and v[1] > self._wall():
            return v[0]
        self._kv.pop(key, None)
        return None

    async def get_many(self, keys: Sequence[str]) -> Dict[str, str]:
        out = {}
        for k in keys:
            v = self._live(k)
            if v is not None:
                out[k] = v
        return out

    async def put(self, key: str, value: str, ex: float) -> None:
        self._kv[key] = (value, self._wall() + ex)

    async def claim(self, key: str, ex: float) -> bool:
        if self._live(key) is not None:
            return False
        self._kv[key] = ("1", self._wall() + ex)
        return True

    async def reserve(self, key: str, now: float, spacing: float, ex: float) -> Optional[float]:
        t = max(float(self._live(key) or 0.0), now)
        self._kv[key] = (repr(t + spacing), now + ex)
        return t


async def _redis_client():
    from services import redis_client
    return await redis_client.get_client()


class RedisStore:
    """The workers' shared store. A Redis failure never raises: reads answer nothing (each worker keeps its own copy), a
    claim falls back to this process, and the spacing gate answers None (the caller then paces this worker alone). A breaker
    skips Redis for a while after a failure."""

    def __init__(self, getter: Callable[[], Awaitable[Any]] = _redis_client):
        self._getter = getter
        self._down_until = 0.0
        self._fails = 0
        self._warned = -math.inf
        self._local = LocalStore()           # claims only, while Redis is away

    async def _c(self):
        if time.monotonic() < self._down_until:
            return None
        try:
            c = await asyncio.wait_for(self._getter(), 4.0)
        except Exception as e:  # noqa: BLE001 — absent, not fatal
            self._fail("connect", e)
            return None
        if c is None:
            self._down_until = time.monotonic() + 60.0
        return c

    def _fail(self, what: str, e: BaseException) -> None:
        self._fails += 1
        now = time.monotonic()
        self._down_until = now + min(60.0, 2.0 ** min(self._fails, 6))
        if now - self._warned >= 60.0:
            self._warned = now
            logger.warning("scan dashboard intraday: redis %s failed (%s); this worker works alone for a while", what, type(e).__name__)

    def _ok(self) -> None:
        self._fails = 0

    async def get_many(self, keys: Sequence[str]) -> Dict[str, str]:
        c = await self._c()
        if c is None or not keys:
            return {}
        try:
            vals = await asyncio.wait_for(c.mget(list(keys)), 2.0)
        except Exception as e:  # noqa: BLE001
            self._fail("read", e)
            return {}
        self._ok()
        return {k: v for k, v in zip(keys, vals) if v is not None}

    async def put(self, key: str, value: str, ex: float) -> None:
        c = await self._c()
        if c is None:
            return
        try:
            await asyncio.wait_for(c.set(key, value, ex=int(ex)), 2.0)
            self._ok()
        except Exception as e:  # noqa: BLE001
            self._fail("write", e)

    async def claim(self, key: str, ex: float) -> bool:
        c = await self._c()
        if c is None:
            return await self._local.claim(key, ex)
        try:
            got = bool(await asyncio.wait_for(c.set(key, "1", nx=True, ex=int(ex)), 2.0))
            self._ok()
            return got
        except Exception as e:  # noqa: BLE001
            self._fail("claim", e)
            return await self._local.claim(key, ex)

    async def reserve(self, key: str, now: float, spacing: float, ex: float) -> Optional[float]:
        c = await self._c()
        if c is None:
            return None
        try:
            t = float(await asyncio.wait_for(c.eval(_RESERVE_LUA, 1, key, "%.6f" % now, "%.6f" % spacing, int(ex)), 2.0))
            self._ok()
            return t
        except Exception as e:  # noqa: BLE001
            self._fail("reserve", e)
            return None


# ── Kite reads ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class KiteFetcher:
    """The app's own intraday reader (platform token, instrument tokens, candle checks). Its 60-second cache is skipped:
    freshness is decided here, across workers."""

    def __init__(self) -> None:
        from services.kite_live_feed.intraday import MAX_SESSIONS, IntradayService
        self._svc = IntradayService()
        self._max = MAX_SESSIONS

    async def bars(self, symbol: str, interval_key: str, sessions: int) -> Dict[str, Any]:
        n = max(1, min(self._max, int(sessions)))
        self._svc._cache.pop((gw.canon(symbol), interval_key, n), None)
        return await self._svc.bars(symbol, interval_key, n, session_open=False)


async def _refresh_platform_token() -> None:
    """Load the day's stored platform Kite login into this worker, as routes/research_chart_intraday.py and the F&O board do:
    only the live feed's leader refreshes its own copy, so another worker keeps a token Kite has since refused."""
    from deps import db
    from services.kite_live_feed import platform_token
    await platform_token.refresh_cache(db)


async def _live_ltps(symbols: Sequence[str]) -> Dict[str, float]:
    """The live quote cache's last prices, only those received in the last LIVE_QUOTE_MAX_AGE_S."""
    from services.kite_live_feed import quote_cache as qc
    rows = await qc.read_quotes(list(symbols))
    out: Dict[str, float] = {}
    now = datetime.now(timezone.utc)
    for s, row in (rows or {}).items():
        try:
            ltp = float(row.get("ltp"))
            at = datetime.fromisoformat(str(row.get("received_at")))
        except (TypeError, ValueError):
            continue
        if ltp > 0 and at.tzinfo is not None and 0 <= (now - at).total_seconds() <= LIVE_QUOTE_MAX_AGE_S:
            out[s] = ltp
    return out


# ── values ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def check_needs(needs: Sequence[Need]) -> None:
    for n in needs:
        if not (isinstance(n, (tuple, list)) and len(n) == 4):
            raise ValueError(f"a need is (key, measure, params, offset), got {n!r}")
        key, measure, params, offset = n
        if measure not in MEASURES:
            raise ValueError(f"unknown intraday measure {measure!r}")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError(f"offset must be a whole number >= 0 for {key!r}")
        if params is not None and not isinstance(params, dict):
            raise ValueError(f"params must be a dict for {key!r}")


def _matrix(per_symbol: List[List[list]]) -> Tuple[Dict[str, np.ndarray], int]:
    """Right-aligned (K, N) open/high/low/close/volume arrays (row K-1 = each stock's latest candle; NaN above its first)."""
    k = max((len(b) for b in per_symbol), default=0)
    n = len(per_symbol)
    arrs = {f: np.full((k, n), np.nan) for f in _PRICE}
    for j, bars in enumerate(per_symbol):
        if not bars:
            continue
        m = np.asarray([b[1:6] for b in bars], dtype=float)
        for i, f in enumerate(_PRICE):
            arrs[f][k - len(bars):, j] = m[:, i]
    return arrs, k


def _series(measure: str, params: Dict[str, Any], a: Dict[str, np.ndarray]) -> np.ndarray:
    p = params or {}
    if measure in _PRICE:
        return a[measure]
    if measure in ("ema", "sma"):
        src = a[str(p.get("source") or "close")]
        n = int(p.get("period", 20))
        return I.ema(src, n) if measure == "ema" else I.sma(src, n)
    if measure == "rsi":
        return I.rsi(a["close"], int(p.get("period", 14)))
    if measure in ("adx", "di_plus", "di_minus"):
        dip, dim, adx = I.dmi(a["high"], a["low"], a["close"], int(p.get("period", 14)))
        return {"adx": adx, "di_plus": dip, "di_minus": dim}[measure]
    if measure == "supertrend":
        return I.supertrend(a["high"], a["low"], a["close"], int(p.get("period", 7)), float(p.get("multiplier", 3)))
    if measure == "close_in_range":
        rng = a["high"] - a["low"]
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(rng > 0, (a["close"] - a["low"]) / rng * 100.0, np.nan)
    raise ValueError(f"unknown intraday measure {measure!r}")


def compute(bars_by_symbol: Dict[str, List[list]], needs: Sequence[Need]) -> Dict[str, Dict[str, Optional[float]]]:
    """Each symbol's need values from its candles (oldest first). Pure: the tests compare it with indicators.py directly."""
    syms = list(bars_by_symbol)
    arrs, k = _matrix([bars_by_symbol[s] for s in syms])
    out: Dict[str, Dict[str, Optional[float]]] = {s: {} for s in syms}
    memo: Dict[Tuple[str, str], np.ndarray] = {}
    for key, measure, params, offset in needs:
        if measure == "first_high":
            for s in syms:
                b = bars_by_symbol[s]
                day = b[-1][0][:10] if b else None
                first = next((x for x in b if x[0][:10] == day), None) if day else None
                out[s][key] = float(first[2]) if first else None
            continue
        mk = (measure, json.dumps(params or {}, sort_keys=True))
        if mk not in memo:
            memo[mk] = _series(measure, params or {}, arrs)
        ser = memo[mk]
        row = k - 1 - int(offset)
        for j, s in enumerate(syms):
            v = ser[row, j] if 0 <= row < k else np.nan
            out[s][key] = float(v) if np.isfinite(v) else None
    return out


class IntradayValues:
    """One per worker (get_service). Everything injectable for the tests."""

    def __init__(self, *, fetcher: Any = None, store: Any = None, wall: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 token_getter: Optional[Callable[[], str]] = None,
                 live_quotes: Optional[Callable[[Sequence[str]], Awaitable[Dict[str, float]]]] = None,
                 token_refresher: Optional[Callable[[], Awaitable[Any]]] = None,
                 first_wait_s: float = FIRST_WAIT_S):
        self._fetcher = fetcher
        self._store = store if store is not None else RedisStore()
        self._wall, self._sleep, self._now = wall, sleep, now
        self._token_getter = token_getter or cfg.get_token
        self._live_quotes = live_quotes or _live_ltps
        self._token_refresher = token_refresher or _refresh_platform_token
        self._token_refreshed_at = -math.inf
        self._first_wait = first_wait_s
        self._local: Dict[str, Entry] = {}
        self._pending: Dict[str, Tuple[float, str, str, int]] = {}
        self._task: Optional[asyncio.Task] = None
        self._last_local_call = -math.inf
        self.calls = 0                          # Kite historical reads this worker made (diagnostics, tests)
        self.problems: Dict[str, int] = {}      # reason -> count since the last answer

    def _get_fetcher(self):
        if self._fetcher is None:
            self._fetcher = KiteFetcher()
        return self._fetcher

    async def _maybe_refresh_token(self) -> None:
        """The day's login into this worker, at most every TOKEN_REFRESH_S (sooner after Kite called the token expired)."""
        if self._wall() - self._token_refreshed_at < TOKEN_REFRESH_S:
            return
        self._token_refreshed_at = self._wall()
        try:
            await asyncio.wait_for(self._token_refresher(), 3.0)
        except Exception as e:  # noqa: BLE001 — the worker keeps the token it held; Kite's answer will say if that fails
            logger.warning("scan dashboard intraday: the platform token could not be reloaded (%s)", type(e).__name__)

    def _stale(self, e: Optional[Entry], interval: str, now: datetime, wall: float) -> bool:
        if e is None:
            return True
        age = wall - e.fetched_at
        if in_session(now):
            return age > FRESH_OPEN_S[interval]
        if e.fetched_at < cfg.last_close(now).timestamp() + AFTER_CLOSE_SETTLE_S:
            return True                         # read before the last close settled: its last candles may be missing
        return age > CLOSED_MAX_AGE_S

    async def _sync_from_store(self, keys: Sequence[str]) -> None:
        """Take a newer copy another worker wrote."""
        if not keys:
            return
        got = await self._store.get_many([PREFIX + "bars:" + k for k in keys])
        for k in keys:
            e = _decode(got.get(PREFIX + "bars:" + k))
            mine = self._local.get(k)
            if e is not None and (mine is None or e.fetched_at > mine.fetched_at):
                self._local[k] = e

    def _schedule(self, items: Sequence[Tuple[str, str, str, int]]) -> None:
        for k, sym, interval, sessions in items:
            e = self._local.get(k)
            deadline = e.fetched_at + FRESH_OPEN_S[interval] if e else 0.0
            if k not in self._pending or deadline < self._pending[k][0]:
                self._pending[k] = (deadline, sym, interval, sessions)
        if self._pending and (self._task is None or self._task.done()):
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while self._pending:
            # The most overdue first; among equals (every never-read candle is due at 0) 15-minute before 1-hour, so the few
            # 15-minute reads a widget needs are not held up by the 218-stock 1-hour backlog after a restart.
            k = min(self._pending, key=lambda x: (self._pending[x][0], INTERVAL_RANK.get(self._pending[x][2], 9)))
            _, sym, interval, sessions = self._pending.pop(k)
            try:
                await self._refresh_one(k, sym, interval, sessions)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — one symbol failing never stops the others
                self.problems["error"] = self.problems.get("error", 0) + 1
                logger.warning("scan dashboard intraday: refresh of %s %s failed (%s)", sym, interval, type(e).__name__)

    async def _pace(self) -> None:
        slot = await self._store.reserve(PREFIX + "next_call_at", self._wall(), SPACING_S, 60)
        if slot is None:
            slot = max(self._wall(), self._last_local_call + LOCAL_SPACING_S)
            self._last_local_call = slot
        wait = slot - self._wall()
        if wait > 0:
            await self._sleep(wait)

    async def _refresh_one(self, k: str, sym: str, interval: str, sessions: int) -> None:
        await self._sync_from_store([k])
        if not self._stale(self._local.get(k), interval, self._now(), self._wall()):
            return                              # another worker refreshed it meanwhile
        if not await self._store.claim(PREFIX + "claim:" + k, CLAIM_S):
            return                              # another worker is reading it now
        await self._pace()
        self.calls += 1
        try:
            raw = await self._get_fetcher().bars(sym, INTERVALS[interval][0], sessions)
        except Exception as e:  # noqa: BLE001 — Kite refused or failed: keep the last candles, retry next cycle
            self.problems["upstream_unavailable"] = self.problems.get("upstream_unavailable", 0) + 1
            logger.warning("scan dashboard intraday: kite read for %s failed (%s)", sym, type(e).__name__)
            return
        availability = str(raw.get("availability") or "ok")
        if availability in ("token_missing", "token_expired"):
            self.problems[availability] = self.problems.get(availability, 0) + 1
            self._token_refreshed_at = -math.inf    # reload the stored login on the next answer
            return                              # never replace good candles with an empty answer
        entry = Entry(fetched_at=self._wall(), bars=[list(b) for b in raw.get("bars") or []], availability=availability)
        self._local[k] = entry
        await self._store.put(PREFIX + "bars:" + k, _encode(entry), CACHE_TTL_S)

    async def values(self, symbols: Sequence[str], interval: str, needs: Sequence[Need], *, lookback_days: int,
                     live_prices: Optional[Dict[str, float]] = None) -> IntradayResult:
        if interval not in INTERVALS:
            raise ValueError(f"interval must be one of {', '.join(INTERVALS)}")
        check_needs(needs)
        syms = list(dict.fromkeys(gw.canon(s) for s in symbols if s))
        sessions = max(1, min(MAX_LOOKBACK, int(lookback_days)))
        now, wall = self._now(), self._wall()
        open_now = in_session(now)
        keys = {s: _ckey(interval, sessions, s) for s in syms}
        label = INTERVAL_LABEL[interval]
        warnings: List[str] = []

        await self._sync_from_store([keys[s] for s in syms if self._stale(self._local.get(keys[s]), interval, now, wall)])
        stale = [s for s in syms if self._stale(self._local.get(keys[s]), interval, now, wall)]
        await self._maybe_refresh_token()
        token = ""
        try:
            token = self._token_getter() or ""
        except Exception as e:  # noqa: BLE001 — treated as not logged in
            logger.warning("scan dashboard intraday: token read failed (%s)", type(e).__name__)
        if stale and token:
            self._schedule([(keys[s], s, interval, sessions) for s in stale])
            if self._task is not None and all(self._local.get(keys[s]) is None for s in syms):
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), self._first_wait)
                except asyncio.TimeoutError:
                    pass
        elif stale:
            warnings.append(f"No Kite login: {label} candles cannot be refreshed"
                            + ("; the last ones read are used." if any(self._local.get(keys[s]) for s in syms) else "."))
        for reason, n in sorted(self.problems.items()):
            if reason in ("token_missing", "token_expired"):
                warnings.append(f"No Kite login ({'expired' if reason == 'token_expired' else 'missing'}): {n} {label} read(s) refused.")
            elif reason == "upstream_unavailable":
                warnings.append(f"Kite did not answer {n} {label} read(s); they are retried.")
            else:
                warnings.append(f"{n} {label} refresh(es) failed; they are retried.")
        self.problems.clear()

        have: Dict[str, List[list]] = {}
        missing: List[str] = []
        oldest: Optional[float] = None
        for s in syms:
            e = self._local.get(keys[s])
            if e is None or not e.bars:
                missing.append(s)
                continue
            have[s] = e.bars
            oldest = e.fetched_at if oldest is None else min(oldest, e.fetched_at)
        loading = [s for s in missing if self._local.get(keys[s]) is None]
        if loading:
            warnings.append(f"{len(loading)} of {len(syms)} symbol(s) have no {label} candles yet (loading).")
        empty = [s for s in missing if s not in loading]
        if empty:
            warnings.append(f"Kite has no {label} candles for {len(empty)} symbol(s): {', '.join(empty[:8])}"
                            + ("…" if len(empty) > 8 else "") + ".")
        if open_now and oldest is not None and wall - oldest > 3 * FRESH_OPEN_S[interval]:
            warnings.append(f"Some {label} candles are {int((wall - oldest) // 60)} min old (Kite's call budget is shared).")

        # The live price into the candle still in progress (copies; the cache keeps Kite's candles).
        if open_now and have:
            live = live_prices
            if live is None:
                try:
                    live = await self._live_quotes(list(have))
                except Exception as e:  # noqa: BLE001 — without live prices the candles are as Kite sent them
                    logger.warning("scan dashboard intraday: live quotes unreadable (%s)", type(e).__name__)
                    live = {}
            minutes = INTERVALS[interval][1]
            for s, bars in list(have.items()):
                ltp = (live or {}).get(s)
                if ltp:
                    copy_bars = bars[:-1] + [list(bars[-1])]
                    if merge_live(copy_bars, float(ltp), now.astimezone(cfg.IST), minutes):
                        have[s] = copy_bars

        values = compute(have, needs) if have else {}
        as_of = max((b[-1][0] for b in have.values()), default=None)
        if not open_now and as_of:
            warnings.append(f"Market closed: the latest {label} candles are from {as_of[:10]} (the last session).")
        return IntradayResult(values=values, as_of=as_of, source=SOURCE, warnings=warnings, missing=missing)


_SERVICE: Optional[IntradayValues] = None


def get_service() -> IntradayValues:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = IntradayValues()
    return _SERVICE


async def intraday_values(symbols: Sequence[str], interval: str, needs: Sequence[Need], *, lookback_days: int,
                          live_prices: Optional[Dict[str, float]] = None) -> IntradayResult:
    """See the module docstring. `live_prices` (symbol -> last price) skips reading the live quote cache."""
    return await get_service().values(symbols, interval, needs, lookback_days=lookback_days, live_prices=live_prices)
