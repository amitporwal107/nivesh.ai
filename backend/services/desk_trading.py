"""Smart trading desk — the shared logic behind the user's own paper trades and price alerts.

Used by `routes/desk_trading.py` (per user, on every read) and `scripts/check_desk_alerts.py` (all users, once
a weekday evening). Nothing here places an order or talks to a broker: a paper trade is a record the user keeps,
and an alert is a level the user wants to hear about, shown in the app's alerts list only.

Store (MongoDB, every document carries the owner's `user_id`; ids are uuid4 strings kept in `_id`):
    desk_paper_trades   symbol, quantity, entry_price, stop_price, target_price, note, source,
                        opened_at, status ("open" | "closed"), closed_at, exit_price,
                        exit_reason ("stop" | "target" | "manual"), exit_session, exit_note,
                        realized_pnl_rs, created_at, updated_at
    desk_price_alerts   symbol, condition ("above" | "below"), level, note, created_at,
                        status ("active" | "fired"), fired_at, fired_session, fired_price, updated_at

Prices: END-OF-DAY daily bars (high, low, close) of raw traded prices from the data platform —
GET /v1/prices/eod/{symbol} (nidp.prices_eod, NSE bhavcopy). Raw, not split-adjusted, because users type the
prices they would really trade at. NSE files more than one row per stock on some days (the block-deal
window "BL", bond series), so one bar per session is kept, from the first series in `SERIES_PREFERENCE`;
other series are ignored. A price that is missing stays None; nothing is ever filled in.

Rules (all on end-of-day bars, from the first session strictly after the IST calendar date the trade was
opened / the alert was created):
    paper trade   low <= stop → closed at the stop ("stop"); high >= target → closed at the target
                  ("target"); both inside one session's range → the stop (we cannot tell which came first
                  from a daily bar, so the conservative reading is taken and the trade says so).
                  A gap through the stop would fill worse in a real market; the paper fill is the stop.
    alert         above: high >= level · below: low <= level → fired, fired_price = the level,
                  fired_session = that session.
A session whose high or low is missing ends the scan: later sessions are not checked until it is
readable, so an exit is never found by skipping a session that could have held an earlier one.
Exits and firings are written with the status in the update filter, so running the check twice (the GET,
the evening script, two tabs) never closes or fires anything twice and never overwrites a manual close.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

TRADES = "desk_paper_trades"
ALERTS = "desk_price_alerts"

MAX_OPEN_TRADES = 100
MAX_ACTIVE_ALERTS = 50
MAX_CLOSED_LISTED = 2000          # newest closed trades read per request; the summary says when there are more
MAX_FIRED_LISTED = 1000
MAX_QUANTITY = 1_000_000
MAX_PRICE = 10_000_000.0          # ₹1 crore a share; anything above is a typing slip
NOTE_MAX = 500

SOURCE = "NSE end-of-day bhavcopy, raw traded prices (nidp.prices_eod via the data platform)"
PRICE_BASIS = "end of day"
EXIT_RULE = (
    "Checked on end-of-day bars from the first session after the IST date the trade was opened: a low at or "
    "below the stop closes it at the stop, a high at or above the target closes it at the target, and a session "
    "that touched both counts as the stop (conservative: a daily bar does not show which came first)."
)
FIRING_RULE = (
    "Checked on end-of-day bars from the first session after the IST date the alert was made: 'above' fires "
    "when a session's high reaches the level, 'below' when its low reaches it. Shown in this list only."
)
BOTH_IN_RANGE_NOTE = "The stop and the target were both inside this session's range; counted as the stop (conservative)."

# Normal-market equity series, most preferred first. BL (block-deal window) and debt series are not used.
SERIES_PREFERENCE = ("EQ", "BE", "BZ", "SM", "ST", "IV", "RR")
_SERIES_RANK = {s: i for i, s in enumerate(SERIES_PREFERENCE)}

LOOKBACK_DAYS = 14                # bars read from this many days before the earliest open date (for the last close)
PAGE_LIMIT = 5000                 # the data platform's largest page
MAX_PAGES = 5
FETCH_CONCURRENCY = 8
FETCH_TIMEOUT_S = 15.0

IST = timezone(timedelta(hours=5, minutes=30))

# Error codes sent to the client.
PRICES_UNAVAILABLE = "prices_unavailable"
PRICES_PARTIAL = "prices_partially_unavailable"
NO_PRICES = "no_prices_for_symbol"

_SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
_KIND_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_TRADE_FIELDS = {"symbol", "quantity", "entry_price", "stop_price", "target_price", "note", "source"}
_ALERT_FIELDS = {"symbol", "condition", "level", "note"}
_SOURCE_FIELDS = {"kind", "bucket", "signal_date"}

_indexes_ready = False


class DeskInputError(ValueError):
    """A request body that cannot be stored; `code` is what the client is told."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class PricesUnavailable(RuntimeError):
    """The data platform could not be read (not configured, unreachable, or an unexpected answer)."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


async def ensure_indexes(db) -> None:
    """Indexes on (user_id, status) for the per-user reads and (status, symbol) for the evening check.
    Asked for once per process; a failure is logged and asked for again on the next call."""
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        for name in (TRADES, ALERTS):
            await db[name].create_index([("user_id", 1), ("status", 1)])
            await db[name].create_index([("status", 1), ("symbol", 1)])
        _indexes_ready = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("desk_trading: the indexes could not be created: %r", exc)


# ── validation ───────────────────────────────────────────────────────────────
def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def clean_symbol(raw: Any) -> str:
    symbol = raw.strip().upper() if isinstance(raw, str) else ""
    if not _SYMBOL_RE.match(symbol):
        raise DeskInputError("invalid_symbol")
    return symbol


def clean_price(raw: Any, code: str) -> float:
    number = _number(raw)
    if number is None or number <= 0 or number > MAX_PRICE:
        raise DeskInputError(code)
    return number


def clean_quantity(raw: Any) -> int:
    number = _number(raw)
    if number is None or not number.is_integer() or not 1 <= number <= MAX_QUANTITY:
        raise DeskInputError("invalid_quantity")
    return int(number)


def clean_note(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > NOTE_MAX * 2:
        raise DeskInputError("invalid_note")
    note = raw.strip()
    if len(note) > NOTE_MAX:
        raise DeskInputError("invalid_note")
    return note or None


def clean_source(raw: Any) -> Optional[Dict[str, Any]]:
    """{kind, bucket?, signal_date?} — where the idea came from (a scanner bucket, a pick). Informational only."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - _SOURCE_FIELDS:
        raise DeskInputError("invalid_source")
    kind = raw.get("kind")
    if not isinstance(kind, str) or not _KIND_RE.match(kind):
        raise DeskInputError("invalid_source")
    bucket = raw.get("bucket")
    if bucket is not None:
        if not isinstance(bucket, str) or _CONTROL_RE.search(bucket) or not 1 <= len(bucket.strip()) <= 60:
            raise DeskInputError("invalid_source")
        bucket = bucket.strip()
    signal_date = raw.get("signal_date")
    if signal_date is not None:
        try:
            signal_date = date.fromisoformat(signal_date).isoformat() if isinstance(signal_date, str) and len(signal_date) == 10 else None
        except ValueError:
            signal_date = None
        if signal_date is None:
            raise DeskInputError("invalid_source")
    return {"kind": kind, "bucket": bucket, "signal_date": signal_date}


def _object(body: Any, allowed: Iterable[str]) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise DeskInputError("invalid_body")
    if set(body) - set(allowed):
        raise DeskInputError("unknown_field")
    return body


def new_trade(user_id: str, body: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """A paper-trade document from a request body (long only); raises DeskInputError."""
    body = _object(body, _TRADE_FIELDS)
    symbol = clean_symbol(body.get("symbol"))
    quantity = clean_quantity(body.get("quantity"))
    entry = clean_price(body.get("entry_price"), "invalid_entry_price")
    stop = clean_price(body.get("stop_price"), "invalid_stop_price")
    if stop >= entry:
        raise DeskInputError("stop_not_below_entry")
    target = None
    if body.get("target_price") is not None:
        target = clean_price(body.get("target_price"), "invalid_target_price")
        if target <= entry:
            raise DeskInputError("target_not_above_entry")
    stamp = _iso(now or utcnow())
    return {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "note": clean_note(body.get("note")),
        "source": clean_source(body.get("source")),
        "opened_at": stamp,
        "status": "open",
        "closed_at": None,
        "exit_price": None,
        "exit_reason": None,
        "exit_session": None,
        "exit_note": None,
        "realized_pnl_rs": None,
        "created_at": stamp,
        "updated_at": stamp,
    }


def new_alert(user_id: str, body: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """A price-alert document from a request body; raises DeskInputError."""
    body = _object(body, _ALERT_FIELDS)
    symbol = clean_symbol(body.get("symbol"))
    condition = body.get("condition")
    if condition not in ("above", "below"):
        raise DeskInputError("invalid_condition")
    level = clean_price(body.get("level"), "invalid_level")
    stamp = _iso(now or utcnow())
    return {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "symbol": symbol,
        "condition": condition,
        "level": level,
        "note": clean_note(body.get("note")),
        "created_at": stamp,
        "status": "active",
        "fired_at": None,
        "fired_session": None,
        "fired_price": None,
        "updated_at": stamp,
    }


# ── prices ───────────────────────────────────────────────────────────────────
def ist_date(stamp: Any) -> date:
    """The IST calendar date of a stored ISO timestamp."""
    moment = datetime.fromisoformat(str(stamp))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST).date()


def _positive(value: Any) -> Optional[float]:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    number = _number(value)
    return number if number is not None and number > 0 else None


def _day(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def session_bars(rows: Iterable[Any]) -> List[Dict[str, Any]]:
    """One bar per session, oldest first, from raw /prices/eod rows: the most preferred normal-market series
    that day. Rows of other series (block-deal window, debt) and rows without a date are dropped."""
    best: Dict[date, Tuple[int, Dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rank = _SERIES_RANK.get(str(row.get("series") or "").strip().upper())
        day = _day(row.get("as_of_date"))
        if rank is None or day is None:
            continue
        if day not in best or rank < best[day][0]:
            best[day] = (rank, row)
    return [
        {
            "date": day,
            "high": _positive(row.get("high_price")),
            "low": _positive(row.get("low_price")),
            "close": _positive(row.get("close_price")),
            "series": SERIES_PREFERENCE[rank],
        }
        for day, (rank, row) in sorted(best.items())
    ]


async def fetch_bars(symbol: str, start: date) -> List[Dict[str, Any]]:
    """End-of-day bars for one symbol from `start` (inclusive) to the latest, oldest first.
    [] when the data platform has no rows; raises PricesUnavailable when it could not be read."""
    if not daas_client.is_configured():
        raise PricesUnavailable("the data platform is not configured")
    rows: List[Any] = []
    offset = 0
    for _ in range(MAX_PAGES):
        params = {"start": start.isoformat(), "limit": PAGE_LIMIT, "offset": offset}
        try:
            body = await daas_client._get(f"/prices/eod/{quote(symbol, safe='')}", params=params, timeout=FETCH_TIMEOUT_S)
        except daas_client.DaasError as exc:
            raise PricesUnavailable(str(exc)) from exc
        if body is None:            # 404: the platform knows no such symbol
            return []
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise PricesUnavailable(f"unexpected answer from /prices/eod/{symbol}")
        rows.extend(data)
        next_offset = (body.get("pagination") or {}).get("next_offset")
        if next_offset is None:
            return session_bars(rows)
        offset = int(next_offset)
    raise PricesUnavailable(f"more than {MAX_PAGES * PAGE_LIMIT} rows for {symbol} since {start}")


async def fetch_bars_many(starts: Dict[str, date]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str]]:
    """({symbol: bars}, {symbol: error code}) — one read per symbol, at most FETCH_CONCURRENCY at a time."""
    gate = asyncio.Semaphore(FETCH_CONCURRENCY)
    bars: Dict[str, List[Dict[str, Any]]] = {}
    errors: Dict[str, str] = {}

    async def one(symbol: str, start: date) -> None:
        try:
            async with gate:
                bars[symbol] = await fetch_bars(symbol, start)
        except PricesUnavailable as exc:
            logger.warning("desk_trading: no end-of-day bars for %s: %s", symbol, exc)
            errors[symbol] = PRICES_UNAVAILABLE
        except Exception as exc:  # noqa: BLE001 — one symbol's surprise must not lose every other symbol's marks
            logger.exception("desk_trading: reading bars for %s failed: %r", symbol, exc)
            errors[symbol] = PRICES_UNAVAILABLE

    await asyncio.gather(*(one(s, d) for s, d in starts.items()))
    return bars, errors


def fetch_starts(docs: Iterable[Dict[str, Any]], stamp_field: str) -> Dict[str, date]:
    """{symbol: first day to read} covering every document's first eligible session and a last close before it."""
    starts: Dict[str, date] = {}
    for doc in docs:
        start = ist_date(doc[stamp_field]) - timedelta(days=LOOKBACK_DAYS)
        symbol = doc["symbol"]
        if symbol not in starts or start < starts[symbol]:
            starts[symbol] = start
    return starts


def last_close(bars: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The newest bar that has a close, or None."""
    return next((b for b in reversed(bars) if b["close"] is not None), None)


# ── the rules ────────────────────────────────────────────────────────────────
def _eligible(bars: List[Dict[str, Any]], after: date):
    """Sessions strictly after `after`, oldest first, ending at the first one without a high or a low."""
    for bar in bars:
        if bar["date"] <= after:
            continue
        if bar["high"] is None or bar["low"] is None:
            logger.warning("desk_trading: the %s bar has no high/low; later sessions wait until it does", bar["date"])
            return
        yield bar


def find_trade_exit(trade: Dict[str, Any], bars: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[date]]:
    """(the exit the end-of-day bars show, or None; the last session checked, or None)."""
    stop = float(trade["stop_price"])
    target = trade.get("target_price")
    checked: Optional[date] = None
    for bar in _eligible(bars, ist_date(trade["opened_at"])):
        hit_stop = bar["low"] <= stop
        hit_target = target is not None and bar["high"] >= float(target)
        if hit_stop:
            return {"exit_reason": "stop", "exit_price": stop, "exit_session": bar["date"],
                    "exit_note": BOTH_IN_RANGE_NOTE if hit_target else None}, bar["date"]
        if hit_target:
            return {"exit_reason": "target", "exit_price": float(target), "exit_session": bar["date"], "exit_note": None}, bar["date"]
        checked = bar["date"]
    return None, checked


def find_alert_fire(alert: Dict[str, Any], bars: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[date]]:
    """(the session the alert fired on, or None; the last session checked, or None)."""
    level = float(alert["level"])
    above = alert["condition"] == "above"
    checked: Optional[date] = None
    for bar in _eligible(bars, ist_date(alert["created_at"])):
        if (bar["high"] >= level) if above else (bar["low"] <= level):
            return {"fired_session": bar["date"], "fired_price": level}, bar["date"]
        checked = bar["date"]
    return None, checked


def realized_pnl(trade: Dict[str, Any], exit_price: float) -> float:
    return round((exit_price - float(trade["entry_price"])) * int(trade["quantity"]), 2)


# ── writes (idempotent: the status is part of the filter) ────────────────────
async def close_trade(db, trade: Dict[str, Any], *, exit_reason: str, exit_price: float,
                      exit_session: Optional[date], exit_note: Optional[str] = None,
                      now: Optional[datetime] = None) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(the trade as stored afterwards, True when THIS call closed it). Never touches a trade that is not open."""
    stamp = _iso(now or utcnow())
    change = {
        "status": "closed",
        "closed_at": stamp,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "exit_session": exit_session.isoformat() if exit_session else None,
        "exit_note": exit_note,
        "realized_pnl_rs": realized_pnl(trade, exit_price),
        "updated_at": stamp,
    }
    owner = {"_id": trade["_id"], "user_id": trade["user_id"]}
    res = await db[TRADES].update_one({**owner, "status": "open"}, {"$set": change})
    if res.matched_count:
        return {**trade, **change}, True
    return await db[TRADES].find_one(owner), False


async def fire_alert(db, alert: Dict[str, Any], *, fired_session: date, fired_price: float,
                     now: Optional[datetime] = None) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(the alert as stored afterwards, True when THIS call fired it). Never touches an alert that is not active."""
    stamp = _iso(now or utcnow())
    change = {
        "status": "fired",
        "fired_at": stamp,
        "fired_session": fired_session.isoformat(),
        "fired_price": fired_price,
        "updated_at": stamp,
    }
    owner = {"_id": alert["_id"], "user_id": alert["user_id"]}
    res = await db[ALERTS].update_one({**owner, "status": "active"}, {"$set": change})
    if res.matched_count:
        return {**alert, **change}, True
    return await db[ALERTS].find_one(owner), False


async def apply_trade_exits(db, trades: List[Dict[str, Any]], bars: Dict[str, List[Dict[str, Any]]], *,
                            persist: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run the exit rule over open trades whose bars were read. (trades as they now stand, counts and the
    last session checked per trade id). With persist=False nothing is written (the script's dry run)."""
    out: List[Dict[str, Any]] = []
    counts: Dict[str, Any] = {"stop": 0, "target": 0, "already_closed": 0, "checked_through": {}}
    for trade in trades:
        if trade.get("status") != "open" or trade["symbol"] not in bars:
            out.append(trade)
            continue
        exit_, checked = find_trade_exit(trade, bars[trade["symbol"]])
        counts["checked_through"][trade["_id"]] = checked
        if exit_ is None:
            out.append(trade)
            continue
        if not persist:
            counts[exit_["exit_reason"]] += 1
            out.append(trade)
            continue
        stored, mine = await close_trade(db, trade, **exit_)
        if mine:
            counts[exit_["exit_reason"]] += 1
            logger.info("desk_trading: trade %s (%s) closed at the %s on %s", trade["_id"], trade["symbol"],
                        exit_["exit_reason"], exit_["exit_session"])
        else:
            counts["already_closed"] += 1
        if stored is not None:
            out.append(stored)
    return out, counts


async def apply_alert_fires(db, alerts: List[Dict[str, Any]], bars: Dict[str, List[Dict[str, Any]]], *,
                            persist: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run the firing rule over active alerts whose bars were read. (alerts as they now stand, counts)."""
    out: List[Dict[str, Any]] = []
    counts: Dict[str, Any] = {"fired": 0, "already_fired": 0, "checked_through": {}}
    for alert in alerts:
        if alert.get("status") != "active" or alert["symbol"] not in bars:
            out.append(alert)
            continue
        fire, checked = find_alert_fire(alert, bars[alert["symbol"]])
        counts["checked_through"][alert["_id"]] = checked
        if fire is None:
            out.append(alert)
            continue
        if not persist:
            counts["fired"] += 1
            out.append(alert)
            continue
        stored, mine = await fire_alert(db, alert, **fire)
        if mine:
            counts["fired"] += 1
            logger.info("desk_trading: alert %s (%s %s %s) fired on %s", alert["_id"], alert["symbol"],
                        alert["condition"], alert["level"], fire["fired_session"])
        else:
            counts["already_fired"] += 1
        if stored is not None:
            out.append(stored)
    return out, counts


# ── responses ────────────────────────────────────────────────────────────────
def _day_str(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def marks_error(errors: Dict[str, str], asked: int) -> Optional[str]:
    """The response-level price status: None, every read failed, or some failed."""
    if not errors:
        return None
    return PRICES_UNAVAILABLE if len(errors) >= asked else PRICES_PARTIAL


def mark_for(symbol: str, bars: Dict[str, List[Dict[str, Any]]], errors: Dict[str, str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if symbol in errors:
        return None, errors[symbol]
    bar = last_close(bars.get(symbol) or [])
    return bar, (None if bar else NO_PRICES)


def public_trade(doc: Dict[str, Any], mark: Optional[Dict[str, Any]] = None, mark_error: Optional[str] = None,
                 checked_through: Optional[date] = None) -> Dict[str, Any]:
    is_open = doc.get("status") == "open"
    close = mark["close"] if (is_open and mark) else None
    return {
        "id": doc["_id"],
        "symbol": doc["symbol"],
        "quantity": doc["quantity"],
        "entry_price": doc["entry_price"],
        "stop_price": doc["stop_price"],
        "target_price": doc.get("target_price"),
        "note": doc.get("note"),
        "source": doc.get("source"),
        "opened_at": doc["opened_at"],
        "status": doc["status"],
        "closed_at": doc.get("closed_at"),
        "exit_price": doc.get("exit_price"),
        "exit_reason": doc.get("exit_reason"),
        "exit_session": doc.get("exit_session"),
        "exit_note": doc.get("exit_note"),
        "last_close": close,
        "last_close_date": _day_str(mark["date"]) if (is_open and mark) else None,
        "unrealized_pnl_rs": round((close - float(doc["entry_price"])) * int(doc["quantity"]), 2) if close is not None else None,
        "realized_pnl_rs": None if is_open else doc.get("realized_pnl_rs"),
        "checked_through": _day_str(checked_through) if is_open else None,
        "mark_error": mark_error if is_open else None,
    }


def public_alert(doc: Dict[str, Any], mark: Optional[Dict[str, Any]] = None, mark_error: Optional[str] = None,
                 checked_through: Optional[date] = None) -> Dict[str, Any]:
    is_active = doc.get("status") == "active"
    return {
        "id": doc["_id"],
        "symbol": doc["symbol"],
        "condition": doc["condition"],
        "level": doc["level"],
        "note": doc.get("note"),
        "created_at": doc["created_at"],
        "status": doc["status"],
        "fired_at": doc.get("fired_at"),
        "fired_session": doc.get("fired_session"),
        "fired_price": doc.get("fired_price"),
        "last_close": mark["close"] if (is_active and mark) else None,
        "last_close_date": _day_str(mark["date"]) if (is_active and mark) else None,
        "checked_through": _day_str(checked_through) if is_active else None,
        "mark_error": mark_error if is_active else None,
    }


def summarize(trades: List[Dict[str, Any]], *, partial: bool) -> Dict[str, Any]:
    """Counts and P&L over public trades. realized is None with no closed trades; unrealized is None unless
    every open trade has a mark (a partial sum would read as the whole)."""
    open_ = [t for t in trades if t["status"] == "open"]
    closed = [t for t in trades if t["status"] == "closed"]
    realized = [t["realized_pnl_rs"] for t in closed if t["realized_pnl_rs"] is not None]
    unmarked = sum(1 for t in open_ if t["unrealized_pnl_rs"] is None)
    return {
        "open": len(open_),
        "closed": len(closed),
        "wins": sum(1 for r in realized if r > 0),
        "losses": sum(1 for r in realized if r < 0),
        "realized_pnl_rs": round(sum(realized), 2) if realized else None,
        "unrealized_pnl_rs": round(sum(t["unrealized_pnl_rs"] for t in open_), 2) if open_ and not unmarked else None,
        "unmarked_open": unmarked,
        "partial": partial,
    }


def latest_day(days: Iterable[Optional[date]]) -> Optional[date]:
    known = [d for d in days if d]
    return max(known) if known else None


def earliest_day(days: Iterable[Optional[date]]) -> Optional[date]:
    known = [d for d in days if d]
    return min(known) if known else None
