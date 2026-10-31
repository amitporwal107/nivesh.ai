"""Live premiums for a handful of named F&O contracts, read only.

WHY THIS EXISTS AND WHY IT IS NOT THE WEBSOCKET
The platform feed (`feed.py`) subscribes cash stocks, indices, the near-month FUT contract of every F&O
underlying, and a window of index options: for LIVE_OPTION_UNDERLYINGS (default NIFTY and BANKNIFTY) the
LIVE_OPTION_EXPIRIES nearest expiries (default 2), LIVE_OPTION_STRIKES_EACH_SIDE strikes either side of the
money (default 15), CE and PE, re-centred on every universe rebuild (served by GET /api/live/option-chain).
A contract outside that set (a stock option, a later expiry, a strike outside the window, a next-month
future) is not on the socket.

Subscribing every chain is not the fix: NIFTY and BANKNIFTY alone run to thousands of listed strikes
against Kite's ~3000-instrument websocket cap. A screen showing five ideas needs at most ~20 named
contracts, so this asks for exactly those over Kite's REST `quote()` instead. `ReadOnlyKite` exposes
no order, GTT, margin or session method, so nothing here can place anything.

Everything degrades rather than guesses: with no token, no feed or a failed call the caller is told
the live read is unavailable and why, and keeps the end-of-day prices it already had.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Leg kinds this can resolve, mapped to Kite's `instrument_type`.
_OPTION_TYPE = {"call": "CE", "put": "PE", "ce": "CE", "pe": "PE"}

MAX_LEGS = 40          # five ideas x four legs, with room to spare; keeps one REST call bounded.


def _day(v: Any) -> Optional[str]:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str) and len(v) >= 10:
        return v[:10]
    return None


def leg_key(underlying: Any, expiry: Any, strike: Any, kind: Any, option_type: Any) -> Optional[Tuple[str, str, Optional[float], str]]:
    """The identity of one contract: (underlying, expiry day, strike, instrument type).

    Returns None when the leg is not an exchange-traded F&O contract this can name — a cash leg, or
    an option with no strike. A None here becomes an `unresolved` entry, never a guess."""
    name = str(underlying or "").strip().upper()
    day = _day(expiry)
    if not name or not day:
        return None
    k = str(kind or "").strip().lower()
    if k in ("future", "futures", "fut"):
        return (name, day, None, "FUT")
    if k == "option":
        t = _OPTION_TYPE.get(str(option_type or "").strip().lower())
        if t is None or strike is None:
            return None
        try:
            return (name, day, float(strike), t)
        except (TypeError, ValueError):
            return None
    return None


def index_instruments(nfo_rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str, Optional[float], str], str]:
    """Kite's NFO instrument dump keyed by contract identity, value = its tradingsymbol.

    Built from the exchange's own rows rather than by assembling a symbol from parts: Kite's weekly
    and monthly option symbols follow different patterns, so a hand-built string is wrong for one of
    them, and an order-free read of a wrong symbol is still a wrong number on a screen."""
    out: Dict[Tuple[str, str, Optional[float], str], str] = {}
    for r in nfo_rows or []:
        if not isinstance(r, dict):
            continue
        itype = str(r.get("instrument_type") or "").upper()
        if itype not in ("CE", "PE", "FUT"):
            continue
        name, day, ts = str(r.get("name") or "").upper(), _day(r.get("expiry")), r.get("tradingsymbol")
        if not name or not day or not ts:
            continue
        if itype == "FUT":
            out[(name, day, None, "FUT")] = str(ts)
            continue
        try:
            out[(name, day, float(r.get("strike")), itype)] = str(ts)
        except (TypeError, ValueError):
            continue
    return out


def resolve(legs: List[Dict[str, Any]], instruments: Dict[Tuple[str, str, Optional[float], str], str]
            ) -> Tuple[Dict[int, str], List[Dict[str, Any]]]:
    """(index -> "NFO:TRADINGSYMBOL", unresolved[]) for the legs given.

    `unresolved` names the leg and why, so a screen can say which premium is still end of day instead
    of quietly showing a stale number as live."""
    keys: Dict[int, str] = {}
    unresolved: List[Dict[str, Any]] = []
    for i, leg in enumerate(legs or []):
        if not isinstance(leg, dict):
            unresolved.append({"index": i, "reason": "the leg is not an object"})
            continue
        ident = leg_key(leg.get("underlying"), leg.get("expiry"), leg.get("strike"),
                        leg.get("kind"), leg.get("option_type"))
        if ident is None:
            unresolved.append({"index": i, "reason": "not an exchange-traded F&O contract, or a field is missing"})
            continue
        ts = instruments.get(ident)
        if not ts:
            unresolved.append({"index": i, "reason": f"no listed contract for {ident[0]} {ident[1]} "
                                                     f"{'' if ident[2] is None else ident[2]} {ident[3]}".replace("  ", " ")})
            continue
        keys[i] = f"NFO:{ts}"
    return keys, unresolved


def traded_since(row: Dict[str, Any], floor: date) -> bool:
    """True when the contract last traded on or after `floor` (the previous session). Kite answers `last_price` for a
    contract that has not traded for days, and 1970-01-01 for one that never traded: that price is not today's."""
    return (_day(row.get("last_trade_time")) or "")[:10] >= floor.isoformat()


def prices_from(quote: Dict[str, Any], keys: Dict[int, str], floor: Optional[date] = None) -> Dict[int, Dict[str, Any]]:
    """Kite's quote() answer reduced to what a screen needs, per leg index. A key the answer does not
    carry is simply absent — it is never defaulted to the last known or to zero. With `floor`, a contract that has
    not traded since before it is absent too (traded_since)."""
    out: Dict[int, Dict[str, Any]] = {}
    for i, key in keys.items():
        row = (quote or {}).get(key)
        if not isinstance(row, dict):
            continue
        last = row.get("last_price")
        if last is None:
            continue
        if floor is not None and not traded_since(row, floor):
            continue
        entry: Dict[str, Any] = {"key": key, "last_price": float(last)}
        ohlc = row.get("ohlc") if isinstance(row.get("ohlc"), dict) else None
        if ohlc and ohlc.get("close") is not None:
            try:
                entry["previous_close"] = float(ohlc["close"])
            except (TypeError, ValueError):
                pass
        for f, cast in (("oi", float), ("volume", float), ("last_trade_time", str), ("exchange_timestamp", str)):
            if row.get(f) is not None:
                try:
                    entry[f] = cast(row[f])
                except (TypeError, ValueError):
                    pass
        out[i] = entry
    return out
