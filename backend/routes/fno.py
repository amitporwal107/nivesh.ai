"""F&O end-of-day data — app-side, read-only proxy over the data platform's NSE F&O bhavcopy.

    GET /api/fno/{symbol}/expiries               option expiries still listed on the latest day, nearest first
    GET /api/fno/{symbol}/chain?expiry=&around=  one expiry's chain by strike, plus a summary of the whole chain
    GET /api/fno/{symbol}/futures                the latest day's futures contracts, each with its basis and, once the
                                                 data platform sends prev_close_price, its day change and OI build-up
                                                 (the same rule as an option's `oi_buildup`, below)
    GET /api/fno/scan/buildup?date=              every F&O stock's futures OI build-up on the latest (or given) day,
                                                 passed through from DaaS /v1/desk/fno-buildup (definitions in
                                                 nidp/services/daas_api/routers/desk_market.py). It lives under /desk
                                                 there because the data platform's /fno/{symbol} would catch /fno/scan

The rows live in nidp.fno_bhavcopy, which only the data platform can read (DaaS /v1/fno/*,
nidp/services/daas_api/routers/fno.py), so each route forwards to it and shapes the answer. The data is end of
day: one row per contract per trading day, with prices, open interest, volume and the contract's lot size.
`lot_size` is null until the data platform's F&O routes send the bhavcopy's lot column (new_board_lot_qty).

Definitions (the pure functions below; tests/test_fno_routes.py works one example by hand):
    spot        the bhavcopy's underlying_price for the day (the first positive value among the rows)
    ATM strike  the strike nearest the spot; an exact tie goes to the lower strike
    PCR         total put open interest ÷ total call open interest, over every strike of the expiry
    max pain    the strike K where  Σ call OI(k) × max(K − k, 0)  +  Σ put OI(k) × max(k − K, 0)  is smallest:
                the total intrinsic value of every open call and put if the underlying settled at K
    basis       futures settle price − spot (positive = the future is at a premium to the spot)

Model estimates on the chain (services/option_pricing.py: Black-76 on a forward). The exchange file carries no
implied volatility, so every figure in this block is worked out here from end-of-day prices. Each is null when
it cannot be worked out; none is ever filled in with a guess.
    summary.days_to_expiry    calendar days from the data's day to the expiry
    summary.forward           the forward the expiry is priced on, and summary.forward_basis how it was found,
                              by the first rule that applies:
                              "future"           the settle price of the future expiring the same day
                              "put-call parity"  no such future (weekly index expiries): the forward the options
                                                 imply, F = K* + (C − P)·e^(rT), at the strike K* where the call
                                                 and the put are closest in price, among strikes whose call AND
                                                 put both traded that day (volume above zero; `parity_pairs`)
                              "carried spot"     no such strike either: spot × e^(rT). Calls and puts at one
                                                 strike can then disagree (see option_pricing)
    summary.rate_pct          r, the annual interest rate the model discounts and carries with, in percent
                              (option_pricing.RISK_FREE_RATE)
    call.iv / put.iv          implied volatility in percent a year, from the contract's settle price when it has
                              one, else its close; iv_price says which ("settle" | "close"; null with iv). A
                              contract with open interest but no trade that day is still priced, from the settle
                              price the exchange worked out for it. null when the contract neither traded nor
                              has open interest that day (zero volume AND zero open interest: its price is not a
                              market price), when it expires on the data's day, or when its price is at or below
                              intrinsic value
    delta gamma theta vega    per unit, at that implied volatility: delta and gamma per one-point move in the
                              forward, theta per calendar day, vega per one volatility point. null with iv
    summary.atm_iv            the mean of the call and put iv at the ATM strike (the one that exists if only one
                              does): the mean barely moves when the forward is a little off
    summary.expected_move     the ATM straddle: call close + put close at the ATM strike, in price points, and
    summary.expected_move_pct the same as a percent of the spot. A market price for movement to expiry, not a
                              forecast and not a probability. null on the expiry day itself
Model fields are null for the whole chain when the futures read fails: without it the route cannot tell
whether a future expires with the options, and the forward is not guessed.

Day change (null until the data platform's chain query sends prev_close_price):
    call.change / put.change  close − previous close, and change_pct the same in percent
    oi_buildup                how the contract's price and open interest moved together that day:
                              price up + OI up "long build-up", price down + OI up "short build-up",
                              price up + OI down "short covering", price down + OI down "long unwinding".
                              A reading of two figures, not a record of who traded. null when either is flat

Errors: an underlying with no F&O rows is 404 with a plain sentence. An unreachable or failing data platform is
502 upstream_unavailable, as on /api/movers and /api/move-odds, never an empty or an older answer.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from fastapi import APIRouter, HTTPException, Path, Query, Request

from deps import get_current_user
from services import option_pricing
from services.copilot_tools import daas_client
from services.fno_candidates import engine as fno_engine
from services.fno_candidates import rules as fno_rules
from services import fno_forward

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
        # The walls a trader reads as a floor and a ceiling: the heaviest put strike AT OR BELOW the spot and the heaviest call strike AT OR ABOVE it.
        # After a sharp move the heaviest strike over every strike can be an in-the-money one opened when the price was elsewhere (a "put wall" above the price).
        "put_wall": top_oi_strike([(k, p) for k, _, p in oi if spot is not None and k <= spot], spot),
        "call_wall": top_oi_strike([(k, c) for k, c, _ in oi if spot is not None and k >= spot], spot),
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
    """Futures contracts, nearest expiry first, each with its basis to `spot` and its day change (`day_change`:
    change, change_pct and oi_buildup, all null until the data platform's /fno/{symbol} sends prev_close_price)."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        # A futures row carries no option side: the current format marks it "FUT", the older one leaves it empty.
        if not isinstance(r, dict) or r.get("option_type") in _OPTION_SIDES:
            continue
        expiry = _iso_day(r.get("expiry_date"))
        if not expiry:
            continue
        settle = _num(r.get("settle_price"))
        contract = {
            "expiry": expiry,
            "close": _num(r.get("close_price")),
            "settle": settle,
            "oi": _qty(r.get("open_interest")),
            "change_in_oi": _qty(r.get("change_in_oi")),
            "volume": _qty(r.get("traded_volume")),
            "basis": futures_basis(settle, spot),
        }
        contract["prev_close"] = _positive(r.get("prev_close_price"))
        contract.update(day_change(r, contract))
        out.append(contract)
    out.sort(key=lambda f: f["expiry"])
    return out


# ── model estimates (Black-76) ───────────────────────────────────────────────

_MODEL_FIELDS = ("iv", "iv_price", "delta", "gamma", "theta", "vega")
_SIDE_KIND = {"call": "CE", "put": "PE"}


def _positive(v: Any) -> Optional[float]:
    f = _num(v)
    return f if f is not None and f > 0 else None


def model_price_source(side: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """(the price implied volatility is read from, which field it is): the settle price when the contract has
    one, else its close. (None, None) when it has neither."""
    for field in ("settle", "close"):
        px = _positive(side.get(field))
        if px is not None:
            return px, field
    return None, None


def model_price(side: Dict[str, Any]) -> Optional[float]:
    """The price implied volatility is read from: the settle price when the contract has one, else its close."""
    return model_price_source(side)[0]


def is_live(side: Dict[str, Any]) -> bool:
    """False for a contract with zero volume AND zero open interest that day: nobody traded or holds it, so
    its price is the exchange's placeholder, not a market price. A missing figure counts as zero."""
    return bool(side.get("volume")) or bool(side.get("oi"))


def traded(side: Any) -> bool:
    """True for a contract that traded on the data's day: volume above zero."""
    return isinstance(side, dict) and bool(side.get("volume"))


def parity_pairs(strikes: Iterable[Dict[str, Any]]) -> List[Tuple[float, float, float]]:
    """(strike, call price, put price) for the strikes the put-call-parity forward may be read from.

    A strike qualifies only when it is live on both sides, and live here means exactly this: the call AND the
    put each traded on the data's day (volume above zero) and each has a price above zero. That is stricter
    than the rule for showing an implied volatility (`is_live`: volume OR open interest): a contract that is
    held but did not trade carries the exchange's theoretical settle price, which is worked out from the spot,
    so a pair containing one would hand back the exchange's carried spot instead of the market's forward. The
    prices are the ones implied volatility is read from (settle, else close)."""
    pairs: List[Tuple[float, float, float]] = []
    for r in strikes:
        call, put = r.get("call"), r.get("put")
        if traded(call) and traded(put):
            c, p = model_price(call), model_price(put)
            if c is not None and p is not None:
                pairs.append((float(r["strike"]), c, p))
    return pairs


def model_side(kind: str, side: Dict[str, Any], strike: float, forward: Optional[float], t: float) -> Dict[str, Any]:
    """{iv, iv_price, delta, gamma, theta, vega} for one contract; every value None when implied volatility
    cannot be worked out. `iv` is in percent a year; `iv_price` names the price it was read from."""
    out: Dict[str, Any] = dict.fromkeys(_MODEL_FIELDS)
    if forward is None or not is_live(side):
        return out
    px, field = model_price_source(side)
    vol = option_pricing.implied_vol(kind, px, forward, strike, t)
    g = option_pricing.greeks(kind, forward, strike, t, vol)
    if vol is None or g is None:
        return out
    return {"iv": round(vol * 100, 2), "iv_price": field, "delta": round(g.delta, 4), "gamma": round(g.gamma, 8),
            "theta": round(g.theta, 4), "vega": round(g.vega, 4)}


def add_model(strikes: Sequence[Dict[str, Any]], forward: Optional[float], t: float) -> List[Dict[str, Any]]:
    """The strike rows with the model fields added to each side that exists."""
    out: List[Dict[str, Any]] = []
    for r in strikes:
        row = dict(r)
        for name, kind in _SIDE_KIND.items():
            if r[name] is not None:
                row[name] = {**r[name], **model_side(kind, r[name], float(r["strike"]), forward, t)}
        out.append(row)
    return out


def atm_iv(row: Optional[Dict[str, Any]]) -> Optional[float]:
    """Mean of the call and put implied volatility at the ATM strike; the one that exists when only one does."""
    ivs = [side["iv"] for side in ((row or {}).get("call"), (row or {}).get("put")) if side and side.get("iv") is not None]
    return round(sum(ivs) / len(ivs), 2) if ivs else None


def straddle(row: Optional[Dict[str, Any]]) -> Optional[float]:
    """Call close + put close at one strike. None unless both closed above zero."""
    call, put = _positive(((row or {}).get("call") or {}).get("close")), _positive(((row or {}).get("put") or {}).get("close"))
    return None if call is None or put is None else round(call + put, 2)


def same_expiry_future(rows: Optional[Iterable[Any]], as_of: str, expiry: str) -> Optional[float]:
    """The settle price of the future that expires on `expiry`, from the futures rows of the day `as_of`."""
    for f in shape_futures([r for r in rows or [] if isinstance(r, dict) and _iso_day(r.get("as_of_date")) == as_of], None):
        if f["expiry"] == expiry and _positive(f["settle"]) is not None:
            return f["settle"]
    return None


def model_summary(as_of: str, expiry: str, spot: Optional[float], futures_rows: Optional[Iterable[Any]],
                  strikes: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """days_to_expiry, forward, forward_basis and rate_pct. `strikes` are every strike of the expiry: the
    put-call-parity forward is read from them when no future expires that day. `futures_rows` is None when the
    futures read failed: no forward is then chosen, because anything else would be a guess at whether a future
    exists."""
    days = option_pricing.days_between(date.fromisoformat(as_of), date.fromisoformat(expiry))
    chosen = None
    if days > 0 and futures_rows is not None:
        chosen = option_pricing.choose_forward(
            same_expiry_future(futures_rows, as_of, expiry), spot, option_pricing.year_fraction(days), pairs=parity_pairs(strikes))
    return {
        "days_to_expiry": days,
        "forward": round(chosen[0], 2) if chosen else None,
        "forward_basis": chosen[1] if chosen else None,
        "rate_pct": round(option_pricing.RISK_FREE_RATE * 100, 4),
    }


def expected_move(atm_row: Optional[Dict[str, Any]], spot: Optional[float], days: int) -> Tuple[Optional[float], Optional[float]]:
    """(ATM straddle in price points, the same as a percent of the spot). None on or after the expiry day."""
    move = straddle(atm_row) if days > 0 else None
    pct = round(move / spot * 100, 2) if move is not None and spot is not None and spot > 0 else None
    return move, pct


# ── day change ───────────────────────────────────────────────────────────────

def day_change(raw: Any, side: Dict[str, Any]) -> Dict[str, Any]:
    """{change, change_pct, oi_buildup} for one contract, from the data platform's row and its shaped side.
    All None when the row carries no previous close (the column is not sent until the data platform is
    redeployed)."""
    prev = _positive(raw.get("prev_close_price")) if isinstance(raw, dict) else None
    close = _positive(side.get("close"))
    if prev is None or close is None:
        return {"change": None, "change_pct": None, "oi_buildup": None}
    change, d_oi = round(close - prev, 2), side.get("change_in_oi")
    label = None
    if change and d_oi:
        label = ("long build-up" if change > 0 else "short build-up") if d_oi > 0 else ("short covering" if change > 0 else "long unwinding")
    return {"change": change, "change_pct": round(change / prev * 100, 2), "oi_buildup": label}


def add_day_change(strikes: Sequence[Dict[str, Any]], raw: Any) -> List[Dict[str, Any]]:
    """The strike rows with change, change_pct and oi_buildup added to each side that exists."""
    by_strike = {_tidy(_num(item.get("strike"))): item for item in (raw if isinstance(raw, list) else []) if isinstance(item, dict)}
    out: List[Dict[str, Any]] = []
    for r in strikes:
        row, item = dict(r), by_strike.get(r["strike"], {})
        for name, kind in _SIDE_KIND.items():
            if r[name] is not None:
                row[name] = {**r[name], **day_change(item.get(kind), r[name])}
        out.append(row)
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


async def _futures_rows(sym: str) -> Tuple[List[Dict[str, Any]], List[Optional[str]]]:
    """(every futures row the data platform has for the latest day, the day each read said it was for)."""
    # An underlying is an index or a stock, never both, and the bhavcopy does not say which without a read.
    bodies = await asyncio.gather(*(
        _daas(f"/fno/{sym}", {"instrument_type": kind, "limit": _FUTURES_LIMIT}, sym) for kind in _FUTURES_TYPES
    ))
    rows = [r for b in bodies for r in (b.get("data") if isinstance(b.get("data"), list) else []) if isinstance(r, dict)]
    return rows, [_iso_day(b.get("as_of")) for b in bodies]


async def _futures_rows_or_none(sym: str) -> Optional[List[Dict[str, Any]]]:
    """The futures rows for the chain's forward, or None when the read failed (the chain is still answered,
    without model estimates)."""
    try:
        return (await _futures_rows(sym))[0]
    except HTTPException as e:
        logger.warning("fno futures read for the %s chain failed (%s): model estimates are left out", sym, e.detail)
        return None


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
    `strikes` holds only the window around the ATM strike.

    Each side also carries the model estimates iv, delta, gamma, theta and vega (Black-76 on the forward in
    `summary.forward`; see the module docstring). A contract with zero volume AND zero open interest is
    skipped: its iv and Greeks are null, because its price is not a market price."""
    await get_current_user(request)
    sym = symbol.upper()
    # The forward for the expiry is the future that expires with it, so the futures are read alongside.
    futures_read = asyncio.ensure_future(_futures_rows_or_none(sym))
    try:
        body = await _daas(f"/fno/{sym}/chain", {"expiry": expiry.isoformat()} if expiry else {}, sym)
    except BaseException:
        futures_read.cancel()
        raise
    futures_rows = await futures_read
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
    summary.update(model_summary(as_of, exp, summary["spot"], futures_rows, strikes))
    t = option_pricing.year_fraction(summary["days_to_expiry"])
    shown = add_day_change(window_around(strikes, summary["atm_strike"], around), raw)
    # Priced on the forward exactly as it is sent (2 decimals), so every figure can be reproduced from the response.
    shown = add_model(shown, summary["forward"], t)
    # The window is centred on the ATM strike, so its row is among the ones just priced.
    atm_row = next((r for r in shown if r["strike"] == summary["atm_strike"]), None)
    summary["atm_iv"] = atm_iv(atm_row)
    summary["expected_move"], summary["expected_move_pct"] = expected_move(atm_row, summary["spot"], summary["days_to_expiry"])
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
    rows, read_days = await _futures_rows(sym)
    days = [d for d in [*read_days, *(_iso_day(r.get("as_of_date")) for r in rows)] if d]
    if not days:
        raise HTTPException(status_code=404, detail=no_data(sym))
    as_of = max(days)
    rows = [r for r in rows if _iso_day(r.get("as_of_date")) == as_of]
    spot = find_spot(rows)
    contracts = shape_futures(rows, spot)
    return {"symbol": sym, "as_of": as_of, "spot": spot, "lot_size": find_lot_size(rows), "futures": contracts, "count": len(contracts)}


_FORWARD_CACHE: Dict[str, Any] = {"ts": 0.0, "key": None, "bars": None}
_FORWARD_TTL = 1800.0


async def _forward_bars(symbols: List[str], start: str, end: str) -> Dict[str, List[Dict[str, Any]]]:
    """Adjusted bars for the universe, read through the data platform in chunks and kept for half an hour."""
    import time
    key = (len(symbols), start, end)
    if _FORWARD_CACHE["bars"] is not None and _FORWARD_CACHE["key"] == key and time.time() - _FORWARD_CACHE["ts"] < _FORWARD_TTL:
        return _FORWARD_CACHE["bars"]
    out: Dict[str, List[Dict[str, Any]]] = {}
    for i in range(0, len(symbols), 250):
        got = await daas_client.get_adjusted_prices_bulk(symbols[i:i + 250], start=start, end=end, timeout=60.0)
        out.update({str(k).upper(): v for k, v in (got or {}).items()})
    _FORWARD_CACHE.update({"ts": time.time(), "key": key, "bars": out})
    return out


@router.get("/forward-test")
async def forward_test(request: Request) -> Dict[str, Any]:
    """The forward test of near-month short build-up (services/fno_forward): how many sessions have been RECORDED, how many signals, how many are judged (5 sessions on), and, only once 30
    sessions are judged, the pooled result net of the assumed cost. Signals are recorded when a session's data is in (scripts/record_fno_forward.py) and never reconstructed. Read only."""
    await get_current_user(request)
    from deps import db
    base = {"version": fno_forward.VERSION, "hypothesis": fno_forward.HYPOTHESIS, "horizon_sessions": fno_forward.HORIZON, "cost_pct": fno_forward.COST_PCT,
            "min_sessions": fno_forward.MIN_SESSIONS, "settings_recorded": list(fno_forward.SETTINGS), "read_only": True,
            "past_result": "Inconclusive in the one-year study (permutation p 0.02 for the production floors, 0.06 for the first frozen setting; 50 pooled sessions); not validated.",
            "not_recorded": "The five frozen volume-floor settings are not recorded: they need 20 sessions of the contract's own volume at signal time."}
    try:
        docs = [d async for d in db[fno_forward.COLLECTION].find({}, {"_id": 0}).sort("as_of", 1)]
    except Exception as e:  # noqa: BLE001
        logger.warning("fno forward test: the records could not be read (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if not docs:
        return {**base, "started": False, "recorded_sessions": 0, "last_recorded": None, "settings": {}}
    symbols = sorted({s for d in docs for s in (d.get("universe_symbols") or [])})
    start = (date.fromisoformat(docs[0]["as_of"]) - timedelta(days=5)).isoformat()
    try:
        bars = await _forward_bars(symbols, start, date.today().isoformat())
    except Exception as e:  # noqa: BLE001 — the counts are still true; the judgement needs prices
        logger.warning("fno forward test: prices unavailable (%s)", type(e).__name__)
        bars = {}
    ev = fno_forward.evaluate(docs, bars)
    return {**base, "started": True, "recorded_sessions": len(docs), "last_recorded": docs[-1]["as_of"], "prices_available": bool(bars), "settings": ev["settings"]}


@router.get("/scan/buildup")
async def scan_buildup(
    request: Request,
    day: Optional[date] = Query(None, alias="date", description="Trading day YYYY-MM-DD; default = the latest"),
) -> Dict[str, Any]:
    """Every F&O stock's futures on one day, one row per underlying: the nearest expiry's price change, open interest
    and its change summed over all expiries, and the build-up label (long_buildup, short_buildup, short_covering,
    long_unwinding, neutral). Passed through unchanged; a day with no rows is 200 with `rows: []`."""
    await get_current_user(request)
    body = await _daas("/desk/fno-buildup", {"date": day.isoformat()} if day else {}, "stock futures")
    if not isinstance(body.get("rows"), list):
        logger.warning("fno DaaS /desk/fno-buildup answered without rows")
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    return body


@router.get("/scan/candidates")
async def scan_candidates(
    request: Request,
    per: int = Query(fno_rules.PER_DEFAULT, ge=1, le=fno_rules.PER_MAX, description="Candidates per build-up category"),
    day: Optional[date] = Query(None, alias="date", description="Trading day YYYY-MM-DD; default = the latest"),
) -> Dict[str, Any]:
    """The top candidates of each build-up category (long build-up, short build-up, short covering, long unwinding) among the
    liquid F&O stocks, each with five confirmations (cash, relative volume, delivery, trend, momentum), a fundamental context
    rating and the figures behind them; plus NIFTY and BANKNIFTY from the same scan. Joins the build-up scan with one bulk read
    of the engineered features. Read only. The ranking counts confirmations: it is not a probability, and no strategy is ranked
    by profit here (the plan engine is asked per candidate, from `plan_inputs`). The features failing leaves every analysis
    reading unknown: the candidates are still listed from the scan."""
    await get_current_user(request)
    body = await _daas("/desk/fno-buildup", {"date": day.isoformat()} if day else {}, "stock futures")
    if not isinstance(body.get("rows"), list):
        logger.warning("fno DaaS /desk/fno-buildup answered without rows")
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    pools = fno_engine.select_pools(body)
    symbols = fno_engine.pool_symbols(pools)
    features: Dict[str, List[Dict[str, Any]]] = {}
    as_of = _iso_day(body.get("as_of"))
    if symbols and as_of:
        try:
            features = await daas_client.get_features_bulk(
                symbols, start=(date.fromisoformat(as_of) - timedelta(days=14)).isoformat(), end=as_of)
        except Exception as e:  # noqa: BLE001 — the scan alone still answers; the analysis readings are then unknown
            logger.warning("fno candidates: the features read failed (%s)", type(e).__name__)
            features = {}
    return fno_engine.assemble(body, pools, features, per)
