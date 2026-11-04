"""The exit watcher (docs/paper_pnl_dashboard/EXIT_WATCH.md "Watcher"). Read-only towards brokers: it never calls one.

On where APP_ENV=staging or EXIT_WATCH_ENABLED=1; EXIT_WATCH_ENABLED=0 turns it off. One leader across workers (the
Redis key nivesh:exitwatch:leader through the scan dashboard's store `lead()`).

The book    every user whose broker positions were read in the last EXIT_WATCH_BOOK_DAYS (3) days: the latest
            position_snapshots document per account (rows with a quantity). The snapshot is the positions
            workspace's last read, written when the user opened My portfolio / Open positions / the P&L dashboard;
            the watcher never reads a broker itself.

Live round    09:15–15:30 IST on weekdays, every EXIT_WATCH_LOOP_S (30 s):
              - store a level for a position seen for the first time (or whose stored level has no stop);
              - fire HEDGE_REMOVED;
              - read the underlyings' quotes from the live feed (kite_live_feed.day_quote.day_quotes) and fire
                STOP_HIT / FLOOR_REACHED / NEAR_STOP (not for a hedged position: its loss is capped).
              A quote fires only when the feed is live and the quote was received in the last EXIT_WATCH_QUOTE_MAX_AGE_S
              (120 s). A price below 0.65× or above 1.5× the stored level's close is taken as a bonus or split not yet
              in the end-of-day series: it fires nothing until the evening round works the stop out again.
Evening round 18:30–23:30 IST on weekdays, every 10 min until done for the day. For each underlying whose NSE bar for
              TODAY is in:
              - advance the trailing stop (STOP_RAISED);
              - fire CLOSE_THROUGH_STOP / FLOOR_REACHED, SUPPORT_BREAK, TREND_TURN, HEDGE_REMOVED and RESULTS_SOON
                (a results date in the next 3 calendar days).
              When every watched underlying is done: exit_watch_state {_id: "eod", day: today}.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote as urlquote

from . import book as book_mod
from . import rules, store, view

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
LEADER_KEY = "nivesh:exitwatch:leader"
LEADER_TTL_S = 90
IDLE_S = 60.0
EVENING_EVERY_S = 600.0
EVENING_FROM, EVENING_TO = dtime(18, 30), dtime(23, 30)
BARS_LOOKBACK_DAYS = 200
RESULTS_DAYS = 3
SNAPSHOTS = "position_snapshots"
ALERT_DAYS = 7

SEVERITY = {"STOP_HIT": "CRITICAL", "NEAR_STOP": "WARNING", "FLOOR_REACHED": "WARNING", "CLOSE_THROUGH_STOP": "CRITICAL",
            "SUPPORT_BREAK": "WARNING", "TREND_TURN": "WARNING", "STOP_RAISED": "INFO", "HEDGE_REMOVED": "CRITICAL",
            "RESULTS_SOON": "INFO"}

_task: Optional[asyncio.Task] = None
_ME = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
_last_evening: float = float("-inf")


def _env_num(name: str, default: float, low: float) -> float:
    try:
        v = float(os.environ.get(name, default))
    except ValueError:
        return default
    return max(low, v)


def loop_seconds() -> float:
    return _env_num("EXIT_WATCH_LOOP_S", 30.0, 5.0)


def book_days() -> float:
    return _env_num("EXIT_WATCH_BOOK_DAYS", 3.0, 0.1)


def quote_max_age() -> float:
    return _env_num("EXIT_WATCH_QUOTE_MAX_AGE_S", 120.0, 5.0)


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get("EXIT_WATCH_ENABLED") or "").strip()
    if flag == "0":
        return False
    return flag == "1" or (env.get("APP_ENV") or "").strip().lower() == "staging"


def in_session(now: datetime) -> bool:
    t = now.astimezone(IST)
    return t.weekday() < 5 and dtime(9, 15) <= t.time() <= dtime(15, 30)


def in_evening(now: datetime) -> bool:
    t = now.astimezone(IST)
    return t.weekday() < 5 and EVENING_FROM <= t.time() <= EVENING_TO


def ist_day(now: datetime) -> date:
    return now.astimezone(IST).date()


def money(v: Optional[float]) -> str:
    return "—" if v is None else f"₹{v:,.2f}"


# ── dependencies (injectable) ────────────────────────────────────────────────────────────────────────────────────────

async def snapshot_books(db, now: datetime) -> Dict[str, Tuple[List[Dict[str, Any]], Optional[str]]]:
    """{user_id: (open rows of every account's latest snapshot, the newest read time)} for snapshots seen in the window."""
    from services.brokers import hub_reads as hub
    since = (now - timedelta(days=book_days())).astimezone(timezone.utc).isoformat()
    docs = await db[SNAPSHOTS].find({"last_seen_at": {"$gte": since}}).sort("read_at", -1).to_list(None)
    seen: set = set()
    out: Dict[str, Tuple[List[Dict[str, Any]], Optional[str]]] = {}
    for d in docs:
        uid, acct = d.get("user_id"), d.get("account_id")
        if not uid or not acct or (uid, acct) in seen:
            continue
        seen.add((uid, acct))
        broker = str(d.get("broker") or "")
        rows = []
        for r in d.get("rows") or []:
            if not book_mod._num(r.get("quantity")):
                continue
            rows.append({**r, "_account_id": acct, "_broker": broker, "_broker_display": hub.display_name(broker),
                         "_read_at": d.get("last_seen_at") or d.get("read_at")})
        have, at = out.get(uid, ([], None))
        last = d.get("last_seen_at") or d.get("read_at")
        out[uid] = (have + rows, max(filter(None, [at, last]), default=None))
    return out


async def default_bars(symbol: str, start: date) -> List[Dict[str, Any]]:
    from services import desk_trading
    return await desk_trading.fetch_bars(symbol, start)


async def default_quotes(symbols: List[str], now: datetime) -> Dict[str, Any]:
    from services.kite_live_feed import day_quote
    return await day_quote.day_quotes(symbols, now=now)


async def default_own_levels(db, user_id: str) -> Dict[str, Dict[str, Any]]:
    from services.positions import store as positions_store
    return await positions_store.read_levels(db, user_id)


async def default_events(symbol: str, today: date) -> List[Dict[str, Any]]:
    from services.copilot_tools import daas_client
    body = await daas_client._get(f"/events/{urlquote(symbol, safe='')}", params={"from_date": today.isoformat(), "limit": 50})
    rows = (body or {}).get("data") if isinstance(body, dict) else None
    return rows if isinstance(rows, list) else []


@dataclass
class Deps:
    db: Any
    books: Callable[[Any, datetime], Awaitable[Dict[str, Tuple[List[Dict[str, Any]], Optional[str]]]]] = snapshot_books
    bars: Callable[[str, date], Awaitable[List[Dict[str, Any]]]] = default_bars
    quotes: Callable[[List[str], datetime], Awaitable[Dict[str, Any]]] = default_quotes
    own_levels: Callable[[Any, str], Awaitable[Dict[str, Dict[str, Any]]]] = default_own_levels
    events: Callable[[str, date], Awaitable[List[Dict[str, Any]]]] = default_events
    extra: Dict[str, Any] = field(default_factory=dict)


def default_deps() -> Deps:
    from deps import db
    return Deps(db=db)


# ── shared pieces ────────────────────────────────────────────────────────────────────────────────────────────────────

def level_fields(w: book_mod.Watched, adv: Dict[str, Any]) -> Dict[str, Any]:
    """The level document's fields after `rules.advance_level`."""
    return {"account_id": w.account_id, "underlying": w.underlying, "side": w.side, "kind": w.kind, "method": w.method,
            "floor": (w.hedge or {}).get("strike"), "stop": adv.get("stop"), "day": adv.get("day"), "atr": adv.get("atr"),
            "atr_pct": adv.get("atr_pct"), "close": adv.get("close"), "support": adv.get("support"),
            "break_day": adv.get("break_day"), "why": adv.get("why"), "history": adv.get("history") or [], "active": True}


async def _bars(deps: Deps, cache: Dict[str, Any], symbol: str, today: date) -> Optional[List[Dict[str, Any]]]:
    """The underlying's bars, read once per round; None when unreadable (logged)."""
    if symbol in cache:
        return cache[symbol]
    try:
        bars = await deps.bars(symbol, today - timedelta(days=BARS_LOOKBACK_DAYS))
    except Exception as e:  # noqa: BLE001 — that underlying waits for the next round; nothing is fired on missing data
        logger.warning("exit_watch: bars for %s unreadable (%s)", symbol, type(e).__name__)
        bars = None
    cache[symbol] = bars
    return bars


async def _own(deps: Deps, uid: str) -> Dict[str, Dict[str, Any]]:
    try:
        return await deps.own_levels(deps.db, uid) or {}
    except Exception as e:  # noqa: BLE001 — without the user's own stops the rule's stop is used, and that is logged
        logger.warning("exit_watch: own levels unreadable (%s)", type(e).__name__)
        return {}


async def _fire(deps: Deps, uid: str, w: book_mod.Watched, kind: str, dedupe: str, *, day: str, price: Optional[float],
                level: Optional[float], source: str, source_at: Optional[str], text: str) -> int:
    ok = await store.fire(deps.db, uid, w.key, kind, dedupe, {
        "account_id": w.account_id, "account": w.account, "underlying": w.underlying, "severity": SEVERITY[kind], "day": day,
        "at": datetime.now(timezone.utc).isoformat(), "price": rules.r2(price), "level": rules.r2(level), "source": source,
        "source_at": source_at, "text": text, "rule": rules.RULE_ID})
    return 1 if ok else 0


def _who(w: book_mod.Watched) -> str:
    return f"{w.underlying} ({w.account})"


def _hedge_text(w: book_mod.Watched, stop: Optional[float]) -> str:
    what = "shares" if w.kind == "shares" else "future"
    return (f"{_who(w)}: the protective option is no longer in the book while the {what} are; the loss is no longer capped. "
            f"The stop loss is now the 2 × ATR trail {money(stop)}.")


def _fresh_price(q: Optional[Dict[str, Any]], now: datetime) -> Tuple[Optional[float], Optional[str]]:
    """(price, received_at) of a live quote received in the last EXIT_WATCH_QUOTE_MAX_AGE_S, else (None, None)."""
    if not q:
        return None, None
    px = book_mod._num(q.get("ltp"))
    at = q.get("received_at")
    if px is None or px <= 0 or not at:
        return None, None
    try:
        t = datetime.fromisoformat(str(at))
    except ValueError:
        return None, None
    if t.tzinfo is None:
        t = t.replace(tzinfo=IST)
    if (now - t).total_seconds() > quote_max_age():
        return None, None
    return px, str(at)


# ── live round ───────────────────────────────────────────────────────────────────────────────────────────────────────

async def live_round(now: datetime, deps: Deps) -> Dict[str, Any]:
    """One live round (the caller checked the session and the leader). Returns what it did."""
    db = deps.db
    await store.ensure_indexes(db)
    today = ist_day(now)
    day = today.isoformat()
    books = await deps.books(db, now)
    watched: Dict[str, List[book_mod.Watched]] = {uid: book_mod.group(rows)[0] for uid, (rows, _) in books.items()}
    unders = sorted({w.underlying for ws in watched.values() for w in ws})
    got: Dict[str, Any] = {"quotes": {}, "why": None, "source": None}
    if unders:
        try:
            got = await deps.quotes(unders, now) or got
        except Exception as e:  # noqa: BLE001 — no quotes: nothing fires this round, and the state says why
            logger.warning("exit_watch: quotes unreadable (%s)", type(e).__name__)
            got = {"quotes": {}, "why": "unreadable", "source": None}
    feed_why = got.get("why") or (None if got.get("source") in (None, "kite_live") or not unders else "feed_not_live")
    quotes = (got.get("quotes") or {}) if got.get("source") == "kite_live" else {}
    cache: Dict[str, Any] = {}
    fired = stale = positions = 0
    at = datetime.now(timezone.utc).isoformat()
    for uid, ws in watched.items():
        stored = await store.read_levels(db, uid)
        own = await _own(deps, uid)
        for w in ws:
            positions += 1
            doc = stored.get(w.key)
            if doc is None or doc.get("stop") is None:
                bars = await _bars(deps, cache, w.underlying, today)
                if bars is not None:
                    adv = rules.advance_level(doc if doc and doc.get("stop") is not None else None, bars, w.side)
                    fields = level_fields(w, adv)
                    await store.save_level(db, uid, w.key, fields, at=at)
                    doc = {**(doc or {}), **fields}
            if doc and doc.get("method") in rules.HEDGE_METHODS and w.kind != "hedged":
                fired += await _fire(deps, uid, w, "HEDGE_REMOVED", day, day=day, price=None, level=doc.get("stop"),
                                     source="broker_book", source_at=w.read_at, text=_hedge_text(w, doc.get("stop")))
            if doc is not None and (doc.get("method") != w.method or doc.get("kind") != w.kind or not doc.get("active")):
                await store.save_level(db, uid, w.key, {"method": w.method, "kind": w.kind, "active": True,
                                                        "floor": (w.hedge or {}).get("strike")}, at=at)
            price, q_at = _fresh_price(quotes.get(w.underlying), now)
            if price is None:
                stale += 1 if not feed_why else 0
                continue
            ref = book_mod._num((doc or {}).get("close"))
            if ref and not (rules.BREAK_LOW <= price / ref <= rules.BREAK_HIGH):
                logger.warning("exit_watch: %s price %.2f is far from its stored close %.2f; no alert until the evening round",
                               w.underlying, price, ref)
                continue
            stop, method = view.stop_in_force(w, (doc or {}).get("stop"), own.get(w.underlying), price)
            status, dpct, datr = rules.status_of(w.side, price, stop, (doc or {}).get("atr"), method)
            mtext = rules.METHOD_TEXT.get(method, method)
            if status == rules.HIT:
                fired += await _fire(deps, uid, w, "STOP_HIT", f"{stop:.2f}", day=day, price=price, level=stop, source="kite_live",
                                     source_at=q_at, text=(f"{_who(w)} is at {money(price)}, through its stop loss {money(stop)} "
                                                           f"({mtext}). Nothing has been sold: the broker is read-only here."))
            elif status == rules.FLOOR:
                k = (w.hedge or {}).get("strike") or stop
                what = "put" if method == rules.PUT_FLOOR else "call"
                fired += await _fire(deps, uid, w, "FLOOR_REACHED", f"{k:g}|{day}", day=day, price=price, level=k,
                                     source="kite_live", source_at=q_at,
                                     text=(f"{_who(w)} is at {money(price)}, through the {k:g} {what}: the hedged loss is at its "
                                           f"cap. Nothing has been sold: the broker is read-only here."))
            elif status == rules.NEAR and method not in rules.HEDGE_METHODS:
                fired += await _fire(deps, uid, w, "NEAR_STOP", day, day=day, price=price, level=stop, source="kite_live",
                                     source_at=q_at, text=(f"{_who(w)} is at {money(price)}, {dpct}% ({datr} ATR) from its stop "
                                                           f"loss {money(stop)} ({mtext})."))
        await store.deactivate_missing(db, uid, [w.key for w in ws], at=at)
    state = {"at": at, "users": len(watched), "positions": positions, "fired": fired, "stale": stale, "feed_why": feed_why}
    await store.write_state(db, "live", state)
    return {"ran": True, **state}


# ── evening round ────────────────────────────────────────────────────────────────────────────────────────────────────

def _is_results(e: Dict[str, Any]) -> bool:
    return "result" in str(e.get("event_type") or "").lower() or "financial result" in str(e.get("purpose") or "").lower()


async def evening_round(now: datetime, deps: Deps) -> Dict[str, Any]:
    """One evening round (the caller checked the window and the leader). Returns what it did."""
    db = deps.db
    await store.ensure_indexes(db)
    today = ist_day(now)
    day = today.isoformat()
    st = await store.read_state(db)
    if (st.get("eod") or {}).get("day") == day:
        return {"ran": False, "why": "done for the day", "day": day}
    books = await deps.books(db, now)
    watched: Dict[str, List[book_mod.Watched]] = {uid: book_mod.group(rows)[0] for uid, (rows, _) in books.items()}
    unders = sorted({w.underlying for ws in watched.values() for w in ws})
    cache: Dict[str, Any] = {}
    pending: List[str] = []
    for u in unders:
        bars = await _bars(deps, cache, u, today)
        if not bars or rules._day(bars[-1]) != day:
            pending.append(u)
    events_cache: Dict[str, List[Dict[str, Any]]] = {}
    fired = advanced = 0
    at = datetime.now(timezone.utc).isoformat()
    for uid, ws in watched.items():
        stored = await store.read_levels(db, uid)
        own = await _own(deps, uid)
        for w in ws:
            if w.underlying in pending:
                continue
            bars = cache[w.underlying]
            doc = stored.get(w.key)
            prev_stop = book_mod._num((doc or {}).get("stop"))
            in_force_rule = prev_stop if doc and doc.get("day") and str(doc["day"]) < day else None
            adv = rules.advance_level(doc if prev_stop is not None else None, bars, w.side)
            if doc and doc.get("method") in rules.HEDGE_METHODS and w.kind != "hedged":
                fired += await _fire(deps, uid, w, "HEDGE_REMOVED", day, day=day, price=None, level=adv.get("stop"),
                                     source="broker_book", source_at=w.read_at, text=_hedge_text(w, adv.get("stop")))
            close = float(bars[-1]["close"])
            stop, method = view.stop_in_force(w, in_force_rule, own.get(w.underlying), close)
            for s in rules.evening_signals(bars, w.side, stop, method):
                kind = s["kind"]
                if kind == "FLOOR_REACHED":
                    k = s["level"]
                    text = (f"{_who(w)} closed at {money(close)} on {day}, through its {k:g} option strike: the hedged loss is "
                            f"at its cap (NSE end of day).")
                    dedupe = f"{k:g}|{day}"
                elif kind == "CLOSE_THROUGH_STOP":
                    text = (f"{_who(w)} closed at {money(close)} on {day}, through its stop loss {money(s['level'])} "
                            f"({rules.METHOD_TEXT.get(method, method)}; NSE end of day).")
                    dedupe = day
                elif kind == "SUPPORT_BREAK":
                    where = "below its 20-session low" if w.side == "long" else "above its 20-session high"
                    text = f"{_who(w)} closed at {money(close)} on {day}, {where} {money(s['level'])} (NSE end of day)."
                    dedupe = day
                else:
                    turn = "down" if w.side == "long" else "up"
                    rel = "below" if w.side == "long" else "above"
                    text = (f"{_who(w)}: the daily trend turned {turn} on {day}: the close {money(close)} is {rel} the "
                            f"20-day average {money(s['ema20'])}, itself {rel} the 50-day {money(s['ema50'])}.")
                    dedupe = day
                fired += await _fire(deps, uid, w, kind, dedupe, day=day, price=close, level=s["level"], source="eod",
                                     source_at=day, text=text)
            if adv.get("moved") and not adv.get("reset") and prev_stop is not None:
                fired += await _fire(deps, uid, w, "STOP_RAISED", day, day=day, price=close, level=adv["stop"], source="eod",
                                     source_at=day,
                                     text=(f"{_who(w)}: the 2 × ATR trailing stop loss moved from {money(prev_stop)} to "
                                           f"{money(adv['stop'])} after NSE's {day} close."))
            await store.save_level(db, uid, w.key, level_fields(w, adv), at=at)
            advanced += 1
            if w.underlying not in events_cache:
                try:
                    events_cache[w.underlying] = await deps.events(w.underlying, today)
                except Exception as e:  # noqa: BLE001 — no results alert this evening; the next evening tries again
                    logger.warning("exit_watch: events for %s unreadable (%s)", w.underlying, type(e).__name__)
                    events_cache[w.underlying] = []
            for e in events_cache[w.underlying]:
                d = str(e.get("event_date") or "")[:10]
                try:
                    ed = date.fromisoformat(d)
                except ValueError:
                    continue
                if _is_results(e) and today <= ed <= today + timedelta(days=RESULTS_DAYS):
                    when = "today" if ed == today else f"on {ed.strftime('%a %d %b')}"
                    fired += await _fire(deps, uid, w, "RESULTS_SOON", d, day=day, price=None, level=None, source="nse_events",
                                         source_at=d, text=f"{_who(w)}: results are due {when} (exchange board-meeting notice).")
        await store.deactivate_missing(db, uid, [w.key for w in ws], at=at)
    if pending:
        await store.write_state(db, "eod", {"at": at, "pending": pending, "attempt_day": day})
    else:
        await store.write_state(db, "eod", {"day": day, "at": at, "pending": []})
    return {"ran": True, "day": day, "advanced": advanced, "fired": fired, "pending": pending}


# ── the loop ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def loop_once(now: datetime, deps: Optional[Deps] = None, *, leader_store: Any = None, me: str = _ME,
                    clock: Callable[[], float] = time.monotonic) -> str:
    """One pass: 'idle' · 'not_leader' · 'live' · 'evening' · 'waiting' (an evening attempt ran under 10 min ago)."""
    global _last_evening
    if not (in_session(now) or in_evening(now)):
        return "idle"
    if leader_store is None:
        from services.scan_builder import signals
        leader_store = signals.get_store()
    if not await leader_store.lead(LEADER_KEY, me, LEADER_TTL_S, time.time()):
        return "not_leader"
    deps = deps or default_deps()
    if in_session(now):
        await live_round(now, deps)
        return "live"
    if clock() - _last_evening < EVENING_EVERY_S:
        return "waiting"
    _last_evening = clock()
    await evening_round(now, deps)
    return "evening"


async def _loop() -> None:
    while True:
        now = datetime.now(timezone.utc)
        try:
            what = await loop_once(now)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — one failed round never stops the watcher; logged with its trace
            logger.exception("exit_watch: a round failed")
            what = "failed"
        await asyncio.sleep(loop_seconds() if what == "live" or in_session(datetime.now(timezone.utc)) else IDLE_S)


def start() -> bool:
    """Start the watcher on this worker when enabled (server startup). True if started."""
    global _task
    if not enabled() or (_task is not None and not _task.done()):
        return False
    _task = asyncio.get_running_loop().create_task(_loop())
    logger.info("exit_watch: started (every %.0f s in the session, evening stops after NSE's file, one leader)", loop_seconds())
    return True


def stop() -> None:
    if _task is not None and not _task.done():
        _task.cancel()
