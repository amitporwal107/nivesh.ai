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

A document without `kind` is a cash share trade (everything below). `kind: "strategy"` documents (futures and option
structures, rules version desk-paper-v3) live in services/desk_strategy_trades.py and are skipped by the share rules.

Paper trades carry the DaaS paper_trades field set (PRD §13.4; rules version `RULES_VERSION`):
    entry rule    at_once (filled at the reference entry when recorded, the first version's behaviour),
                  break_above (filled when a later session's high reaches the entry) or pullback_to (when its
                  low does). A conditional entry waits `entry_window_sessions` sessions, then closes as
                  "entry_not_reached" with no P&L. The fill is the reference entry; a session that opened
                  beyond it is flagged (a real order would have filled near the open).
    entry session conditional entries are checked for exits on their own session too, conservatively:
                  break_above counts a stop on that session (the low may have come first, flagged);
                  pullback_to does not count a target on that session (the high may have come first, flagged).
    exit rule     stop / target as above; with `max_hold_sessions`, the close of the last session held
                  ("time"). A gap through the stop is flagged; the paper fill stays the stop.
    costs         strategy_engine's cost model (services/strategy_engine/backtest.py): DEFAULT_SLIPPAGE_PCT of
                  the traded value plus DEFAULT_BROKERAGE_INR, per side. Snapshotted on each trade.
    path          observations = eligible sessions read since the trade was recorded; MFE / MAE = the highest
                  high / lowest low from the first session held through the exit session, against the fill.
Nothing here can create a broker order: there is no broker import and no order call.
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
from services.strategy_engine.backtest import DEFAULT_BROKERAGE_INR, DEFAULT_SLIPPAGE_PCT

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

# ── paper trades: the DaaS paper_trades field set (PRD §13.4) ────────────────
RULES_VERSION = "desk-paper-v2"
ENTRY_RULES = ("at_once", "break_above", "pullback_to")
ENTRY_RULE_TEXT = {
    "at_once": "Filled at the reference entry price when the trade was recorded (assumed, not checked against a bar).",
    "break_above": ("Filled at the reference entry on the first session after it was recorded whose high reaches it; "
                    "a session that opened above it is flagged."),
    "pullback_to": ("Filled at the reference entry on the first session after it was recorded whose low reaches it; "
                    "a session that opened below it is flagged."),
}
DEFAULT_ENTRY_WINDOW = 5          # sessions a conditional entry waits before it closes as "entry_not_reached"
MAX_ENTRY_WINDOW = 20
MAX_HOLD_SESSIONS = 250
SIGNAL_SKEW = timedelta(minutes=5)  # a signal time this far ahead of the server clock is still accepted
STRATEGY_VERSION_MAX = 60
COST_MODEL = {
    "name": "strategy_engine default",
    "slippage_pct_per_side": round(DEFAULT_SLIPPAGE_PCT * 100, 4),
    "brokerage_rs_per_side": float(DEFAULT_BROKERAGE_INR),
    "source": "services/strategy_engine/backtest.py",
}
ORDERS_NOTE = "Paper trades are simulated and never create a broker order."
TIME_EXIT_NOTE = "Held for the most sessions the exit rule allows; closed at that session's close."
NOT_REACHED_NOTE = "The entry level was not reached within the entry window; no position was taken."
CANCELLED_NOTE = "Closed by you before the entry level was reached; no position was taken."
# Exit reasons a stored trade can carry.
EXIT_REASONS = ("stop", "target", "time", "manual", "entry_not_reached", "cancelled")
_STRATEGY_VERSION_RE = re.compile(r"^[A-Za-z0-9 ._:+/#()-]{1,60}$")

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

_TRADE_FIELDS = {"symbol", "quantity", "entry_price", "stop_price", "target_price", "note", "source",
                 "entry_rule", "entry_window_sessions", "max_hold_sessions", "signal_at", "strategy_version", "rationale"}
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


def _whole(value: Any, low: int, high: int, code: str) -> int:
    number = _number(value)
    if number is None or not number.is_integer() or not low <= number <= high:
        raise DeskInputError(code)
    return int(number)


def clean_entry_rule(raw: Any) -> str:
    if raw is None:
        return "at_once"
    if not isinstance(raw, str) or raw not in ENTRY_RULES:
        raise DeskInputError("invalid_entry_rule")
    return raw


def clean_signal_at(raw: Any, now: datetime) -> Optional[str]:
    """When the signal was generated: an ISO date ("2026-10-09") or date-time; never after now."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not 10 <= len(raw.strip()) <= 40:
        raise DeskInputError("invalid_signal_at")
    text = raw.strip()
    try:
        if len(text) == 10:
            day = date.fromisoformat(text)
            if day > now.astimezone(IST).date():
                raise DeskInputError("invalid_signal_at")
            return day.isoformat()
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise DeskInputError("invalid_signal_at") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if moment > now + SIGNAL_SKEW:
        raise DeskInputError("invalid_signal_at")
    return _iso(moment)


def clean_strategy_version(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str) or not _STRATEGY_VERSION_RE.match(raw.strip() or "\n"):
        raise DeskInputError("invalid_strategy_version")
    return raw.strip()


def clean_rationale(raw: Any) -> Optional[str]:
    try:
        return clean_note(raw)
    except DeskInputError:
        raise DeskInputError("invalid_rationale") from None


def new_trade(user_id: str, body: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """A paper-trade document from a request body (long only); raises DeskInputError."""
    body = _object(body, _TRADE_FIELDS)
    moment = now or utcnow()
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
    entry_rule = clean_entry_rule(body.get("entry_rule"))
    window = None
    if body.get("entry_window_sessions") is not None:
        if entry_rule == "at_once":
            raise DeskInputError("invalid_entry_window")          # only a conditional entry waits
        window = _whole(body.get("entry_window_sessions"), 1, MAX_ENTRY_WINDOW, "invalid_entry_window")
    elif entry_rule != "at_once":
        window = DEFAULT_ENTRY_WINDOW
    max_hold = None
    if body.get("max_hold_sessions") is not None:
        max_hold = _whole(body.get("max_hold_sessions"), 1, MAX_HOLD_SESSIONS, "invalid_max_hold")
    signal_at = clean_signal_at(body.get("signal_at"), moment)
    strategy_version = clean_strategy_version(body.get("strategy_version"))
    rationale = clean_rationale(body.get("rationale"))
    stamp = _iso(moment)
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
        "entry_rule": entry_rule,
        "entry_window_sessions": window,
        "max_hold_sessions": max_hold,
        "signal_at": signal_at,
        "strategy_version": strategy_version,
        "rationale": rationale,
        "rules_version": RULES_VERSION,
        "cost_model": dict(COST_MODEL),
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
            "open": _positive(row.get("open_price")),
            "high": _positive(row.get("high_price")),
            "low": _positive(row.get("low_price")),
            "close": _positive(row.get("close_price")),
            # Shares traded that session (the volume alert, services/desk_alerts.py); None when not sent.
            "volume": _positive(row.get("volume")),
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


def _flag(code: str, text: str, session: Optional[date] = None, price: Optional[float] = None) -> Dict[str, Any]:
    return {"code": code, "text": text, "session": session.isoformat() if session else None, "price": price}


def _rupees(value: float) -> str:
    return f"₹{value:,.2f}"


def simulate(trade: Dict[str, Any], bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run the trade's entry and exit rules over end-of-day bars (oldest first).

    Returns {entry_status: assumed | reached | waiting | not_reached, entry_session, sim_entry_price,
    observations, held_sessions, checked_through, max_high, min_low, flags, exit (or None)}; `exit` is
    {exit_reason, exit_price, exit_session, exit_note} as close_trade takes it. Never writes."""
    rule = trade.get("entry_rule") or "at_once"
    entry = float(trade["entry_price"])
    stop = float(trade["stop_price"])
    target = float(trade["target_price"]) if trade.get("target_price") is not None else None
    window = int(trade.get("entry_window_sessions") or DEFAULT_ENTRY_WINDOW)
    max_hold = trade.get("max_hold_sessions")
    opened = ist_date(trade["opened_at"])
    flags: List[Dict[str, Any]] = []
    out: Dict[str, Any] = {"entry_status": "waiting", "entry_session": None, "sim_entry_price": None,
                           "observations": 0, "held_sessions": 0, "checked_through": None,
                           "max_high": None, "min_low": None, "flags": flags, "exit": None}
    entered = rule == "at_once"
    if entered:
        out.update(entry_status="assumed", sim_entry_price=entry)
        day = next((b for b in bars if b["date"] == opened), None)
        if day and day["high"] is not None and day["low"] is not None and not day["low"] <= entry <= day["high"]:
            flags.append(_flag("entry_outside_day_range",
                               f"The entry {_rupees(entry)} is outside the {opened.isoformat()} range "
                               f"({_rupees(day['low'])}–{_rupees(day['high'])}): that fill could not have happened that day.",
                               opened))
    waited = 0
    for bar in bars:
        if bar["date"] <= opened:
            continue
        if bar["high"] is None or bar["low"] is None:
            logger.warning("desk_trading: the %s bar has no high/low; later sessions wait until it does", bar["date"])
            flags.append(_flag("bar_missing_high_low",
                               "This session has no high or low on record; later sessions are not checked until it does.",
                               bar["date"]))
            break
        out["observations"] += 1
        out["checked_through"] = bar["date"]
        entry_session = False
        if not entered:
            waited += 1
            reached = bar["high"] >= entry if rule == "break_above" else bar["low"] <= entry
            if not reached:
                if waited >= window:
                    out["entry_status"] = "not_reached"
                    out["exit"] = {"exit_reason": "entry_not_reached", "exit_price": None, "exit_session": bar["date"],
                                   "exit_note": NOT_REACHED_NOTE}
                    return out
                continue
            entered, entry_session = True, True
            # A session that OPENS beyond the trigger never traded at the trigger, so the fill is the open —
            # worse than the entry, in the same way a gapped stop fills worse than the stop. This used to
            # record the trigger price and only flag the gap, which made every gapped entry better than it
            # could have been.
            opened_beyond = bar["open"] is not None and (bar["open"] > entry if rule == "break_above" else bar["open"] < entry)
            fill = bar["open"] if opened_beyond else entry
            out.update(entry_status="reached", entry_session=bar["date"], sim_entry_price=fill)
            if opened_beyond:
                flags.append(_flag("entry_gap",
                                   f"The session opened at {_rupees(bar['open'])}, beyond the entry {_rupees(entry)}: the "
                                   "price never traded at the entry, so the fill is the open.",
                                   bar["date"], bar["open"]))
        out["held_sessions"] += 1
        out["max_high"] = bar["high"] if out["max_high"] is None else max(out["max_high"], bar["high"])
        out["min_low"] = bar["low"] if out["min_low"] is None else min(out["min_low"], bar["low"])
        hit_stop = bar["low"] <= stop
        hit_target = target is not None and bar["high"] >= target
        if entry_session and rule == "pullback_to" and hit_target:
            hit_target = False
            flags.append(_flag("entry_session_ambiguous",
                               "The target was inside the entry session's range, but its high may have come before the "
                               "fill; the target is counted from the next session.", bar["date"]))
        if entry_session and rule == "break_above" and hit_stop:
            flags.append(_flag("entry_session_ambiguous",
                               "The stop was inside the entry session's range and its low may have come before the fill; "
                               "counted as the stop (conservative).", bar["date"]))
        exit_: Optional[Dict[str, Any]] = None
        if hit_stop:
            # A session that OPENS below the stop never traded at the stop: a real stop order becomes a
            # market order and fills at the open, worse than the stop. This used to book the fill at the
            # stop anyway and merely flag it, which made a paper stop-loss incapable of losing to a gap —
            # and the promotion gates in ai_trader/strategy.py read these numbers. The flag text said the
            # right thing while the arithmetic did the opposite.
            gapped = bar["open"] is not None and bar["open"] < stop
            fill = bar["open"] if gapped else stop
            exit_ = {"exit_reason": "stop", "exit_price": fill, "exit_session": bar["date"],
                     "exit_note": BOTH_IN_RANGE_NOTE if hit_target else None}
            if hit_target:
                flags.append(_flag("both_in_range", BOTH_IN_RANGE_NOTE, bar["date"]))
            if gapped:
                flags.append(_flag("gap_through_stop",
                                   f"The session opened at {_rupees(bar['open'])}, below the stop {_rupees(stop)}: the "
                                   "price never traded at the stop, so the fill is the open and the loss is larger than "
                                   "the stop distance.", bar["date"], bar["open"]))
        elif hit_target:
            exit_ = {"exit_reason": "target", "exit_price": target, "exit_session": bar["date"], "exit_note": None}
        elif max_hold and out["held_sessions"] >= int(max_hold) and bar["close"] is not None:
            exit_ = {"exit_reason": "time", "exit_price": bar["close"], "exit_session": bar["date"], "exit_note": TIME_EXIT_NOTE}
        if exit_ is not None:
            out["exit"] = exit_
            return out
    return out


def find_trade_exit(trade: Dict[str, Any], bars: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[date]]:
    """(the exit the end-of-day bars show, or None; the last session checked, or None)."""
    sim = simulate(trade, bars)
    return sim["exit"], sim["checked_through"]


def trade_costs(trade: Dict[str, Any], entry_price: float, exit_price: float) -> float:
    """Round-trip estimated cost in rupees under the trade's cost model (the current one for older trades)."""
    model = trade.get("cost_model") or COST_MODEL
    slip = float(model.get("slippage_pct_per_side", COST_MODEL["slippage_pct_per_side"])) / 100.0
    brokerage = float(model.get("brokerage_rs_per_side", COST_MODEL["brokerage_rs_per_side"]))
    qty = int(trade["quantity"])
    entry_side = entry_price * qty * slip + brokerage
    exit_side = exit_price * qty * slip + brokerage
    return round(entry_side + exit_side, 2)


def estimated_costs(trade: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """What a round trip would cost at the stop and at the target, from the reference entry."""
    entry = float(trade["entry_price"])
    target = trade.get("target_price")
    return {"at_target": trade_costs(trade, entry, float(target)) if target is not None else None,
            "at_stop": trade_costs(trade, entry, float(trade["stop_price"]))}


def path_figures(trade: Dict[str, Any], sim: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """MFE / MAE against the fill (percent and rupees) and the counts, from a simulate() result; all None
    when the trade was never entered or nothing was read."""
    none = {"mfe_pct": None, "mae_pct": None, "mfe_rs": None, "mae_rs": None}
    if not sim:
        return {**none, "observations": None, "held_sessions": None, "entry_status": None, "entry_session": None,
                "sim_entry_price": None, "flags": []}
    fill = sim["sim_entry_price"]
    qty = int(trade["quantity"])
    out = {"observations": sim["observations"], "held_sessions": sim["held_sessions"],
           "entry_status": sim["entry_status"],
           "entry_session": sim["entry_session"].isoformat() if sim["entry_session"] else None,
           "sim_entry_price": fill, "flags": list(sim["flags"]), **none}
    if fill and sim["max_high"] is not None and sim["min_low"] is not None:
        out.update(mfe_pct=round((sim["max_high"] / fill - 1) * 100, 2), mae_pct=round((sim["min_low"] / fill - 1) * 100, 2),
                   mfe_rs=round((sim["max_high"] - fill) * qty, 2), mae_rs=round((sim["min_low"] - fill) * qty, 2))
    return out


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
async def close_trade(db, trade: Dict[str, Any], *, exit_reason: str, exit_price: Optional[float],
                      exit_session: Optional[date], exit_note: Optional[str] = None,
                      now: Optional[datetime] = None,
                      sim: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(the trade as stored afterwards, True when THIS call closed it). Never touches a trade that is not open.
    `sim` (a simulate() result) records the entry, the path (MFE / MAE, observations) and the flags with the exit;
    gross P&L, estimated costs and net P&L are worked out from the fill and the exit price. A trade closed without
    an exit price (entry never reached, or cancelled) has no P&L and no costs."""
    stamp = _iso(now or utcnow())
    path = path_figures(trade, sim)
    if sim is None and (trade.get("entry_rule") or "at_once") == "at_once":
        path.update(entry_status="assumed", sim_entry_price=float(trade["entry_price"]))
    gross = realized_pnl(trade, exit_price) if exit_price is not None else None
    costs = trade_costs(trade, float(trade["entry_price"]), exit_price) if exit_price is not None else None
    change = {
        "status": "closed",
        "closed_at": stamp,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "exit_session": exit_session.isoformat() if exit_session else None,
        "exit_note": exit_note,
        "realized_pnl_rs": gross,
        "costs_rs": costs,
        "net_pnl_rs": round(gross - costs, 2) if gross is not None and costs is not None else None,
        **path,
        "checked_through": sim["checked_through"].isoformat() if sim and sim["checked_through"] else None,
        "updated_at": stamp,
    }
    owner = {"_id": trade["_id"], "user_id": trade["user_id"]}
    res = await db[TRADES].update_one({**owner, "status": "open"}, {"$set": change})
    if res.matched_count:
        # The account gets back exactly what this trade reserved, plus or minus its net P&L. The
        # figure comes from the trade, not from a fresh calculation: recomputing it at today's prices
        # is how a paper account silently drifts away from the positions that made it. Released here
        # rather than in the route so an AUTOMATIC exit (apply_trade_exits) frees the capital too.
        from services import paper_account as _acct
        await _acct.release(db, trade["user_id"], trade.get("paper_reserved_rs"),
                            net_pnl=change.get("net_pnl_rs"), trade_id=trade["_id"],
                            symbol=trade.get("symbol"))
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
    counts: Dict[str, Any] = {"stop": 0, "target": 0, "time": 0, "entry_not_reached": 0, "already_closed": 0,
                              "checked_through": {}, "paths": {}}
    for trade in trades:
        if trade.get("kind") == "strategy" or trade.get("status") != "open" or trade["symbol"] not in bars:
            out.append(trade)          # strategy trades are evaluated by services/desk_strategy_trades.py
            continue
        sim = simulate(trade, bars[trade["symbol"]])
        exit_ = sim["exit"]
        counts["checked_through"][trade["_id"]] = sim["checked_through"]
        counts["paths"][trade["_id"]] = sim
        if exit_ is None:
            out.append(trade)
            continue
        if not persist:
            counts[exit_["exit_reason"]] += 1
            out.append(trade)
            continue
        stored, mine = await close_trade(db, trade, **exit_, sim=sim)
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


ENTERED = ("assumed", "reached")


def _paper_fields(doc: Dict[str, Any], close: Optional[float], sim: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The §13.4 fields of one trade. An open trade's path comes from this read's simulate(); a closed trade's
    from what was stored when it closed (null when it closed before these fields existed, never 0)."""
    rule = doc.get("entry_rule") or "at_once"
    is_open = doc.get("status") == "open"
    if is_open:
        path = path_figures(doc, sim)
        if sim is None:
            path.update(entry_status="assumed" if rule == "at_once" else "waiting",
                        sim_entry_price=float(doc["entry_price"]) if rule == "at_once" else None)
        entered = path["entry_status"] in ENTERED
        fill = path["sim_entry_price"]
        gross = round((close - fill) * int(doc["quantity"]), 2) if entered and close is not None and fill else None
        costs = trade_costs(doc, fill, close) if gross is not None else None
        basis = "exit side estimated at the last close" if costs is not None else None
    else:
        keys = ("observations", "held_sessions", "entry_session", "mfe_pct", "mae_pct", "mfe_rs", "mae_rs")
        path = {k: doc.get(k) for k in keys}
        exit_price = doc.get("exit_price")
        status = doc.get("entry_status") or ("assumed" if rule == "at_once" and exit_price is not None else None)
        path.update(entry_status=status, flags=list(doc.get("flags") or []),
                    sim_entry_price=doc.get("sim_entry_price") if "sim_entry_price" in doc
                    else (float(doc["entry_price"]) if status in ENTERED else None))
        gross = doc.get("realized_pnl_rs")
        costs = doc.get("costs_rs")
        if costs is None and exit_price is not None and gross is not None:
            costs = trade_costs(doc, float(doc["entry_price"]), float(exit_price))
        basis = "entry and exit at the fill prices" if costs is not None else None
    net = round(gross - costs, 2) if gross is not None and costs is not None else None
    return {
        "entry_rule": rule,
        "entry_window_sessions": doc.get("entry_window_sessions"),
        "max_hold_sessions": doc.get("max_hold_sessions"),
        "signal_at": doc.get("signal_at"),
        "strategy_version": doc.get("strategy_version"),
        "rationale": doc.get("rationale"),
        "rules_version": doc.get("rules_version"),
        "cost_model": doc.get("cost_model") or dict(COST_MODEL),
        "est_costs_rs": estimated_costs(doc),
        **path,
        "gross_pnl_rs": gross,
        "costs_rs": costs,
        "costs_basis": basis,
        "net_pnl_rs": net,
    }


def public_trade(doc: Dict[str, Any], mark: Optional[Dict[str, Any]] = None, mark_error: Optional[str] = None,
                 checked_through: Optional[date] = None, sim: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    is_open = doc.get("status") == "open"
    close = mark["close"] if (is_open and mark) else None
    paper = _paper_fields(doc, close, sim)
    return {
        "id": doc["_id"],
        "kind": "cash",
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
        "unrealized_pnl_rs": paper["gross_pnl_rs"] if is_open else None,
        "realized_pnl_rs": None if is_open else doc.get("realized_pnl_rs"),
        "checked_through": _day_str(checked_through) if is_open else doc.get("checked_through"),
        "mark_error": mark_error if is_open else None,
        **paper,
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
    # A paper position exists only once its entry is assumed or reached; a waiting entry holds nothing.
    held = [t for t in open_ if t.get("entry_status", "assumed") in ENTERED]
    realized = [t["realized_pnl_rs"] for t in closed if t["realized_pnl_rs"] is not None]
    net_realized = [t["net_pnl_rs"] for t in closed if t.get("net_pnl_rs") is not None]
    costs_realized = [t["costs_rs"] for t in closed if t.get("costs_rs") is not None]
    unmarked = sum(1 for t in held if t["unrealized_pnl_rs"] is None)
    whole = bool(held) and not unmarked
    return {
        "open": len(open_),
        "closed": len(closed),
        "wins": sum(1 for r in realized if r > 0),
        "losses": sum(1 for r in realized if r < 0),
        "realized_pnl_rs": round(sum(realized), 2) if realized else None,
        "unrealized_pnl_rs": round(sum(t["unrealized_pnl_rs"] for t in held), 2) if whole else None,
        "unmarked_open": unmarked,
        "partial": partial,
        "net_realized_pnl_rs": round(sum(net_realized), 2) if net_realized else None,
        "costs_realized_rs": round(sum(costs_realized), 2) if costs_realized else None,
        "net_unrealized_pnl_rs": round(sum(t["net_pnl_rs"] for t in held), 2) if whole else None,
        "entry_pending": sum(1 for t in open_ if t.get("entry_status") == "waiting"),
        "not_entered": sum(1 for t in closed if t.get("exit_reason") in ("entry_not_reached", "cancelled")),
    }


def latest_day(days: Iterable[Optional[date]]) -> Optional[date]:
    known = [d for d in days if d]
    return max(known) if known else None


def earliest_day(days: Iterable[Optional[date]]) -> Optional[date]:
    known = [d for d in days if d]
    return min(known) if known else None
