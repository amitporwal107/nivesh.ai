"""The user's paper book, read WITHOUT applying exits, as normalized executions plus the ledger's own figures.

Why not GET /api/desk/paper-trades: that route APPLIES exits (it writes closes and entry fills) before it answers, which is
right for the Live desk's one read per load and wrong for a screen that refreshes every few seconds. This module runs the
same evaluators with `persist=False` (services/desk_trading.apply_trade_exits, services/desk_strategy_trades.apply_exits),
so an exit the end-of-day bars show but nobody has written yet is reported as EXIT DUE instead of being written here.

The trades are serialized by the ledger's own public functions (svc.public_trade / strat.public_strategy_trade), so a fill,
an exit price, a leg's exit mark or a cost figure on this dashboard is the number the Live desk and the journal show.

Cache: the end-of-day part (bars, simulations) changes once a day, so it is kept per user for BOOK_TTL_S, and rebuilt at once
when the user's trades change (a fingerprint of ids, status and updated_at is read on every call, one small query).

SCANNER (SPT) POSITIONS (Scanner-to-Paper Trading, slice C: services/spt/paper/positions.py) are in the same book as cash
share trades (`source` "scanner" on the item; "desk" for the desk's own): every `spt_positions` document not CLOSED is open,
the CLOSED ones are closed trades. Their executions are the position's OWN applied fills (`fill_ids`), read from its entry
order and its exit orders (`spt_orders.fills`), each at its recorded traded value ÷ quantity (slippage in the price, as C
books it); charges are the fills' recorded costs (dashboard.leg_charges). The booked realised P&L of a closed one is C's
`realized_gross_rs` (exit proceeds − entry cost) and `realized_net_rs` (net of every fill's charges). Their end-of-day mark
comes from the same bars read as the desk's share trades. Unlike desk trades, SPT fills and exits happen in the session on
live quotes (slice C's monitor); nothing here applies or writes them. A failed SPT read leaves them out and says so
(`Book.spt_error`), never silently.

SETUP TYPE OF A SCANNER POSITION (Paper Trading v2 "P&L by strategy"): an SPT position stores no setup field, so its
opportunity's stored `category` (spt_opportunities.category, slice A: breakout / reversal / momentum / …) is read — ONE
query for all of the user's positions per book build (`_spt_setup_types`), kept on the item as `setup_type`. A missing
opportunity, or a failed read (logged), leaves it null; it is never inferred.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from services import desk_strategy_trades as strat
from services import desk_trading as svc
from services.kite_live_feed import config as kcfg

from .ledger import Execution

logger = logging.getLogger(__name__)

BOOK_TTL_S = 300.0
#: Slice C's stores (services/spt/constants.POSITIONS / ORDERS); read only here.
SPT_POSITIONS, SPT_ORDERS, SPT_OPPORTUNITIES = "spt_positions", "spt_orders", "spt_opportunities"
SPT_CLOSED_STATE = "CLOSED"
SPT_MAX_POSITIONS = 2000
SPT_LOOKBACK_DAYS = 10
DESK, SCANNER = "desk", "scanner"
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
    tradingsymbol: Optional[str] = None  # a broker row's own Kite F&O symbol (LIVE positions): priced by it directly


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
    source: str = DESK                              # desk | scanner (an SPT paper position, slice C)


@dataclass
class Book:
    open: List[TradeItem] = field(default_factory=list)
    closed: List[TradeItem] = field(default_factory=list)
    partial: bool = False
    marks_error: Optional[str] = None
    built_at: float = 0.0
    spt_error: Optional[str] = None                 # the scanner positions could not be read: they are left out, said so


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


def _ist_date(stamp: Any) -> Optional[str]:
    """The IST day of an ISO stamp (a naive stamp is IST, as slice C reads them)."""
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return _day(stamp)
    return (d if d.tzinfo else d.replace(tzinfo=kcfg.IST)).astimezone(kcfg.IST).date().isoformat()


def spt_item(pos: Dict[str, Any], fills: List[Tuple[Dict[str, Any], int]],
             bars: Optional[List[Dict[str, Any]]] = None, setup_type: Optional[str] = None) -> TradeItem:
    """A scanner (SPT) paper position as one cash position (see the module docstring). `fills` = (fill record, side) of the
    position's entry order (+1) and exit orders (-1); only the fills the position applied (`fill_ids`) are used."""
    pid, sym = str(pos["_id"]), str(pos.get("symbol") or "").upper()
    is_open = pos.get("state") != SPT_CLOSED_STATE
    applied = set(pos.get("fill_ids") or [])
    execs: List[Execution] = []
    for rec, side in sorted(fills, key=lambda fs: (str(fs[0].get("at") or ""), int(fs[0].get("seq") or 0))):
        fid = rec.get("fill_id")
        q, value = _num(rec.get("quantity")), _num(rec.get("value_rs"))
        price = (value / q) if (q and value is not None) else _num(rec.get("price"))
        if fid not in applied or not q or q <= 0 or price is None:
            continue
        execs.append(Execution(str(fid), pid, side, q, price, at=rec.get("at"), kind="fill" if side > 0 else "exit"))
    stop = _num(pos.get("stop_loss"))
    target = _num(pos.get("target_2") if pos.get("t1_done") else pos.get("target_1"))
    entry_costs, exit_costs = _num(pos.get("entry_costs_rs")) or 0.0, _num(pos.get("exit_costs_rs")) or 0.0
    exit_qty = _num(pos.get("exit_qty")) or 0.0
    exit_avg = round(_num(pos.get("exit_value_rs")) / exit_qty, 4) if exit_qty and _num(pos.get("exit_value_rs")) is not None else None
    pend = pos.get("pending_exit") if isinstance(pos.get("pending_exit"), dict) else None
    pending = {"exit_reason": pend.get("reason"), "exit_session": pend.get("day"), "scanner": True} if pend else None
    mark = svc.last_close(bars or []) if is_open else None
    prev = None
    if bars and is_open:
        closes = [b for b in bars if b.get("close") is not None]
        if len(closes) >= 2:
            prev = _num(closes[-2]["close"])
    ids = {"opportunity_id": pos.get("opportunity_id"), "proposal_id": pos.get("proposal_id"),
           "order_id": pos.get("entry_order_id")}
    pub: Dict[str, Any] = {
        "id": pid, "kind": "cash", "symbol": sym, "status": "open" if is_open else "closed",
        "quantity": int(_num(pos.get("quantity")) or 0) if is_open else int(_num(pos.get("entry_qty")) or 0),
        "entry_price": _num(pos.get("avg_entry_price")), "sim_entry_price": _num(pos.get("avg_entry_price")),
        "entry_status": "assumed", "entry_rule": "scanner", "entry_session": _ist_date(pos.get("opened_at")),
        "stop_price": stop, "current_stop": stop, "target_price": target, "current_target": target,
        "initial_stop": _num(pos.get("initial_stop")), "target_1": _num(pos.get("target_1")),
        "target_2": _num(pos.get("target_2")), "t1_done": bool(pos.get("t1_done")),
        "opened_at": pos.get("opened_at"), "closed_at": pos.get("closed_at"),
        "exit_price": exit_avg, "exit_session": _ist_date(pos.get("closed_at")), "exit_reason": pos.get("exit_reason"),
        "realized_pnl_rs": _num(pos.get("realized_gross_rs")) if not is_open else None,
        "costs_rs": round(entry_costs + exit_costs, 2) if not is_open else None,
        "net_pnl_rs": _num(pos.get("realized_net_rs")) if not is_open else None,
        "held_sessions": pos.get("sessions_held"), "entry_qty": _num(pos.get("entry_qty")), "exit_qty": exit_qty,
        "entry_costs_rs": entry_costs, "exit_costs_rs": exit_costs, "cost_model": pos.get("cost_model"),
        "last_close": _num(mark["close"]) if mark else None,
        "last_close_date": _day(mark["date"]) if mark else None,
        # A dict, like a desk trade's own `source` (the journal reads it): where this position came from.
        "source": {"kind": SCANNER, **ids}, **ids,
        "spt_position_id": pid, "spt_state": pos.get("state"), "r_multiple": (pos.get("outcome") or {}).get("r_multiple"),
        # the opportunity's stored category (module docstring, SETUP TYPE); None when it could not be read
        "setup_type": setup_type,
        # an open position whose fills could not be matched is shown as missing, never as flat (dashboard alert)
        "fills_missing": bool(is_open and not execs),
    }
    leg = Leg(position_key=pid, trade_id=pid, leg_index=None, segment="EQUITY", symbol=sym, instrument=sym, kind="cash",
              eod_mark=pub["last_close"] if is_open else exit_avg,
              eod_date=pub["last_close_date"] if is_open else pub["exit_session"], eod_basis="close", prev_eod=prev)
    return TradeItem(trade_id=pid, kind="cash", status=pub["status"], public=pub, legs=[leg], executions=execs,
                     entered=True, pending_exit=pending, entry_session=pub["entry_session"], source=SCANNER)


async def _spt_docs(db, uid: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, List[Tuple[Dict[str, Any], int]]]]:
    """(open SPT positions, closed ones newest first, {position id: [(fill, side)]}) of the user."""
    docs = await db[SPT_POSITIONS].find({"user_id": uid}).to_list(SPT_MAX_POSITIONS)
    open_ = [d for d in docs if d.get("state") != SPT_CLOSED_STATE]
    closed = sorted((d for d in docs if d.get("state") == SPT_CLOSED_STATE), key=lambda d: str(d.get("closed_at") or ""),
                    reverse=True)
    fills: Dict[str, List[Tuple[Dict[str, Any], int]]] = {}
    if docs:
        entry = {d.get("entry_order_id"): str(d["_id"]) for d in docs if d.get("entry_order_id")}
        pids = [str(d["_id"]) for d in docs]
        orders = await db[SPT_ORDERS].find({"user_id": uid, "$or": [{"_id": {"$in": list(entry)}},
                                                                    {"position_id": {"$in": pids}, "purpose": "EXIT"}]}) \
            .to_list(SPT_MAX_POSITIONS * 4)
        for o in orders:
            if o.get("purpose") == "EXIT":
                pid, side = o.get("position_id"), -1
            else:
                pid, side = entry.get(o.get("_id")), 1
            if pid:
                fills.setdefault(str(pid), []).extend((dict(f), side) for f in o.get("fills") or [])
    return open_, closed, fills


async def _spt_setup_types(db, docs: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """{opportunity id: its stored `category`} for these positions: one read. {} when it fails (logged)."""
    ids = sorted({str(d["opportunity_id"]) for d in docs if d.get("opportunity_id")})
    if not ids:
        return {}
    try:
        rows = await db[SPT_OPPORTUNITIES].find({"_id": {"$in": ids}}).to_list(len(ids))
    except Exception as e:  # noqa: BLE001 — the positions still show; their setup type is null
        logger.warning("paper_pnl: the scanner opportunities could not be read for setup types (%s)", type(e).__name__)
        return {}
    return {str(r["_id"]): (r.get("category") if isinstance(r.get("category"), str) and r.get("category").strip() else None)
            for r in rows}


async def _fingerprint(db, uid: str) -> str:
    rows = await db[svc.TRADES].find({"user_id": uid}, {"_id": 1, "status": 1, "updated_at": 1, "closed_at": 1}) \
        .to_list(svc.MAX_OPEN_TRADES * 2 + svc.MAX_CLOSED_LISTED + 1)
    text = "|".join(sorted(f"{r['_id']}:{r.get('status')}:{r.get('updated_at')}:{r.get('closed_at')}" for r in rows))
    try:
        spt = await db[SPT_POSITIONS].find({"user_id": uid}).to_list(SPT_MAX_POSITIONS)
        text += "|spt|" + "|".join(sorted(f"{r['_id']}:{r.get('state')}:{r.get('version')}:{r.get('updated_at')}" for r in spt))
    except Exception as e:  # noqa: BLE001 — the build reports it (Book.spt_error); the fingerprint just changes each time
        text += f"|spt-unreadable:{type(e).__name__}:{time.monotonic()}"
    return hashlib.sha1(text.encode()).hexdigest()


async def _build(db, uid: str) -> Book:
    all_open = await db[svc.TRADES].find({"user_id": uid, "status": "open"}).sort("opened_at", -1).to_list(svc.MAX_OPEN_TRADES * 2)
    cash_open = [d for d in all_open if d.get("kind") != strat.KIND]
    strat_open = [d for d in all_open if d.get("kind") == strat.KIND]
    starts = svc.fetch_starts(cash_open, "opened_at")
    spt_error = None
    try:
        spt_open, spt_closed, spt_fills = await _spt_docs(db, uid)
    except Exception as e:  # noqa: BLE001 — left out and said so (Book.spt_error), never silently
        logger.warning("paper_pnl: the scanner (SPT) positions of a user could not be read (%s)", type(e).__name__)
        spt_open, spt_closed, spt_fills, spt_error = [], [], {}, f"the scanner paper positions could not be read ({type(e).__name__})"
    setups = await _spt_setup_types(db, spt_open + spt_closed)
    for d in spt_open:                                      # their end-of-day marks: the same bars read
        sym, opened = str(d.get("symbol") or "").upper(), _ist_date(d.get("opened_at"))
        if sym and opened:
            start = date.fromisoformat(opened) - timedelta(days=SPT_LOOKBACK_DAYS)
            if sym not in starts or start < starts[sym]:
                starts[sym] = start
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})
    _, counts = await svc.apply_trade_exits(db, cash_open, bars, persist=False)
    _, sims, s_errors = await strat.apply_exits(db, strat_open, persist=False) if strat_open else ([], {}, {})

    book = Book(built_at=time.monotonic(), spt_error=spt_error)
    for doc in cash_open:
        sim = counts["paths"].get(doc["_id"])
        mark, mark_error = svc.mark_for(doc["symbol"], bars, errors)
        pub = svc.public_trade(doc, mark, mark_error, counts["checked_through"].get(doc["_id"]), sim=sim)
        book.open.append(cash_item(pub, bars.get(doc["symbol"]), pending_exit=(sim or {}).get("exit")))
    for doc in strat_open:
        sim = sims.get(doc["_id"])
        pub = strat.public_strategy_trade(doc, sim, s_errors.get(doc["_id"]))
        book.open.append(strategy_item(pub, pending_exit=(sim or {}).get("exit")))
    for doc in spt_open:
        book.open.append(spt_item(doc, spt_fills.get(str(doc["_id"])) or [], bars.get(str(doc.get("symbol") or "").upper()),
                                  setup_type=setups.get(str(doc.get("opportunity_id") or ""))))

    closed = await db[svc.TRADES].find({"user_id": uid, "status": "closed"}).sort("closed_at", -1).to_list(svc.MAX_CLOSED_LISTED + 1)
    book.partial = len(closed) > svc.MAX_CLOSED_LISTED
    for doc in closed[: svc.MAX_CLOSED_LISTED]:
        if doc.get("kind") == strat.KIND:
            book.closed.append(strategy_item(strat.public_strategy_trade(doc)))
        else:
            book.closed.append(cash_item(svc.public_trade(doc)))
    book.partial = book.partial or len(spt_closed) > svc.MAX_CLOSED_LISTED
    for doc in spt_closed[: svc.MAX_CLOSED_LISTED]:
        book.closed.append(spt_item(doc, spt_fills.get(str(doc["_id"])) or [],
                                    setup_type=setups.get(str(doc.get("opportunity_id") or ""))))
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
