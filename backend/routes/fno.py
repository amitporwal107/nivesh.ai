"""F&O end-of-day data — app-side, read-only proxy over the data platform's NSE F&O bhavcopy.

    GET /api/fno/{symbol}/expiries               option expiries still listed on the latest day, nearest first
    GET /api/fno/{symbol}/chain?expiry=&around=  one expiry's chain by strike, plus a summary of the whole chain
    GET /api/fno/{symbol}/futures                the latest day's futures contracts, each with its basis

The rows live in nidp.fno_bhavcopy, which only the data platform can read (DaaS /v1/fno/*,
nidp/services/daas_api/routers/fno.py), so each route forwards to it and shapes the answer. The data is end of
day: one row per contract per trading day, with prices, open interest, volume and the contract's lot size. It
has no implied volatility, so none is returned and none is estimated. `lot_size` is null until the data
platform's F&O routes send the bhavcopy's lot column (new_board_lot_qty).

Definitions (the pure functions below; tests/test_fno_routes.py works one example by hand):
    spot        the bhavcopy's underlying_price for the day (the first positive value among the rows)
    ATM strike  the strike nearest the spot; an exact tie goes to the lower strike
    PCR         total put open interest ÷ total call open interest, over every strike of the expiry
    max pain    the strike K where  Σ call OI(k) × max(K − k, 0)  +  Σ put OI(k) × max(k − K, 0)  is smallest:
                the total intrinsic value of every open call and put if the underlying settled at K
    basis       futures settle price − spot (positive = the future is at a premium to the spot)

Errors: an underlying with no F&O rows is 404 with a plain sentence. An unreachable or failing data platform is
502 upstream_unavailable, as on /api/movers and /api/move-odds, never an empty or an older answer.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from fastapi import APIRouter, HTTPException, Path, Query, Request

from deps import get_current_user
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fno", tags=["fno"])

SYMBOL_PATTERN = r"^[A-Za-z0-9&\-]+$"
SYMBOL_MAX = 20
DEFAULT_AROUND = 40
MAX_AROUND = 500
# The exchange's current bhavcopy names index and stock futures IDF and STF (their options are IDO and STO);
# its older format called them FUTIDX and FUTSTK. Both are asked for, so either vintage of rows is found.
_FUTURES_TYPES = ("IDF", "STF", "FUTIDX", "FUTSTK")
_OPTION_SIDES = ("CE", "PE")
# An underlying lists three monthly futures (a few more for long-dated index contracts).
_FUTURES_LIMIT = 50
_UNAVAILABLE = "upstream_unavailable"

Number = Union[int, float]


# ── reading the data platform's values ───────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    """A finite number, or None. NUMERIC arrives as a float and BIGINT as an int; anything else is absent."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _qty(v: Any) -> Optional[int]:
    """Open interest, change in OI, volume: whole numbers."""
    f = _num(v)
    return None if f is None else int(f)


def _tidy(f: Optional[float]) -> Optional[Number]:
    """25100.0 → 25100, 712.5 → 712.5: a strike reads as it is quoted."""
    if f is None:
        return None
    return int(f) if f.is_integer() else f


def _iso_day(v: Any) -> Optional[str]:
    """A calendar day exactly as "YYYY-MM-DD", or None. A timestamp is not a trading day."""
    if not isinstance(v, str) or len(v) != 10:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        return None


# ── pure calculations ────────────────────────────────────────────────────────

def find_spot(rows: Iterable[Any]) -> Optional[float]:
    """The day's underlying price: the first positive underlying_price among the bhavcopy rows."""
    for r in rows:
        if isinstance(r, dict):
            p = _num(r.get("underlying_price"))
            if p is not None and p > 0:
                return p
    return None


def find_lot_size(rows: Iterable[Any]) -> Optional[int]:
    """The contract's lot size: the first positive new_board_lot_qty among the bhavcopy rows. None when the
    data platform does not send the column."""
    for r in rows:
        if isinstance(r, dict):
            lot = _qty(r.get("new_board_lot_qty"))
            if lot is not None and lot > 0:
                return lot
    return None


def atm_strike(strikes: Sequence[float], spot: Optional[float]) -> Optional[float]:
    """The strike nearest the spot. An exact tie goes to the lower strike."""
    if spot is None or not strikes:
        return None
    return min(strikes, key=lambda k: (abs(k - spot), k))


def put_call_ratio(total_call_oi: float, total_put_oi: float) -> Optional[float]:
    """Put open interest ÷ call open interest. None when there is no call open interest to divide by."""
    if total_call_oi <= 0:
        return None
    return round(total_put_oi / total_call_oi, 4)


def expiry_payout(points: Sequence[Tuple[float, float, float]], settle_at: float) -> float:
    """Total intrinsic value of all open calls and puts if the underlying settled at `settle_at`.
    `points` are (strike, call OI, put OI)."""
    return sum(c * max(settle_at - k, 0.0) + p * max(k - settle_at, 0.0) for k, c, p in points)


def max_pain(points: Sequence[Tuple[float, float, float]], spot: Optional[float] = None) -> Optional[float]:
    """The strike at which `expiry_payout` is smallest. A tie goes to the strike nearer the spot, then the
    lower one. None when the expiry has no open interest at all."""
    if not any(c > 0 or p > 0 for _, c, p in points):
        return None
    return min(
        (k for k, _, _ in points),
        key=lambda k: (expiry_payout(points, k), abs(k - spot) if spot is not None else 0.0, k),
    )


def top_oi_strike(points: Sequence[Tuple[float, float]], spot: Optional[float] = None) -> Optional[Dict[str, Number]]:
    """The strike holding the most open interest among (strike, OI) pairs. A tie goes to the strike nearer
    the spot, then the lower one. None when no strike has any."""
    live = [(k, oi) for k, oi in points if oi > 0]
    if not live:
        return None
    k, oi = min(live, key=lambda t: (-t[1], abs(t[0] - spot) if spot is not None else 0.0, t[0]))
    return {"strike": _tidy(k), "oi": int(oi)}


def futures_basis(settle: Optional[float], spot: Optional[float]) -> Optional[float]:
    """Futures settle price − spot. None when either price is missing."""
    if settle is None or spot is None or settle <= 0 or spot <= 0:
        return None
    return round(settle - spot, 2)


# ── shaping ──────────────────────────────────────────────────────────────────

def shape_side(row: Any) -> Optional[Dict[str, Any]]:
    """One call or put contract as the app sends it. None when the strike has no contract on that side."""
    if not isinstance(row, dict):
        return None
    return {
        "close": _num(row.get("close_price")),
        "settle": _num(row.get("settle_price")),
        "oi": _qty(row.get("open_interest")),
        "change_in_oi": _qty(row.get("change_in_oi")),
        "volume": _qty(row.get("traded_volume")),
    }


def shape_strikes(raw: Any) -> List[Dict[str, Any]]:
    """The data platform's `strikes` list as strike-ascending rows of {strike, call, put}."""
    out: List[Dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        strike = _num(item.get("strike"))
        call, put = shape_side(item.get("CE")), shape_side(item.get("PE"))
        if strike is None or strike <= 0 or (call is None and put is None):
            continue
        out.append({"strike": _tidy(strike), "call": call, "put": put})
    out.sort(key=lambda r: r["strike"])
    return out


def _side_total(strikes: Sequence[Dict[str, Any]], side: str, field: str) -> int:
    return sum(int((r[side] or {}).get(field) or 0) for r in strikes)


def summarise_chain(strikes: Sequence[Dict[str, Any]], spot: Optional[float], as_of: str, expiry: str) -> Dict[str, Any]:
    """Totals, PCR, max pain, ATM and the heaviest strikes, over every strike passed in."""
    oi = [(float(r["strike"]), float((r["call"] or {}).get("oi") or 0), float((r["put"] or {}).get("oi") or 0)) for r in strikes]
    total_call, total_put = _side_total(strikes, "call", "oi"), _side_total(strikes, "put", "oi")
    return {
        "as_of": as_of,
        "expiry": expiry,
        "spot": spot,
        "atm_strike": _tidy(atm_strike([k for k, _, _ in oi], spot)),
        "total_call_oi": total_call,
        "total_put_oi": total_put,
        "total_call_oi_change": _side_total(strikes, "call", "change_in_oi"),
        "total_put_oi_change": _side_total(strikes, "put", "change_in_oi"),
        "pcr": put_call_ratio(total_call, total_put),
        "max_pain": _tidy(max_pain(oi, spot)),
        "max_call_oi": top_oi_strike([(k, c) for k, c, _ in oi], spot),
        "max_put_oi": top_oi_strike([(k, p) for k, _, p in oi], spot),
    }


def window_around(strikes: Sequence[Dict[str, Any]], centre_strike: Optional[Number], around: int) -> List[Dict[str, Any]]:
    """Up to `around` strikes each side of `centre_strike`, plus that strike. Without one (no spot), the
    window sits on the middle of the chain."""
    if not strikes:
        return []
    centre = next((i for i, r in enumerate(strikes) if r["strike"] == centre_strike), len(strikes) // 2)
    return list(strikes[max(0, centre - around): centre + around + 1])


def live_option_expiries(rows: Any) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """(latest trading day, the option expiries still listed on it, nearest first).

    The data platform lists every expiry it has ever seen for the underlying, with the last day each one
    appeared. An expiry is live when it appeared on the latest day, carries option contracts and does not
    fall before that day. `days_to_expiry` counts calendar days from the data's day, not from today; 0 means
    the contracts expired at that day's close."""
    clean = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        expiry, seen = _iso_day(r.get("expiry_date")), _iso_day(r.get("latest_seen"))
        if expiry and seen:
            clean.append((expiry, seen, (_qty(r.get("ce_count")) or 0) + (_qty(r.get("pe_count")) or 0)))
    if not clean:
        return None, []
    as_of = max(seen for _, seen, _ in clean)  # ISO days sort as text
    day = date.fromisoformat(as_of)
    out = [
        {"expiry": expiry, "days_to_expiry": (date.fromisoformat(expiry) - day).days}
        for expiry, seen, options in clean
        if seen == as_of and expiry >= as_of and options > 0
    ]
    out.sort(key=lambda e: e["expiry"])
    return as_of, out


def shape_futures(rows: Iterable[Any], spot: Optional[float]) -> List[Dict[str, Any]]:
    """Futures contracts, nearest expiry first, each with its basis to `spot`."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        # A futures row carries no option side: the current format marks it "FUT", the older one leaves it empty.
        if not isinstance(r, dict) or r.get("option_type") in _OPTION_SIDES:
            continue
        expiry = _iso_day(r.get("expiry_date"))
        if not expiry:
            continue
        settle = _num(r.get("settle_price"))
        out.append({
            "expiry": expiry,
            "close": _num(r.get("close_price")),
            "settle": settle,
            "oi": _qty(r.get("open_interest")),
            "change_in_oi": _qty(r.get("change_in_oi")),
            "volume": _qty(r.get("traded_volume")),
            "basis": futures_basis(settle, spot),
        })
    out.sort(key=lambda f: f["expiry"])
    return out


# ── data platform ────────────────────────────────────────────────────────────

def no_data(sym: str) -> str:
    return f"No F&O data for {sym}"


def not_found_message(sym: str, body: Any) -> Optional[str]:
    """The plain sentence for a data-platform 404 this module understands, else None. A 404 with any other
    body (a missing route, a proxy page) says nothing about the underlying, so it is not passed off as
    "no data"."""
    # The data platform wraps its errors as {"error": {"message": …}}; a bare FastAPI error is {"detail": …}.
    detail = None
    if isinstance(body, dict):
        error = body.get("error")
        detail = error.get("message") if isinstance(error, dict) else body.get("detail")
    if not isinstance(detail, str):
        return None
    d = detail.lower()
    if d.startswith("no f&o data"):
        return no_data(sym)
    if d.startswith("no upcoming expiry"):
        return f"No option contracts are listed for {sym}"
    return None


async def _daas(path: str, params: Dict[str, Any], sym: str) -> Dict[str, Any]:
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw(path, params or None)
    except daas_client.DaasError as e:
        logger.warning("fno DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict):
        return body
    if status == 404:
        message = not_found_message(sym, body)
        if message:
            raise HTTPException(status_code=404, detail=message)
    logger.warning("fno DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/{symbol}/expiries")
async def expiries(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=SYMBOL_MAX, pattern=SYMBOL_PATTERN),
) -> Dict[str, Any]:
    """Option expiries still listed on the latest trading day, nearest first."""
    await get_current_user(request)
    sym = symbol.upper()
    body = await _daas(f"/fno/{sym}/expiries", {}, sym)
    as_of, rows = live_option_expiries(body.get("data"))
    if as_of is None:
        raise HTTPException(status_code=404, detail=no_data(sym))
    return {"symbol": sym, "as_of": as_of, "expiries": rows, "count": len(rows)}


@router.get("/{symbol}/chain")
async def chain(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=SYMBOL_MAX, pattern=SYMBOL_PATTERN),
    expiry: Optional[date] = Query(None, description="Expiry YYYY-MM-DD; default = the nearest on or after the data's day"),
    around: int = Query(DEFAULT_AROUND, ge=1, le=MAX_AROUND, description="Strikes sent each side of the ATM strike"),
) -> Dict[str, Any]:
    """One expiry's calls and puts by strike. `summary` is worked out over every strike of the expiry;
    `strikes` holds only the window around the ATM strike."""
    await get_current_user(request)
    sym = symbol.upper()
    body = await _daas(f"/fno/{sym}/chain", {"expiry": expiry.isoformat()} if expiry else {}, sym)
    as_of, exp = _iso_day(body.get("as_of")), _iso_day(body.get("expiry"))
    if not as_of or not exp:
        logger.warning("fno DaaS /fno/%s/chain answered without a day or an expiry", sym)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    raw = body.get("strikes")
    strikes = shape_strikes(raw)
    if not strikes:
        raise HTTPException(status_code=404, detail=f"No option contracts for {sym} expiring {exp}")
    sides = [item.get(side) for item in raw if isinstance(item, dict) for side in _OPTION_SIDES]
    summary = summarise_chain(strikes, find_spot(sides), as_of, exp)
    shown = window_around(strikes, summary["atm_strike"], around)
    return {
        "symbol": sym, "summary": summary, "lot_size": find_lot_size(sides),
        "strikes": shown, "strike_count": len(strikes), "strikes_returned": len(shown),
    }


@router.get("/{symbol}/futures")
async def futures(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=SYMBOL_MAX, pattern=SYMBOL_PATTERN),
) -> Dict[str, Any]:
    """The latest trading day's futures contracts for the underlying, nearest expiry first."""
    await get_current_user(request)
    sym = symbol.upper()
    # An underlying is an index or a stock, never both, and the bhavcopy does not say which without a read.
    bodies = await asyncio.gather(*(
        _daas(f"/fno/{sym}", {"instrument_type": kind, "limit": _FUTURES_LIMIT}, sym) for kind in _FUTURES_TYPES
    ))
    rows = [r for b in bodies for r in (b.get("data") if isinstance(b.get("data"), list) else []) if isinstance(r, dict)]
    days = [d for d in [*(_iso_day(b.get("as_of")) for b in bodies), *(_iso_day(r.get("as_of_date")) for r in rows)] if d]
    if not days:
        raise HTTPException(status_code=404, detail=no_data(sym))
    as_of = max(days)
    rows = [r for r in rows if _iso_day(r.get("as_of_date")) == as_of]
    spot = find_spot(rows)
    contracts = shape_futures(rows, spot)
    return {"symbol": sym, "as_of": as_of, "spot": spot, "lot_size": find_lot_size(rows), "futures": contracts, "count": len(contracts)}
