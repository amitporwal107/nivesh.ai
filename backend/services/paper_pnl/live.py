"""LIVE (broker) positions on the P&L dashboard (docs/paper_pnl_dashboard/DESIGN.md "v2"; owner 4 Nov 2026: Live, read-only).

Source: every connected broker account's NET positions, read through the Open positions workspace's own read
(services/positions/service.read_broker — the read My portfolio uses; it snapshots changed reads). Read-only towards brokers:
nothing here places, modifies or cancels an order, and no order function is imported. Long-term holdings are not positions here.

Cadence: the broker read is cached per user for PNL_BROKER_TTL_S (60 s) while the prices move with the live feed every few
seconds: quantity, average and product are the broker's from its last read; the price and its status come from the SAME resolver
as paper (services/paper_pnl/prices.resolve), each contract named as an NSE instrument by services/positions/symbols (ICICI
Direct's stock codes differ from NSE's: SONBLW = SONACOMS) and, for a Zerodha row, by its own Kite symbol.

Figures per position: unrealized = (LTP − average) × signed quantity; realized = null (the brokers' position reads do not split
their realised part, so none is shown rather than a mixed figure; `broker_pnl` is the broker's own total on its read); estimated
charges = the desk cost card (services/desk_cost_card.py) for the opening side at the average and the closing side at the price
shown. A row whose contract cannot be named and that has no price at all is MISSING (left out of the totals, said so); one that
cannot be named but carries the broker's own last price is priced at it, labelled as the broker's.

Account state: OK · STALE (the read shown is older than 2 × TTL: a later read failed) · SIGN_IN (the broker session ended or the
account is not connected for live reads) · ERROR (the read failed, or the broker cannot be read live) · OFF (broker connections
are not enabled for the user). A failed read never fails the snapshot.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from services import desk_cost_card as cost_card
from services import desk_trading as svc

from .book import Leg
from .prices import DELAYED, MISSING, Quote

logger = logging.getLogger(__name__)

MODE = "LIVE"
SEGMENT_OF = {"EQ": "EQUITY", "FUT": "FUTURES", "CE": "OPTIONS", "PE": "OPTIONS"}
KIND_OF = {"EQ": "cash", "FUT": "future", "CE": "option", "PE": "option"}
CARD_SEGMENT = {"EQ": "equity_delivery", "FUT": "futures", "CE": "options", "PE": "options"}
EXECUTIONS_NOTE = ("Fills are not read for broker positions here: the brokers send only the current day's trade book. "
                   "The quantity and average are the broker's own.")
REALIZED_NOTE = ("Brokers' position reads do not split realised P&L from their own total, so live rows show open P&L at the "
                 "price shown (net of estimated charges) and the broker's own figure beside it.")
CAPITAL_BASIS = "Broker account capital is not read here, so no return % is worked out for live positions."

STATE_OK, STATE_STALE, STATE_SIGN_IN, STATE_ERROR, STATE_OFF = "OK", "STALE", "SIGN_IN", "ERROR", "OFF"


def ttl_seconds() -> float:
    try:
        return max(5.0, float(os.environ.get("PNL_BROKER_TTL_S", "60")))
    except ValueError:
        return 60.0


async def _read(request: Any, db, uid: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The positions workspace's read (entries, open rows). Patched in tests."""
    from services.positions import service as positions_service
    return await positions_service.read_broker(request, db, uid)


@dataclass
class BrokerBook:
    """One user's broker read: the accounts (read_broker's source entries) and their open rows, as last read."""
    entries: List[Dict[str, Any]] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    read_mono: Optional[float] = None
    error: Optional[str] = None                      # the whole read failed and nothing earlier was kept


_CACHE: Dict[str, BrokerBook] = {}
_LOCKS: Dict[str, asyncio.Lock] = {}


def _merge(old: Optional[BrokerBook], entries: List[Dict[str, Any]], rows: List[Dict[str, Any]], mono: float) -> BrokerBook:
    """A new read, keeping an account's earlier rows when only this read of it failed transiently (its entry keeps the earlier
    read time, so it turns STALE after 2 × TTL). A session that ended keeps nothing."""
    from services.brokers import hub_reads as hub
    if old is None:
        return BrokerBook(list(entries), list(rows), mono)
    kept_rows = list(rows)
    out_entries = []
    for e in entries:
        failed = not e.get("ok") and (e.get("error") or {}).get("code") == hub.CODE_READ_FAILED
        prev = next((p for p in old.entries if p.get("account_id") and p.get("account_id") == e.get("account_id")
                     and p.get("ok")), None)
        if failed and prev is not None:
            out_entries.append({**prev, "refresh_error": e.get("error")})
            kept_rows.extend(r for r in old.rows if r.get("_account_id") == e.get("account_id"))
        else:
            out_entries.append(e)
    return BrokerBook(out_entries, kept_rows, mono)


async def read_broker_book(request: Any, db, uid: str, *, reader: Optional[Callable[..., Awaitable[Any]]] = None,
                           ttl: Optional[float] = None) -> BrokerBook:
    """The user's broker book, read at most once per TTL. Never raises."""
    ttl = ttl_seconds() if ttl is None else ttl
    hit = _CACHE.get(uid)
    if hit is not None and hit.read_mono is not None and time.monotonic() - hit.read_mono < ttl:
        return hit
    lock = _LOCKS.setdefault(uid, asyncio.Lock())
    async with lock:
        hit = _CACHE.get(uid)
        if hit is not None and hit.read_mono is not None and time.monotonic() - hit.read_mono < ttl:
            return hit
        try:
            entries, rows = await (reader or _read)(request, db, uid)
        except Exception as e:  # noqa: BLE001 — the snapshot answers without live positions and says why
            logger.warning("paper_pnl: broker positions unreadable (%s)", type(e).__name__)
            if hit is not None and hit.entries:
                # Keep the last read (its accounts turn STALE by the age of their read) and try again after a TTL, so a
                # broker that is down is not asked again on every pass of the stream.
                hit.read_mono = time.monotonic()
                return hit
            book = BrokerBook(error=f"Broker accounts could not be read ({type(e).__name__}).", read_mono=time.monotonic())
            _CACHE[uid] = book
            return book
        book = _merge(hit, entries, rows, time.monotonic())
        _CACHE[uid] = book
        return book


# ── accounts ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _age_seconds(stamp: Optional[str], now: datetime) -> Optional[float]:
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (now - d).total_seconds()


def account_state(entry: Dict[str, Any], now: datetime, ttl: Optional[float] = None) -> Tuple[str, Optional[str]]:
    """(state, note) of one broker account entry."""
    from services.brokers import hub_reads as hub
    ttl = ttl_seconds() if ttl is None else ttl
    err = entry.get("error") or {}
    code = err.get("code")
    if entry.get("ok"):
        age = _age_seconds(entry.get("read_at"), now)
        if age is not None and age > 2 * ttl:
            return STATE_STALE, f"Last read {int(age)} s ago; the latest read failed. Positions are as of that read."
        return STATE_OK, None
    if code == "BROKER_HUB_OFF":
        return STATE_OFF, err.get("message") or "Broker connections are not enabled for this account."
    if code == hub.CODE_SESSION_EXPIRED:
        return STATE_SIGN_IN, err.get("message") or "The broker session has ended: sign in again."
    return STATE_ERROR, err.get("message") or "The broker could not be read."


def accounts(book: BrokerBook, now: datetime) -> List[Dict[str, Any]]:
    """One entry per broker account (open_positions and net_pnl are filled by the dashboard from the priced rows)."""
    out = []
    for e in book.entries:
        if not e.get("account_id"):
            continue                                    # the hub-off entry names no account
        state, note = account_state(e, now)
        out.append({"account_id": str(e["account_id"]), "name": e.get("broker_display") or e.get("label") or e.get("broker") or "Broker",
                    "mode": MODE, "broker": e.get("broker"), "state": state, "state_note": note, "read_at": e.get("read_at"),
                    "capital": None, "capital_basis": CAPITAL_BASIS, "open_positions": 0, "net_pnl": None})
    return out


def unavailable_note(book: BrokerBook, accts: List[Dict[str, Any]]) -> Optional[str]:
    """Why no live position can be shown, or None when at least one account is readable."""
    if book.error:
        return book.error
    off = next((e for e in book.entries if not e.get("account_id") and (e.get("error") or {}).get("code") == "BROKER_HUB_OFF"), None)
    if off is not None:
        return (off.get("error") or {}).get("message") or "Broker connections are not enabled for this account."
    if not accts:
        return "No broker account is connected."
    if any(a["state"] in (STATE_OK, STATE_STALE) for a in accts):
        return None
    return "No broker account could be read: " + "; ".join(f"{a['name']}: {a['state_note'] or a['state'].lower()}" for a in accts)


# ── positions ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _pos(v: Any) -> Optional[float]:
    f = _num(v)
    return f if f is not None and f > 0 else None


def position_key(row: Dict[str, Any]) -> str:
    """Stable across reads: the account, the exchange, the broker's symbol and its product (a symbol can be held under two)."""
    return ":".join(["live", str(row.get("_account_id") or "?"), str(row.get("exchange") or "?").upper(),
                     str(row.get("symbol") or "?").upper(), str(row.get("product_raw") or row.get("product") or "-").upper()])


@dataclass
class LiveLeg:
    leg: Leg
    row: Dict[str, Any]
    instrument_type: str               # EQ | FUT | CE | PE
    mapped: bool
    problem: Optional[str]


def legs(book: BrokerBook) -> List[LiveLeg]:
    """One Leg per open broker row, named as an NSE instrument where possible."""
    from services.positions import symbols
    out: List[LiveLeg] = []
    for r in book.rows:
        broker = r.get("_broker") or ""
        try:
            c = symbols.normalise(r, broker)
        except Exception as e:  # noqa: BLE001 — a row that cannot be named is still listed, unpriced unless the broker priced it
            logger.warning("paper_pnl: broker row not named (%s)", type(e).__name__)
            c = symbols.Contract(str(r.get("symbol") or ""), "EQ", mapped=False, problem="the row could not be read as an instrument")
        itype = c.instrument if c.instrument in SEGMENT_OF else "EQ"
        code = str(r.get("symbol") or "").upper()
        zerodha = broker.lower() in symbols.ZERODHA_SLUGS
        ts = code if (zerodha and itype != "EQ" and c.mapped) else None
        try:
            name = symbols.label(c) if c.mapped and (c.expiry or itype == "EQ") else (code or c.underlying)
        except Exception:  # noqa: BLE001
            name = code or c.underlying
        leg = Leg(position_key=position_key(r), trade_id=position_key(r), leg_index=None, segment=SEGMENT_OF[itype],
                  symbol=c.underlying or code, instrument=name, kind=KIND_OF[itype], expiry=c.expiry, strike=c.strike,
                  option_type={"CE": "call", "PE": "put"}.get(itype), tradingsymbol=ts)
        if not c.mapped:
            # An unnamed contract never reaches the resolver as a contract: nothing could be priced for it but a wrong symbol.
            leg.kind = "unmapped"
        out.append(LiveLeg(leg, r, itype, c.mapped, c.problem))
    return out


def priceable(lives: List[LiveLeg]) -> List[Leg]:
    return [l.leg for l in lives if l.mapped]


def fill_expiries(lives: List[LiveLeg], expiry_of: Callable[[Optional[str]], Optional[str]]) -> None:
    """A Zerodha monthly symbol names a month: its day from Kite's instrument list once the resolver loaded it."""
    from services.positions import symbols
    for l in lives:
        if l.leg.expiry or not l.leg.tradingsymbol:
            continue
        day = expiry_of(l.leg.tradingsymbol)
        if day:
            l.leg.expiry = day
            try:
                l.leg.instrument = symbols.label(symbols.Contract(l.leg.symbol, l.instrument_type, expiry=day, strike=l.leg.strike))
            except Exception:  # noqa: BLE001
                pass


def charges(itype: str, qty: float, avg: Optional[float], ltp: Optional[float]) -> Optional[float]:
    """Round trip under the desk cost card: the opening side at the average, the closing side at the price shown."""
    if avg is None or ltp is None or not qty:
        return None
    seg = CARD_SEGMENT.get(itype, "equity_delivery")
    opening = "BUY" if qty > 0 else "SELL"
    closing = "SELL" if qty > 0 else "BUY"
    total = cost_card.add(cost_card.order_side(seg, opening, abs(qty) * avg, svc.COST_MODEL),
                          cost_card.order_side(seg, closing, abs(qty) * ltp, svc.COST_MODEL))["total"]
    return round(total, 2)


def _broker_quote(row: Dict[str, Any], now: datetime, today: str) -> Optional[Quote]:
    px = _pos(row.get("last_price"))
    if px is None:
        return None
    age = _age_seconds(row.get("_read_at"), now)
    return Quote(ltp=px, prev_close=None, status=DELAYED, source="Broker's last price on its read", at=row.get("_read_at"),
                 age_seconds=None if age is None else round(age, 1), day=today)


def position_rows(lives: List[LiveLeg], quotes: Dict[str, Quote], *, today: str, now: datetime) -> List[Dict[str, Any]]:
    """The dashboard's position rows for the broker legs (same keys as the paper rows, plus the v2 fields)."""
    out = []
    for l in lives:
        r, leg = l.row, l.leg
        qty = _num(r.get("quantity")) or 0.0
        avg = _pos(r.get("avg_price"))
        q = quotes.get(leg.position_key) if l.mapped else None
        if q is None or q.ltp is None:
            q = _broker_quote(r, now, today) or q or Quote(None, None, MISSING, None, None, None, None)
        ltp = q.ltp
        unreal = round((ltp - avg) * qty, 2) + 0.0 if ltp is not None and avg is not None else None
        ch = charges(l.instrument_type, qty, avg, ltp)
        net = None if unreal is None or ch is None else round(unreal - ch, 2)
        invested = round(abs(qty) * avg, 2) if avg is not None else None
        status = "ACTIVE"
        if leg.expiry and leg.expiry == today:
            status = "EXPIRES_TODAY"
        out.append({
            "position_id": leg.position_key, "trade_id": leg.trade_id, "leg_index": None, "strategy_id": None, "strategy_name": None,
            "mode": MODE, "account_id": str(r.get("_account_id") or ""), "account": r.get("_broker_display") or r.get("_broker") or "Broker",
            "instrument": leg.instrument, "symbol": leg.symbol, "underlying": leg.symbol, "segment": leg.segment,
            "side": "LONG" if qty > 0 else "SHORT", "net_quantity": qty, "lots": None, "lot_size": None,
            "avg_price": avg, "ltp": ltp, "prev_close": q.prev_close, "price_status": q.status, "price_source": q.source,
            "price_at": q.at, "price_age_seconds": q.age_seconds, "price_day": q.day,
            "invested_value": invested, "unrealized_pnl": unreal, "realized_pnl": None, "gross_pnl": unreal,
            "charges_estimated": ch, "net_pnl": net, "day_pnl": None,
            "return_pct": round(net / invested * 100, 2) if net is not None and invested else None,
            "stop_loss": None, "target": None, "distance_to_stop_pct": None, "risk_used_pct": None,
            "status": status, "opened_at": None, "expiry": leg.expiry, "executions": [],
            "broker_pnl": _num(r.get("pnl")), "broker_read_at": r.get("_read_at"),
            "product": r.get("product"), "exposure_rs": round(abs(qty * ltp), 2) if ltp is not None else None,
            "editable_levels": False, "pending_levels": None, "executions_note": EXECUTIONS_NOTE,
            "contract_problem": None if l.mapped else (l.problem or "the contract could not be named"),
        })
    return out


@dataclass
class LiveView:
    """What the dashboard needs from the broker side: priced rows, the accounts and why Live is unavailable (or None)."""
    positions: List[Dict[str, Any]] = field(default_factory=list)
    accounts: List[Dict[str, Any]] = field(default_factory=list)
    note: Optional[str] = None
    legs: List[LiveLeg] = field(default_factory=list)

    @property
    def account_ids(self) -> List[str]:
        return [a["account_id"] for a in self.accounts]
