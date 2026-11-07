"""The SPT paper monitor (DESIGN.md §6 "Exits", WF §13, §16, §19.3, §20). Read-only towards brokers: it never calls one.

ON where APP_ENV=staging or SPT_C_ENABLED=1; SPT_C_ENABLED=0 turns it off (config.enabled). ONE leader across workers:
the Redis key nivesh:spt:c:leader through the scan dashboard's store `lead()` (services/exit_watch/runner.py pattern).

EVERY PASS (any time of day), before anything else:
    housekeeping   finish what a stopped process left half done, each step idempotent: an ENTRY left in CREATED /
                   VALIDATED is validated and queued; an order whose recorded fills have not reached spt_fills / the
                   position / its terminal handling is synced; a position that claimed an exit order that was never
                   written gets it; a CLOSED position whose release or outcome is owed gets them
    expiry         DAY orders at 15:30 IST of their session, GTD at `expires_at` (orders.expire_due)
The first pass of a process also runs the reconciliation (reconcile.startup_check), which marks what does not add up
RECONCILIATION_REQUIRED and moves no money.

LIVE ROUND (09:15–15:30 IST, weekdays; every SPT_C_LOOP_S = 15 s):
  1. kill switch / halt / B's account block (controls.entry_block) for every user with a live ENTRY: their ENTRY orders
     are cancelled (reservations released when nothing filled); no ENTRY fill happens for them this round.
  2. one quote read for every symbol with a live order or an open position (`Deps.quotes`; the default is
     kite_live_feed.day_quote.day_quotes, live Kite only).
  3. live orders, oldest first: one fill attempt each (execution.execute_order).
  4. open positions: the display mark and MFE/MAE; then, on the live BID (LTP when the quote has no bid, said so on the
     exit's trigger):
        an EXIT_PENDING position (decided at the evening pass) → a full MARKET exit at this first live quote;
        bid ≤ stop        → STOP_TRIGGERED, the live ENTRY remainder cancelled, a full MARKET exit (reason `stop`, or
                            `trailing` once the ATR trail has raised the stop); `gap: true` when the session opened
                            below the stop (the quote's open);
        bid ≥ target 2    → TARGET_TRIGGERED, a full exit (`target_2`);
        bid ≥ target 1    → TARGET_TRIGGERED, an exit of t1_exit_fraction of the open quantity (`target_1`); when it has
                            filled, the stop moves to breakeven (positions.after_exit_terminal).
     A position with a live full exit (CLOSING), in RECONCILIATION_REQUIRED or EXECUTION_EXCEPTION gets no new order.
  5. the exit orders created in step 4 get their first fill attempt on the same quote.

EVENING PASS (18:30–23:30 IST, weekdays; every 10 min until done for the day), per open position whose symbol has
NSE's end-of-day bar for TODAY (desk_trading.fetch_bars; otherwise it waits for the next attempt):
  - sessions held = the bars after the entry day;
  - a stop breached by today's low with no live exit (stale quotes all day) → EXIT_PENDING (reason stop);
  - the ATR trail (exit_plan.trail, `trail-atr-v1`: services/exit_rules start/step over the bars since entry, the ATR
    seeded from the bars before it) raises the stop, never lowers it (STOP_MOVED);
  - the trend exit (exit_plan.trend_exit `close_below_sma20`): today's close below the simple 20-session average →
    EXIT_PENDING (reason trend);
  - the time exit: sessions held ≥ max_hold_sessions → EXIT_PENDING (reason time).
  No fill ever comes from a bar: an EXIT_PENDING position exits at the next session's first live quote.

NEVER RAISES OUT OF A ROUND: each order / position is its own try; a failure is logged with its type and counted in
spt_state {_id: "spt_c", at, round, counts, errors}. RESTART-SAFE: a fill is recorded with the order's version and fill
count in the filter (orders.record_fills), so re-running a round never double-fills.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.spt import constants as C
from services.spt import events as ev

from . import config, controls, execution, orders, positions, reconcile, store

logger = logging.getLogger(__name__)

LEADER_KEY = "nivesh:spt:c:leader"
LEADER_TTL_S = 90
IDLE_S = 60.0
EVENING_EVERY_S = 600.0
EVENING_FROM, EVENING_TO = dtime(18, 30), dtime(23, 30)
NEW_ORDER_GRACE_S = 30
HOUSEKEEPING_WINDOW_DAYS = 3
BARS_LOOKBACK_DAYS = 120
SMA_PERIOD = 20
MAX_ERRORS_KEPT = 20
NO_AUTO_EXIT = (C.POS_RECONCILIATION_REQUIRED, C.POS_EXECUTION_EXCEPTION, C.POS_CLOSED)

_task: Optional[asyncio.Task] = None
_ME = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
_last_evening: float = float("-inf")
_started_up = False


def in_evening(now: datetime) -> bool:
    t = now.astimezone(store.IST)
    return t.weekday() < 5 and EVENING_FROM <= t.time() <= EVENING_TO


# ── dependencies (injectable) ────────────────────────────────────────────────────────────────────────────────────────

async def default_quotes(symbols: List[str], now: datetime) -> Dict[str, Any]:
    """{"quotes": {SYMBOL: quote}, "why"}: live Kite quotes only (the Redis cache first, the feed snapshot behind it);
    when the feed is not live there are none and `why` says so."""
    from services.kite_live_feed import day_quote
    got = await day_quote.day_quotes(symbols, now=now)
    if got.get("source") != "kite_live":
        return {"quotes": {}, "why": got.get("why") or "feed_not_live"}
    return {"quotes": got.get("quotes") or {}, "why": None}


async def default_bars(symbol: str, start: date) -> List[Dict[str, Any]]:
    from services import desk_trading
    return await desk_trading.fetch_bars(symbol, start)


@dataclass
class Deps:
    db: Any
    quotes: Callable[[List[str], datetime], Awaitable[Dict[str, Any]]] = default_quotes
    bars: Callable[[str, date], Awaitable[List[Dict[str, Any]]]] = default_bars
    extra: Dict[str, Any] = field(default_factory=dict)


def default_deps() -> Deps:
    from deps import db
    return Deps(db=db)


class _Round:
    def __init__(self) -> None:
        self.counts: Dict[str, int] = {}
        self.errors: List[Dict[str, str]] = []

    def inc(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def fail(self, where: str, e: BaseException) -> None:
        logger.warning("spt monitor: %s failed (%s)", where, type(e).__name__)
        self.inc("errors")
        if len(self.errors) < MAX_ERRORS_KEPT:
            self.errors.append({"where": where, "error": type(e).__name__})


# ── housekeeping (every pass) ────────────────────────────────────────────────────────────────────────────────────────

async def housekeeping(db, now: datetime, r: _Round, *, full: bool = False) -> None:
    """Finish what a stopped process left half done (module docstring). Each item its own try. A routine pass looks at
    documents changed in the last HOUSEKEEPING_WINDOW_DAYS (an indexed read); the startup pass (`full`) at all of them."""
    grace = store.iso(now - timedelta(seconds=NEW_ORDER_GRACE_S))
    window: Dict[str, Any] = {} if full else {"updated_at": {"$gte": store.iso(now - timedelta(days=HOUSEKEEPING_WINDOW_DAYS))}}
    try:
        stuck = await db[store.ORDERS].find({"state": {"$in": [C.ORD_CREATED, C.ORD_VALIDATED]},
                                             "created_at": {"$lte": grace}}).to_list(1000)
    except Exception as e:  # noqa: BLE001
        r.fail("housekeeping.read_new", e)
        stuck = []
    for o in stuck:
        try:
            await orders.advance_new(db, o, now)
            r.inc("advanced_new")
        except Exception as e:  # noqa: BLE001
            r.fail(f"advance_new {o['_id']}", e)
    try:
        behind = await db[store.ORDERS].find({**window, "$or": [
            {"$expr": {"$lt": [{"$ifNull": ["$position_seq", 0]}, {"$ifNull": ["$fills_seq", 0]}]}},
            {"$expr": {"$lt": [{"$ifNull": ["$logged_seq", 0]}, {"$ifNull": ["$fills_seq", 0]}]}},
            {"state": {"$in": list(orders.TERMINAL)}, "terminal_done": False}]}).to_list(1000)
    except Exception as e:  # noqa: BLE001
        r.fail("housekeeping.read_behind", e)
        behind = []
    for o in behind:
        try:
            await orders.sync_order(db, o["_id"], now=now)
            r.inc("synced")
        except Exception as e:  # noqa: BLE001
            r.fail(f"sync {o['_id']}", e)
    try:
        claimed = await db[store.POSITIONS].find({"live_exit_order_id": {"$ne": None},
                                                  "state": {"$in": list(C.POS_OPEN_STATES)}}).to_list(1000)
    except Exception as e:  # noqa: BLE001
        r.fail("housekeeping.read_claims", e)
        claimed = []
    for p in claimed:
        try:
            if await store.get_order(db, p["live_exit_order_id"]) is None:
                await orders.ensure_exit_order(db, p, now=now)
                r.inc("exit_orders_restored")
        except Exception as e:  # noqa: BLE001
            r.fail(f"ensure_exit {p['_id']}", e)
    try:
        owed = await db[store.POSITIONS].find({**window, "state": C.POS_CLOSED, "$or": [
            {"release.state": {"$in": ["pending", "claimed"]}}, {"outcome": None}]}).to_list(1000)
    except Exception as e:  # noqa: BLE001
        r.fail("housekeeping.read_closed", e)
        owed = []
    for p in owed:
        try:
            if (p.get("release") or {}).get("state") in ("pending", "claimed"):
                if await positions.recover_release(db, p, now=now):
                    r.inc("releases_recovered")
            if not p.get("outcome"):
                await positions.close_followups(db, await store.get_position(db, p["_id"]) or p, now=now)
        except Exception as e:  # noqa: BLE001
            r.fail(f"closed {p['_id']}", e)


# ── the live round ───────────────────────────────────────────────────────────────────────────────────────────────────

def _trail_raised(pos: Dict[str, Any]) -> bool:
    hist = pos.get("stop_history") or []
    return bool(hist) and (hist[-1] or {}).get("reason") == "trailing_atr"


async def evaluate_position(db, pos: Dict[str, Any], raw_quote: Any, now: datetime, r: _Round) -> Optional[str]:
    """Marks and exit triggers for one position (module docstring, step 4). Returns the id of an exit order created."""
    if pos.get("state") in NO_AUTO_EXIT:
        r.inc("positions_not_monitored")
        return None
    q, why = execution.check_quote(raw_quote, now)
    if q is None:
        r.inc(f"positions_{why}")
        return None
    await positions.mark(db, pos, q, now)
    pos = await store.get_position(db, pos["_id"]) or pos
    if pos.get("state") == C.POS_CLOSING or int(pos.get("quantity") or 0) <= 0:
        return None
    live = await store.get_order(db, pos["live_exit_order_id"]) if pos.get("live_exit_order_id") else None
    live = live if live and live.get("state") in C.ORD_LIVE_STATES else None
    if live is not None and live.get("exit_full"):
        return None
    ref = q.get("bid") or q.get("ltp")
    basis = "bid" if q.get("bid") else "ltp_no_bid"
    stop, t1, t2 = execution._num(pos.get("stop_loss")), execution._num(pos.get("target_1")), execution._num(pos.get("target_2"))
    trig = {"basis": basis, "price": ref, "bid": q.get("bid"), "ltp": q.get("ltp"), "open": q.get("open"),
            "quote_at": q.get("received_at")}
    day = store.ist_day(now).isoformat()
    pending = pos.get("pending_exit") if pos.get("state") == C.POS_EXIT_PENDING else None
    if pending:
        reason = pending.get("reason") or "manual"
        gap = reason in ("stop", "trailing") and stop is not None and q.get("open") is not None and q["open"] < stop
        o = await orders.create_exit_order(db, position_id=pos["_id"], reason=reason, gap=gap,
                                           trigger={**trig, "level": stop, "pending": pending}, actor_id=positions.SERVICE_ACTOR,
                                           now=now)
        r.inc("exits_pending_sent")
        return o["_id"]
    if stop is not None and ref <= stop:
        reason = "trailing" if _trail_raised(pos) else "stop"
        gap = q.get("open") is not None and q["open"] < stop
        await ev.emit(db, "STOP_TRIGGERED", idempotency_key=f"position:{pos['_id']}:stop:{pos.get('stop_version')}:{day}",
                      source_service=store.SOURCE, occurred_at=store.iso(now), correlation_id=pos.get("correlation_id"),
                      account_id=pos["user_id"], instrument_id=pos["symbol"],
                      payload={"position_id": pos["_id"], "stop_loss": stop, "reason": reason, "gap": gap, **trig})
        o = await orders.create_exit_order(db, position_id=pos["_id"], reason=reason, gap=gap,
                                           trigger={**trig, "level": stop}, actor_id=positions.SERVICE_ACTOR, now=now)
        r.inc("stops_triggered")
        return o["_id"]
    if t2 is not None and ref >= t2:
        await ev.emit(db, "TARGET_TRIGGERED", idempotency_key=f"position:{pos['_id']}:target_2:{day}",
                      source_service=store.SOURCE, occurred_at=store.iso(now), correlation_id=pos.get("correlation_id"),
                      account_id=pos["user_id"], instrument_id=pos["symbol"],
                      payload={"position_id": pos["_id"], "target": "target_2", "level": t2, **trig})
        o = await orders.create_exit_order(db, position_id=pos["_id"], reason="target_2",
                                           trigger={**trig, "level": t2}, actor_id=positions.SERVICE_ACTOR, now=now)
        r.inc("targets_triggered")
        return o["_id"]
    if t1 is not None and not pos.get("t1_done") and live is None and ref >= t1:
        qty = int(pos["quantity"])
        part = max(1, int(math.floor(qty * float(pos.get("t1_exit_fraction") or 0.5))))
        await ev.emit(db, "TARGET_TRIGGERED", idempotency_key=f"position:{pos['_id']}:target_1:{day}",
                      source_service=store.SOURCE, occurred_at=store.iso(now), correlation_id=pos.get("correlation_id"),
                      account_id=pos["user_id"], instrument_id=pos["symbol"],
                      payload={"position_id": pos["_id"], "target": "target_1", "level": t1, "quantity": part, **trig})
        o = await orders.create_exit_order(db, position_id=pos["_id"], reason="target_1", quantity=part,
                                           trigger={**trig, "level": t1}, actor_id=positions.SERVICE_ACTOR, now=now)
        r.inc("targets_triggered")
        return o["_id"]
    if pos.get("state") in (C.POS_OPEN, C.POS_PARTIALLY_EXITED) and live is None:
        await store.transition(db, store.POSITIONS, pos["_id"], expect_states=[pos["state"]],
                               expect_version=pos["version"], to_state=C.POS_MONITORING, now=now)
    return None


async def live_round(now: datetime, deps: Deps) -> Dict[str, Any]:
    """One pass (the caller holds the leadership). In the session it also fills and watches (module docstring)."""
    db = deps.db
    r = _Round()
    await store.ensure_indexes(db)
    await housekeeping(db, now, r)
    try:
        r.inc("expired", await orders.expire_due(db, now))
    except Exception as e:  # noqa: BLE001
        r.fail("expire_due", e)
    session_open = store.in_session(now)
    feed_why = None
    if session_open:
        blocked: Dict[str, Dict[str, Any]] = {}
        try:
            live = await store.live_orders(db)
        except Exception as e:  # noqa: BLE001
            r.fail("read_live_orders", e)
            live = []
        for uid in sorted({o["user_id"] for o in live if o.get("purpose") == "ENTRY"}):
            try:
                b = await controls.entry_block(db, uid)
            except Exception as e:  # noqa: BLE001 — fail closed
                r.fail("entry_block", e)
                b = {"code": "controls_unreadable"}
            if b:
                blocked[uid] = b
        for o in live:
            if o.get("purpose") == "ENTRY" and o["user_id"] in blocked:
                try:
                    if await orders.cancel_paper_order(db, o["_id"], reason=blocked[o["user_id"]]["code"], now=now):
                        r.inc("entries_cancelled_by_controls")
                except Exception as e:  # noqa: BLE001
                    r.fail(f"cancel {o['_id']}", e)
        try:
            live = await store.live_orders(db)
            open_pos = await store.open_positions(db)
        except Exception as e:  # noqa: BLE001
            r.fail("read_book", e)
            live, open_pos = [], []
        symbols = sorted({o["symbol"] for o in live} | {p["symbol"] for p in open_pos})
        quotes: Dict[str, Any] = {}
        if symbols:
            try:
                got = await deps.quotes(symbols, now) or {}
                quotes, feed_why = got.get("quotes") or {}, got.get("why")
            except Exception as e:  # noqa: BLE001 — no quotes: nothing fills, nothing triggers; the state says why
                r.fail("quotes", e)
                feed_why = "unreadable"
        for o in live:
            if o.get("purpose") == "ENTRY" and o["user_id"] in blocked:
                continue
            try:
                res = await execution.execute_order(db, o, quotes.get(o["symbol"]), now, session_open=True)
                r.inc("fill_attempts")
                if res["filled"]:
                    r.inc("fills")
                    r.inc("shares_filled", res["filled"])
                elif res["reason"]:
                    r.inc(f"no_fill_{res['reason']}")
            except Exception as e:  # noqa: BLE001
                r.fail(f"execute {o['_id']}", e)
        new_exits: List[str] = []
        try:
            open_pos = await store.open_positions(db)
        except Exception as e:  # noqa: BLE001
            r.fail("read_positions", e)
            open_pos = []
        for p in open_pos:
            try:
                oid = await evaluate_position(db, p, quotes.get(p["symbol"]), now, r)
                if oid:
                    new_exits.append(oid)
            except orders.ExitRefused as e:
                r.inc(f"exit_refused_{e.code}")
            except Exception as e:  # noqa: BLE001
                r.fail(f"evaluate {p['_id']}", e)
        for oid in new_exits:
            try:
                o = await store.get_order(db, oid)
                if o is not None and o.get("state") in C.ORD_LIVE_STATES:
                    res = await execution.execute_order(db, o, quotes.get(o["symbol"]), now, session_open=True)
                    if res["filled"]:
                        r.inc("fills")
                        r.inc("shares_filled", res["filled"])
            except Exception as e:  # noqa: BLE001
                r.fail(f"execute_exit {oid}", e)
    state = {"at": store.iso(now), "round": "live" if session_open else "housekeeping", "leader": _ME,
             "counts": r.counts, "errors": r.errors, "feed_why": feed_why}
    await store.write_state(db, {"live": state, "at": state["at"]})
    return {"ran": True, **state}


# ── the evening pass ─────────────────────────────────────────────────────────────────────────────────────────────────

def _bar_day(b: Dict[str, Any]) -> Optional[date]:
    d = b.get("date")
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return None


def lowest_stop_today(pos: Dict[str, Any], today: date) -> Optional[float]:
    """The lowest stop in force at any time during `today`'s session: the stop at the open and every stop set during the
    day. A low at or below it went through the stop whenever it happened; a low below only a stop raised later that day
    (breakeven after T1) may have come before the raise and is not counted."""
    open_at = datetime.combine(today, store.OPEN, tzinfo=store.IST)
    stops: List[float] = []
    at_open: Optional[float] = None
    for h in pos.get("stop_history") or []:
        t = store.parse_ts(h.get("at"))
        s = execution._num(h.get("stop"))
        if t is None or t <= open_at:
            at_open = s
        elif store.ist_day(t) == today:
            stops.append(s)
    cands = [x for x in [at_open, *stops] if x is not None]
    return min(cands) if cands else None


def trail_stop(pos: Dict[str, Any], warm: List[Dict[str, Any]], held: List[Dict[str, Any]]) -> Optional[float]:
    """The ATR trail's stop after the held bars (services/exit_rules trail-atr-v1: highest high since entry − k × ATR14,
    never loosening), or None when the trail is off or cannot be worked out."""
    from services import exit_rules as xr
    trail = pos.get("trail") or {}
    k = execution._num(trail.get("k"))
    avg, stop0 = execution._num(pos.get("avg_entry_price")), execution._num(pos.get("initial_stop"))
    if not trail or k is None or avg is None or stop0 is None:
        return None
    rules = xr.Rules(side="long", trail_atr_mult=min(k, xr.MAX_TRAIL_MULT),
                     atr_period=int(trail.get("atr_period") or xr.DEFAULT_ATR_PERIOD))
    state = xr.start(avg, stop0, rules, warmup=warm)
    for b in held:
        try:
            state, ex = xr.step(state, b, rules)
        except xr.IncompleteBar:
            break
        if ex is not None:
            break
    return state.stop


async def evening_position(db, pos: Dict[str, Any], bars: List[Dict[str, Any]], today: date, now: datetime,
                           r: _Round) -> None:
    opened = store.ist_day(store.parse_ts(pos.get("opened_at")) or now)
    warm = [b for b in bars if (_bar_day(b) or today) <= opened][-60:]
    held = [b for b in bars if (_bar_day(b) or date.min) > opened]
    sessions = len(held)
    last = bars[-1]
    low, close = execution._num(last.get("low")), execution._num(last.get("close"))
    stop = execution._num(pos.get("stop_loss"))
    floor = lowest_stop_today(pos, today)
    pending: Optional[Dict[str, Any]] = None
    if held and floor is not None and low is not None and low <= floor and pos.get("state") != C.POS_CLOSING:
        pending = {"reason": "trailing" if _trail_raised(pos) else "stop", "note": "stop_breached_without_live_exit",
                   "low": low, "stop": floor, "day": today.isoformat()}
    cand = trail_stop(pos, warm, held)
    if cand is not None and (stop is None or cand > stop + 1e-9):
        if await positions.move_stop(db, pos["_id"], cand, reason="trailing_atr", by=positions.SERVICE_ACTOR, now=now,
                                     market_ref={"source": "nse_eod", "day": today.isoformat(), "close": close}):
            r.inc("trail_raised")
    trend = pos.get("trend_exit") or {}
    if pending is None and trend and close is not None:
        closes = [execution._num(b.get("close")) for b in bars]
        closes = [c for c in closes if c is not None]
        if len(closes) >= SMA_PERIOD:
            sma = sum(closes[-SMA_PERIOD:]) / SMA_PERIOD
            if close < sma - 1e-9:
                pending = {"reason": "trend", "rule": trend.get("rule") or "close_below_sma20", "close": close,
                           "sma20": round(sma, 2), "day": today.isoformat()}
    mh = orders._whole(pos.get("max_hold_sessions"))
    if pending is None and mh is not None and sessions >= mh:
        pending = {"reason": "time", "sessions_held": sessions, "max_hold_sessions": mh, "day": today.isoformat()}
    for _ in range(positions.MAX_RETRIES):
        cur = await store.get_position(db, pos["_id"])
        if cur is None or cur.get("state") not in C.POS_OPEN_STATES:
            return
        fields: Dict[str, Any] = {"sessions_held": sessions, "evening_day": today.isoformat()}
        to_state = None
        if pending and not cur.get("pending_exit") and cur.get("state") not in (C.POS_CLOSING,) + NO_AUTO_EXIT:
            fields["pending_exit"] = {**pending, "at": store.iso(now)}
            to_state = C.POS_EXIT_PENDING
        if await store.transition(db, store.POSITIONS, pos["_id"], expect_states=C.POS_OPEN_STATES,
                                  expect_version=cur["version"], to_state=to_state, set_=fields, now=now):
            if to_state:
                r.inc(f"exit_pending_{pending['reason']}")
            return


async def evening_round(now: datetime, deps: Deps) -> Dict[str, Any]:
    """One evening pass (the caller checked the window and the leadership)."""
    db = deps.db
    r = _Round()
    today = store.ist_day(now)
    st = await store.read_state(db)
    if (st.get("evening") or {}).get("day") == today.isoformat():
        return {"ran": False, "why": "done for the day"}
    pend: List[str] = []
    cache: Dict[str, Optional[List[Dict[str, Any]]]] = {}
    try:
        open_pos = await store.open_positions(db)
    except Exception as e:  # noqa: BLE001
        r.fail("read_positions", e)
        open_pos = []
    for p in open_pos:
        if p.get("state") in NO_AUTO_EXIT or p.get("evening_day") == today.isoformat():
            continue
        sym = p["symbol"]
        if sym not in cache:
            try:
                cache[sym] = await deps.bars(sym, today - timedelta(days=BARS_LOOKBACK_DAYS))
            except Exception as e:  # noqa: BLE001 — that symbol waits for the next attempt; nothing decided on missing data
                r.fail(f"bars {sym}", e)
                cache[sym] = None
        bars = cache[sym]
        if not bars or _bar_day(bars[-1]) != today:
            if sym not in pend:
                pend.append(sym)
            continue
        try:
            await evening_position(db, p, bars, today, now, r)
            r.inc("evening_positions")
        except Exception as e:  # noqa: BLE001
            r.fail(f"evening {p['_id']}", e)
    ev_state = {"at": store.iso(now), "counts": r.counts, "errors": r.errors, "pending": pend}
    if not pend and not r.errors:
        ev_state["day"] = today.isoformat()
    else:
        ev_state["day"] = (st.get("evening") or {}).get("day")
        ev_state["attempt_day"] = today.isoformat()
    await store.write_state(db, {"evening": ev_state})
    return {"ran": True, **ev_state}


# ── the loop ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def startup(db, now: datetime) -> Dict[str, Any]:
    """The first pass of a process: finish leftovers, then reconcile (marks, never moves money)."""
    r = _Round()
    await store.ensure_indexes(db)
    await housekeeping(db, now, r, full=True)
    try:
        rep = await reconcile.startup_check(db, now=now)
    except Exception as e:  # noqa: BLE001
        r.fail("reconcile", e)
        rep = {"ok": None, "mismatches": []}
    await store.write_state(db, {"startup": {"at": store.iso(now), "counts": r.counts, "errors": r.errors,
                                             "reconcile_ok": rep.get("ok"),
                                             "mismatches": len(rep.get("mismatches") or [])}})
    return rep


async def loop_once(now: datetime, deps: Optional[Deps] = None, *, leader_store: Any = None, me: str = _ME,
                    clock: Callable[[], float] = time.monotonic) -> str:
    """One pass: 'not_leader' · 'live' · 'housekeeping' · 'evening'."""
    global _last_evening, _started_up
    if leader_store is None:
        from services.scan_builder import signals
        leader_store = signals.get_store()
    if not await leader_store.lead(LEADER_KEY, me, LEADER_TTL_S, time.time()):
        return "not_leader"
    deps = deps or default_deps()
    if not _started_up:
        await startup(deps.db, now)
        _started_up = True
    out = await live_round(now, deps)
    if in_evening(now) and clock() - _last_evening >= EVENING_EVERY_S:
        _last_evening = clock()
        await evening_round(now, deps)
        return "evening"
    return out["round"]


async def _loop() -> None:
    while True:
        now = datetime.now(timezone.utc)
        try:
            from services.spt import settings
            await settings.refresh(default_deps().db)      # every worker, before the leader check (settings.py)
            what = await loop_once(now)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — one failed pass never stops the monitor; logged with its trace
            logger.exception("spt monitor: a pass failed")
            what = "failed"
        await asyncio.sleep(config.loop_seconds() if what == "live" or store.in_session(datetime.now(timezone.utc))
                            else IDLE_S)


def start() -> bool:
    """Start the monitor on this worker when enabled (server startup). True if started."""
    global _task
    if not config.enabled() or (_task is not None and not _task.done()):
        return False
    _task = asyncio.get_running_loop().create_task(_loop())
    logger.info("spt monitor: started (every %.0f s in the session, evening pass after NSE's file, one leader)",
                config.loop_seconds())
    return True


def stop() -> None:
    if _task is not None and not _task.done():
        _task.cancel()
