"""The user's paper book, read WITHOUT applying exits, as normalized executions plus the ledger's own figures.

Why not GET /api/desk/paper-trades: that route APPLIES exits (it writes closes and entry fills) before it answers, which is
right for the Live desk's one read per load and wrong for a screen that refreshes every few seconds. This module runs the
same evaluators with `persist=False` (services/desk_trading.apply_trade_exits, services/desk_strategy_trades.apply_exits),
so an exit the end-of-day bars show but nobody has written yet is reported as EXIT DUE instead of being written here.

The trades are serialized by the ledger's own public functions (svc.public_trade / strat.public_strategy_trade), so a fill,
an exit price, a leg's exit mark or a cost figure on this dashboard is the number the Live desk and the journal show.

Cache: the end-of-day part (bars, simulations) changes once a day, so it is kept per user for BOOK_TTL_S, and rebuilt at once
when the user's trades change (a fingerprint of ids, status and updated_at is read on every call, one small query).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from services import desk_strategy_trades as strat
from services import desk_trading as svc

from .ledger import Execution

logger = logging.getLogger(__name__)

BOOK_TTL_S = 300.0
ENTERED = ("assumed", "reached")
SEGMENT_OF_LEG = {"future": "FUTURES", "option": "OPTIONS", "cash": "EQUITY"}

_CACHE: Dict[str, Tuple[float, str, "Book"]] = {}
_LOCKS: Dict[str, asyncio.Lock] = {}


@dataclass
class Leg:
    """One instrument of a trade: the cash trade itself, or one leg of a strategy."""
    position_key: str
    trade_id: str
    leg_index: Optional[int]
    segment: str                       # EQUITY | FUTURES | OPTIONS
    symbol: str                        # the underlying / stock
    instrument: str                    # display name
    kind: str                          # cash | future | option
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None  # call | put
    lots: Optional[float] = None
    lot_size: Optional[float] = None
    eod_mark: Optional[float] = None   # the ledger's end-of-day mark (open) / exit mark (closed)
    eod_date: Optional[str] = None
    eod_basis: Optional[str] = None
    prev_eod: Optional[float] = None   # the session before eod_date's close (cash only; for the day's move)


@dataclass
class TradeItem:
    trade_id: str
    kind: str                          # cash | strategy
    status: str                        # open | closed
    public: Dict[str, Any]
    legs: List[Leg]
    executions: List[Execution]
    entered: bool
    pending_exit: Optional[Dict[str, Any]] = None   # an exit the EOD bars show that the ledger has not written yet
    entry_session: Optional[str] = None


@dataclass
class Book:
    open: List[TradeItem] = field(default_factory=list)
    closed: List[TradeItem] = field(default_factory=list)
    partial: bool = False
    marks_error: Optional[str] = None
    built_at: float = 0.0


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _day(v: Any) -> Optional[str]:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str) and len(v) >= 10:
        return v[:10]
    return None


def leg_instrument(underlying: str, leg: Dict[str, Any]) -> str:
    """'NIFTY 25 Nov 2026 26000 CE', 'NIFTY 25 Nov 2026 FUT', 'RELIANCE' (cash)."""
    kind = leg.get("kind")
    if kind == "cash":
        return underlying
    exp = _day(leg.get("expiry"))
    when = date.fromisoformat(exp).strftime("%d %b %Y") if exp else "?"
    if kind == "future":
        return f"{underlying} {when} FUT"
    strike = _num(leg.get("strike"))
    k = ("%.2f" % strike).rstrip("0").rstrip(".") if strike is not None else "?"
    return f"{underlying} {when} {k} {'CE' if leg.get('option_type') == 'call' else 'PE'}"


def cash_item(pub: Dict[str, Any], bars: Optional[List[Dict[str, Any]]] = None, pending_exit: Optional[Dict[str, Any]] = None) -> TradeItem:
    """A share trade as one position: BUY at the fill once entered, SELL at the exit price once closed."""
    tid, sym = str(pub["id"]), str(pub["symbol"])
    qty = _num(pub.get("quantity")) or 0.0
    status = pub.get("status")
    entered = (pub.get("entry_status") or ("assumed" if (pub.get("entry_rule") or "at_once") == "at_once" else None)) in ENTERED
    fill = _num(pub.get("sim_entry_price")) or (_num(pub.get("entry_price")) if entered else None)
    execs: List[Execution] = []
    if entered and fill and qty > 0:
        execs.append(Execution(f"{tid}:open", tid, 1, qty, fill, at=pub.get("entry_session") or pub.get("opened_at"), kind="fill"))
        exit_price = _num(pub.get("exit_price"))
        if status == "closed" and exit_price is not None:
            execs.append(Execution(f"{tid}:close", tid, -1, qty, exit_price, at=pub.get("closed_at") or pub.get("exit_session"), kind="exit"))
    prev = None
    if bars and status == "open":
        closes = [b for b in bars if b.get("close") is not None]
        if len(closes) >= 2 and _day(closes[-1].get("date")) == pub.get("last_close_date"):
            prev = _num(closes[-2]["close"])
    leg = Leg(position_key=tid, trade_id=tid, leg_index=None, segment="EQUITY", symbol=sym, instrument=sym, kind="cash",
              eod_mark=_num(pub.get("last_close")) if status == "open" else _num(pub.get("exit_price")),
              eod_date=pub.get("last_close_date") if status == "open" else pub.get("exit_session"),
              eod_basis="close", prev_eod=prev)
    return TradeItem(trade_id=tid, kind="cash", status=str(status), public=pub, legs=[leg], executions=execs, entered=entered,
                     pending_exit=pending_exit, entry_session=pub.get("entry_session"))


def strategy_item(pub: Dict[str, Any], pending_exit: Optional[Dict[str, Any]] = None) -> TradeItem:
    """A futures / option structure: one position per leg, opened at the leg's entry price; a closed structure's legs are
    closed at their stored exit marks (the same marks its realized P&L was booked at)."""
    tid, und = str(pub["id"]), str(pub.get("underlying") or pub.get("symbol"))
    status = str(pub.get("status"))
    legs: List[Leg] = []
    execs: List[Execution] = []
    for leg in pub.get("legs") or []:
        i = int(leg["index"])
        key = f"{tid}:{i}"
        lots, size, entry = _num(leg.get("lots")), _num(leg.get("lot_size")), _num(leg.get("entry_price"))
        side = 1 if leg.get("side") == "buy" else -1
        legs.append(Leg(position_key=key, trade_id=tid, leg_index=i, segment=SEGMENT_OF_LEG.get(str(leg.get("kind")), "OPTIONS"),
                        symbol=und, instrument=leg_instrument(und, leg), kind=str(leg.get("kind")), expiry=_day(leg.get("expiry")),
                        strike=_num(leg.get("strike")), option_type=leg.get("option_type"), lots=lots, lot_size=size,
                        eod_mark=_num(leg.get("mark")), eod_date=leg.get("mark_date"), eod_basis=leg.get("mark_basis")))
        if lots and size and entry is not None and lots * size > 0:
            qty = lots * size
            execs.append(Execution(f"{key}:open", key, side, qty, entry, at=pub.get("opened_at"), kind="fill"))
            mark = _num(leg.get("mark"))
            if status == "closed" and mark is not None:
                execs.append(Execution(f"{key}:close", key, -side, qty, mark, at=pub.get("closed_at"), kind="exit"))
    return TradeItem(trade_id=tid, kind="strategy", status=status, public=pub, legs=legs, executions=execs, entered=True,
                     pending_exit=pending_exit, entry_session=_day(pub.get("opened_at")))


async def _fingerprint(db, uid: str) -> str:
    rows = await db[svc.TRADES].find({"user_id": uid}, {"_id": 1, "status": 1, "updated_at": 1, "closed_at": 1}) \
        .to_list(svc.MAX_OPEN_TRADES * 2 + svc.MAX_CLOSED_LISTED + 1)
    text = "|".join(sorted(f"{r['_id']}:{r.get('status')}:{r.get('updated_at')}:{r.get('closed_at')}" for r in rows))
    return hashlib.sha1(text.encode()).hexdigest()


async def _build(db, uid: str) -> Book:
    all_open = await db[svc.TRADES].find({"user_id": uid, "status": "open"}).sort("opened_at", -1).to_list(svc.MAX_OPEN_TRADES * 2)
    cash_open = [d for d in all_open if d.get("kind") != strat.KIND]
    strat_open = [d for d in all_open if d.get("kind") == strat.KIND]
    starts = svc.fetch_starts(cash_open, "opened_at")
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})
    _, counts = await svc.apply_trade_exits(db, cash_open, bars, persist=False)
    _, sims, s_errors = await strat.apply_exits(db, strat_open, persist=False) if strat_open else ([], {}, {})

    book = Book(built_at=time.monotonic())
    for doc in cash_open:
        sim = counts["paths"].get(doc["_id"])
        mark, mark_error = svc.mark_for(doc["symbol"], bars, errors)
        pub = svc.public_trade(doc, mark, mark_error, counts["checked_through"].get(doc["_id"]), sim=sim)
        book.open.append(cash_item(pub, bars.get(doc["symbol"]), pending_exit=(sim or {}).get("exit")))
    for doc in strat_open:
        sim = sims.get(doc["_id"])
        pub = strat.public_strategy_trade(doc, sim, s_errors.get(doc["_id"]))
        book.open.append(strategy_item(pub, pending_exit=(sim or {}).get("exit")))

    closed = await db[svc.TRADES].find({"user_id": uid, "status": "closed"}).sort("closed_at", -1).to_list(svc.MAX_CLOSED_LISTED + 1)
    book.partial = len(closed) > svc.MAX_CLOSED_LISTED
    for doc in closed[: svc.MAX_CLOSED_LISTED]:
        if doc.get("kind") == strat.KIND:
            book.closed.append(strategy_item(strat.public_strategy_trade(doc)))
        else:
            book.closed.append(cash_item(svc.public_trade(doc)))
    book.marks_error = svc.marks_error({**errors, **s_errors}, len(starts) + len(strat_open))
    return book


async def read_book(db, uid: str, *, max_age_s: float = BOOK_TTL_S) -> Book:
    """The user's book; rebuilt when older than `max_age_s` or when any trade changed since it was built."""
    fp = await _fingerprint(db, uid)
    hit = _CACHE.get(uid)
    if hit and hit[1] == fp and time.monotonic() - hit[0] < max_age_s:
        return hit[2]
    lock = _LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        hit = _CACHE.get(uid)
        if hit and hit[1] == fp and time.monotonic() - hit[0] < max_age_s:
            return hit[2]
        book = await _build(db, uid)
        _CACHE[uid] = (time.monotonic(), fp, book)
        return book
