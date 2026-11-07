"""Buyer- and seller-initiated trades for the realtime scan dashboard (docs/scan_builder/DESIGN.md §8): the condition
"buyer initiated trades / seller initiated trades > 1" of the "10x volume first 5 min" widget, from TrueData tick history.

    await initiated_counts(symbols) -> TickFlowResult      values[symbol] = {buy_trades, sell_trades, buy_volume, sell_volume}

Source: TrueData `getticks` with best bid/ask (nidp.shared.sources.truedata.TrueDataClient.ticks): about one tick a second, each
with the last price, the quantity traded since the previous tick and the best bid and ask at that moment. A tick is counted as
ONE trade print of its side (the tick carries no trade count of its own); its quantity goes to the same side's volume.

Classification (Lee–Ready), for today's continuous session:
  * skipped: the opening-auction print(s) at or before 09:15:00 (the pre-open call auction has no initiating side), rows with
    volume <= 1 (TrueData's marker rows: their price sits outside the bid/ask of the same second) and rows without a price;
  * last price >= ask → buyer-initiated; <= bid → seller-initiated;
  * strictly inside the spread: above the mid → buyer, below → seller, at the mid → the tick test;
  * no usable bid/ask (missing, zero or crossed) → the tick test;
  * tick test: against the previous COUNTED tick's price — up → buyer, down → seller, unchanged → that tick's side; the
    first counted tick with no side is left unclassified (not in either count).

Never in the way of the dashboard's 10-second refresh: an answer comes from cache at once and stale symbols are refreshed in
the background, incrementally (only ticks after the last one read, carrying the tick-test state). A first call with nothing
cached waits up to FIRST_WAIT_S; symbols still unread are listed in `missing` with a "loading" warning. Freshness: 60 s in
the session; after 15:30 the day's counts are read once more after the close settles, then kept. Outside the session the
counts are the last session's (before 09:15, on weekends).

Across the 4 uvicorn workers (Redis, through services/scan_builder/intraday.py's RedisStore; without Redis each worker works
alone and paces itself LOCAL_SPACING_S apart):
  nivesh:sb:tickflow:state:<SYMBOL>   the day's counts + reading position (JSON), read by every worker
  nivesh:sb:tickflow:claim:<SYMBOL>   SET NX for CLAIM_S: one worker reads a symbol per cycle
  nivesh:sb:tickflow:next_call_at     one spacing gate: this feature's TrueData calls start >= SPACING_S apart across ALL
                                      workers (TrueData documents 1–3 requests/s per account; other jobs share it)
TrueData's own client also keeps 1.1 s between its calls in each process. No credential, token or URL is ever logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dtime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from services.kite_live_feed import config as cfg
from services.kite_live_feed import gateway as gw

from .intraday import RedisStore, in_session

logger = logging.getLogger(__name__)

PREFIX = "nivesh:sb:tickflow:"
FRESH_OPEN_S = 60.0
AFTER_CLOSE_SETTLE_S = 120.0          # ticks read in the 2 minutes after 15:30 may still lack the last ones
SPACING_S = 1.1                       # this feature's TrueData calls, all workers together
LOCAL_SPACING_S = SPACING_S * 4       # no Redis: each of the 4 workers paces itself
CLAIM_S = 30
FIRST_WAIT_S = 3.0
CACHE_TTL_S = 86400
SESSION_OPEN = dtime(9, 15, 0)
SESSION_CLOSE = dtime(15, 30, 0)
SOURCE = ("TrueData tick history with best bid/ask (about one tick a second): each tick counted as one buyer- or "
          "seller-initiated print (Lee–Ready: at or above the ask buyer, at or below the bid seller, inside the spread by the "
          "mid, then the tick test); the opening auction and TrueData's 1-share marker rows are left out")

# TrueData errors after which a symbol is simply retried next cycle (the counts so far are kept).
_RETRY_CODES = {"RATE_LIMITED", "PROVIDER_UNAVAILABLE", "AUTH_EXPIRED", "PROVIDER_ERROR", "INVALID_PAYLOAD"}


@dataclass
class TickFlowResult:
    values: Dict[str, Dict[str, Optional[float]]]
    as_of: Optional[str]                  # IST time of the latest tick counted (ISO)
    source: str
    warnings: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


@dataclass
class FlowState:
    """One symbol's counts for one session day and where reading stopped."""
    day: str                              # session day (IST, YYYY-MM-DD) the counts belong to
    fetched_at: float                     # wall clock (epoch s) of the last TrueData read
    last_ts: Optional[str] = None         # timestamp of the last row read (counted or skipped)
    seen_at_last: int = 0                 # rows with timestamp == last_ts already read (a second can hold several ticks)
    last_counted_ts: Optional[str] = None
    last_ltp: Optional[float] = None      # price of the last COUNTED tick (tick test)
    last_side: int = 0                    # +1 buyer, -1 seller, 0 none: the last counted tick's side
    buy_trades: int = 0
    sell_trades: int = 0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    unclassified: int = 0
    status: str = "ok"                    # ok | empty (TrueData has no ticks for it that day) | unknown (symbol not found)


def _encode(s: FlowState) -> str:
    return json.dumps(asdict(s), separators=(",", ":"))


def _decode(raw: Optional[str]) -> Optional[FlowState]:
    if not raw:
        return None
    try:
        return FlowState(**json.loads(raw))
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def classify(ltp: float, bid: Optional[float], ask: Optional[float], prev_ltp: Optional[float], prev_side: int) -> int:
    """+1 buyer-initiated, -1 seller-initiated, 0 unknown (Lee–Ready; see the module docstring)."""
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        if ltp >= ask:
            return 1
        if ltp <= bid:
            return -1
        mid = (bid + ask) / 2.0
        if ltp > mid:
            return 1
        if ltp < mid:
            return -1
    if prev_ltp is None:
        return 0
    if ltp > prev_ltp:
        return 1
    if ltp < prev_ltp:
        return -1
    return prev_side


def apply_rows(state: FlowState, rows: Sequence[Dict[str, Any]]) -> FlowState:
    """Count `rows` (TrueData ticks in time order; a re-read starts AT state.last_ts) into `state`, in place. The rows of the
    last second already read (state.seen_at_last of them) are skipped, so a second split across two reads counts once."""
    start_ts = state.last_ts
    skip = state.seen_at_last if start_ts is not None else 0
    pos_ts, pos_n = state.last_ts, state.seen_at_last
    auction_end = SESSION_OPEN.strftime("%H:%M:%S")
    for r in rows:
        ts = r.get("timestamp")
        if not isinstance(ts, str) or len(ts) < 19:
            continue
        ts = ts[:19]
        if start_ts is not None and ts < start_ts:
            continue
        if ts == start_ts and skip > 0:
            skip -= 1
            continue
        if ts == pos_ts:
            pos_n += 1
        else:
            pos_ts, pos_n = ts, 1
        ltp, vol = _num(r.get("ltp")), _num(r.get("volume"))
        if ltp is None or ltp <= 0 or vol is None or vol <= 1:
            continue                                            # no price, or TrueData's 1-share marker row
        if ts[11:19] <= auction_end:
            continue                                            # the opening auction print
        side = classify(ltp, _num(r.get("bid")), _num(r.get("ask")), state.last_ltp, state.last_side)
        if side > 0:
            state.buy_trades += 1
            state.buy_volume += vol
        elif side < 0:
            state.sell_trades += 1
            state.sell_volume += vol
        else:
            state.unclassified += 1
        state.last_ltp, state.last_side, state.last_counted_ts = ltp, side, ts
    state.last_ts, state.seen_at_last = pos_ts, pos_n
    return state


def session_day(now: datetime) -> date:
    """The session the counts are for: today while it runs or after today's close, else the last session."""
    t = now.astimezone(cfg.IST)
    if in_session(now) or (t.weekday() < 5 and t.time() > SESSION_CLOSE):
        return t.date()
    return cfg.last_close(now).astimezone(cfg.IST).date()


def _default_client():
    from nidp.shared.sources.truedata import TrueDataClient
    return TrueDataClient()


class TickFlow:
    """One per worker (get_service). Everything injectable for the tests."""

    def __init__(self, *, client: Any = None, store: Any = None, wall: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 run_sync: Optional[Callable[..., Awaitable[Any]]] = None, first_wait_s: float = FIRST_WAIT_S):
        self._client = client
        self._store = store if store is not None else RedisStore()
        self._wall, self._sleep, self._now = wall, sleep, now
        self._run_sync = run_sync or asyncio.to_thread
        self._first_wait = first_wait_s
        self._local: Dict[str, FlowState] = {}
        self._pending: Dict[str, Tuple[float, str]] = {}
        self._task: Optional[asyncio.Task] = None
        self._last_local_call = -math.inf
        self.calls = 0                          # TrueData tick reads this worker made (diagnostics, tests)
        self.rows_read = 0
        self.problems: Dict[str, int] = {}      # reason -> count since the last answer

    def _get_client(self):
        if self._client is None:
            self._client = _default_client()
        return self._client

    def _configured(self) -> bool:
        try:
            return bool(self._get_client().configured)
        except Exception as e:  # noqa: BLE001 — no client, no counts
            logger.warning("scan dashboard tick flow: TrueData client unavailable (%s)", type(e).__name__)
            return False

    def _stale(self, s: Optional[FlowState], day: date, now: datetime, wall: float) -> bool:
        if s is None or s.day != day.isoformat():
            return True
        if in_session(now) and day == now.astimezone(cfg.IST).date():
            return wall - s.fetched_at > FRESH_OPEN_S
        close = datetime.combine(day, SESSION_CLOSE, tzinfo=cfg.IST).timestamp()
        return s.fetched_at < close + AFTER_CLOSE_SETTLE_S        # read before the close settled: read once more

    async def _sync_from_store(self, syms: Sequence[str]) -> None:
        if not syms:
            return
        got = await self._store.get_many([PREFIX + "state:" + s for s in syms])
        for s in syms:
            st = _decode(got.get(PREFIX + "state:" + s))
            mine = self._local.get(s)
            if st is not None and (mine is None or (st.day, st.fetched_at) > (mine.day, mine.fetched_at)):
                self._local[s] = st

    def _schedule(self, syms: Sequence[str]) -> None:
        for s in syms:
            st = self._local.get(s)
            deadline = st.fetched_at + FRESH_OPEN_S if st else 0.0
            if s not in self._pending or deadline < self._pending[s][0]:
                self._pending[s] = (deadline, s)
        if self._pending and (self._task is None or self._task.done()):
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while self._pending:
            k = min(self._pending, key=lambda x: (self._pending[x][0], x))      # the most overdue first
            self._pending.pop(k)
            try:
                await self._refresh_one(k)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — one symbol failing never stops the others
                self.problems["error"] = self.problems.get("error", 0) + 1
                logger.warning("scan dashboard tick flow: refresh of %s failed (%s)", k, type(e).__name__)

    async def _pace(self) -> None:
        slot = await self._store.reserve(PREFIX + "next_call_at", self._wall(), SPACING_S, 60)
        if slot is None:
            slot = max(self._wall(), self._last_local_call + LOCAL_SPACING_S)
            self._last_local_call = slot
        wait = slot - self._wall()
        if wait > 0:
            await self._sleep(wait)

    async def _refresh_one(self, sym: str) -> None:
        now, wall = self._now(), self._wall()
        day = session_day(now)
        await self._sync_from_store([sym])
        if not self._stale(self._local.get(sym), day, now, wall):
            return                              # another worker refreshed it meanwhile
        if not await self._store.claim(PREFIX + "claim:" + sym, CLAIM_S):
            return                              # another worker is reading it now
        prev = self._local.get(sym)
        st = FlowState(**asdict(prev)) if prev is not None and prev.day == day.isoformat() and prev.status == "ok" \
            else FlowState(day=day.isoformat(), fetched_at=0.0)
        start = (datetime.fromisoformat(st.last_ts) if st.last_ts else datetime.combine(day, SESSION_OPEN))
        t_ist = now.astimezone(cfg.IST)
        end = (t_ist.replace(tzinfo=None) if day == t_ist.date() and t_ist.time() < SESSION_CLOSE
               else datetime.combine(day, SESSION_CLOSE))
        await self._pace()
        self.calls += 1
        read_at = self._wall()
        try:
            rows = await self._run_sync(self._get_client().ticks, sym, start, end, True)
        except Exception as e:  # noqa: BLE001 — TrueData's own errors carry a code; nothing secret is in them
            code = getattr(e, "code", None) or type(e).__name__
            if code == "EMPTY_RESPONSE":
                rows = []                       # "No data exists": nothing new since the last read (or none at all)
            elif code == "IDENTIFIER_NOT_RESOLVED":
                st.status, st.fetched_at = "unknown", read_at
                self._local[sym] = st
                await self._store.put(PREFIX + "state:" + sym, _encode(st), CACHE_TTL_S)
                return
            else:
                reason = code if code in _RETRY_CODES or code == "NOT_CONFIGURED" else "error"
                self.problems[reason] = self.problems.get(reason, 0) + 1
                logger.warning("scan dashboard tick flow: TrueData ticks for %s failed (%s)", sym, code)
                return                          # keep the counts so far; retried next cycle
        self.rows_read += len(rows or [])
        apply_rows(st, rows or [])
        if st.last_ts is None and not rows:
            st.status = "empty"
        elif st.status == "empty":
            st.status = "ok"
        st.fetched_at = read_at
        self._local[sym] = st
        await self._store.put(PREFIX + "state:" + sym, _encode(st), CACHE_TTL_S)

    async def counts(self, symbols: Sequence[str]) -> TickFlowResult:
        syms = list(dict.fromkeys(gw.canon(s) for s in symbols if s))
        now, wall = self._now(), self._wall()
        day = session_day(now)
        warnings: List[str] = []
        if not syms:
            return TickFlowResult(values={}, as_of=None, source=SOURCE)
        if not self._configured():
            return TickFlowResult(values={}, as_of=None, source=SOURCE, missing=syms, warnings=[
                "No TrueData login (TRUEDATA_USERNAME / TRUEDATA_PASSWORD are not set on this server)"])

        await self._sync_from_store([s for s in syms if self._stale(self._local.get(s), day, now, wall)])
        stale = [s for s in syms if self._stale(self._local.get(s), day, now, wall)]
        if stale:
            self._schedule(stale)
            if self._task is not None and all(not self._has_day(s, day) for s in syms):
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), self._first_wait)
                except asyncio.TimeoutError:
                    pass
        problems: List[str] = []
        for reason, n in sorted(self.problems.items()):
            if reason == "NOT_CONFIGURED":
                problems.append(f"TrueData refused {n} tick read(s): account not subscribed or not authorised")
            elif reason == "RATE_LIMITED":
                problems.append(f"TrueData call quota reached ({n} tick read(s) retried)")
            elif reason == "AUTH_EXPIRED":
                problems.append(f"TrueData refused the login ({n} tick read(s) retried)")
            else:
                problems.append(f"{n} TrueData tick read(s) failed and are retried")
        self.problems.clear()

        values: Dict[str, Dict[str, Optional[float]]] = {}
        missing: List[str] = []
        loading, empty, unknown = [], [], []
        as_of: Optional[str] = None
        for s in syms:
            st = self._local.get(s)
            if st is None or st.day != day.isoformat():
                missing.append(s)
                loading.append(s)
                continue
            if st.status == "unknown":
                missing.append(s)
                unknown.append(s)
                continue
            if st.status == "empty" or st.last_counted_ts is None:
                missing.append(s)
                empty.append(s)
                continue
            values[s] = {"buy_trades": float(st.buy_trades), "sell_trades": float(st.sell_trades),
                         "buy_volume": float(st.buy_volume), "sell_volume": float(st.sell_volume)}
            if as_of is None or st.last_counted_ts > as_of:
                as_of = st.last_counted_ts
        if loading:
            warnings.append(f"trade-side ticks are loading ({len(loading)} of {len(syms)} stocks)")
        warnings += problems
        if empty:
            warnings.append(f"TrueData has no ticks on {day.isoformat()} for {', '.join(empty[:8])}" + ("…" if len(empty) > 8 else ""))
        if unknown:
            warnings.append(f"TrueData does not know {', '.join(unknown[:8])}" + ("…" if len(unknown) > 8 else ""))
        if not in_session(now) and values:
            warnings.append(f"Market closed: the counts are for the session of {day.isoformat()}")
        return TickFlowResult(values=values, as_of=(as_of + "+05:30") if as_of else None, source=SOURCE,
                              warnings=warnings, missing=missing)

    def _has_day(self, sym: str, day: date) -> bool:
        st = self._local.get(sym)
        return st is not None and st.day == day.isoformat()


_SERVICE: Optional[TickFlow] = None


def get_service() -> TickFlow:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = TickFlow()
    return _SERVICE


async def initiated_counts(symbols: Sequence[str], *, now: Optional[datetime] = None) -> TickFlowResult:
    """See the module docstring. `now` is for tests and checks; the service's clock is used otherwise."""
    svc = get_service()
    if now is not None:
        saved = svc._now
        svc._now = lambda: now
        try:
            return await svc.counts(symbols)
        finally:
            svc._now = saved
    return await svc.counts(symbols)
