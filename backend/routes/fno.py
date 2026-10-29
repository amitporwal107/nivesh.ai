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
    GET /api/fno/{symbol}/futures/oi-buildup?interval=15m&window=4&sessions=2
                                                 the current / next / far month futures AND consolidated (the three
                                                 summed), per N-bar window: price change, OI change, volume and the
                                                 build-up class, with the snapshot time. Kite candles with OI when the
                                                 platform Kite session works, else the latest bhavcopy day per expiry
                                                 labelled end of day (services/fno_oi_windows.py). Intraday, each
                                                 contract and consolidated also carry `bars` [[t, close, volume, oi]]
                                                 (the sessions sent plus one baseline bar). Read only
    GET /api/fno/{symbol}/options/intraday?interval=15m&sessions=2&strikes=5
                                                 the nearest expiry's calls and puts at the ATM strike ± `strikes` (max
                                                 8): Kite candles with OI per contract, and per candle time the CE / PE
                                                 OI and volume summed, the OI changes and the PCR
                                                 (services/fno_options_intraday.py). 200 with `availability` naming why
                                                 when Kite cannot answer. Read only
    GET /api/fno/{symbol}/iv-history?days=&bucket=  the recorded daily ATM implied volatility of the underlying, with IV
                                                 rank and IV percentile once 252 sessions are recorded
                                                 (services/fno_iv_history; written by scripts/record_iv_history.py
                                                 from `session_iv` below, the chain's own model on one session's rows)

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
from pydantic import BaseModel, Field

from deps import get_current_user
from services import option_pricing
from services.copilot_tools import daas_client
from services.fno_candidates import engine as fno_engine
from services.fno_candidates import rules as fno_rules
from services import fno_forward
from services import fno_iv_history
from services import fno_margin
from services import fno_oi_windows

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


# ── one session's ATM implied volatility (the IV history) ───────────────────
# The chain route's own calculation, run on one past (or the latest) session's rows: the same spot, ATM strike,
# forward and Black-76 implied volatility, so a recorded figure equals the chain's `summary.atm_iv` for that expiry
# on that day. Buckets: near_month is the first futures expiry strictly after the session, next_month the second.
# On an expiry day the expiring month has no time left (its IV is null in the chain), so it is not a bucket.

IV_BUCKET_FIELDS = ("expiry", "days_to_expiry", "atm_strike", "spot", "future_settle", "forward", "forward_basis",
                    "call_iv", "call_iv_price", "put_iv", "put_iv_price", "atm_iv", "reason")


def session_expiries(day: str, futures_rows: Iterable[Any]) -> List[str]:
    """The futures expiries listed on `day` that fall strictly after it, nearest first."""
    rows = [r for r in futures_rows if isinstance(r, dict) and _iso_day(r.get("as_of_date")) == day]
    return sorted({f["expiry"] for f in shape_futures(rows, None) if f["expiry"] > day})


def _chain_rows(rows: Iterable[Any]) -> List[Dict[str, Any]]:
    """Option rows of one expiry, as the data platform sends them from /fno/{symbol}, regrouped into the
    {strike, CE, PE} list that /fno/{symbol}/chain sends, so the chain's own shaping reads them."""
    chain: Dict[float, Dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("option_type") not in _OPTION_SIDES:
            continue
        k = _num(r.get("strike_price"))
        if k is None or k <= 0:
            continue
        chain.setdefault(k, {"strike": k, "CE": None, "PE": None})[r["option_type"]] = r
    return [chain[k] for k in sorted(chain)]


def expiry_atm_iv(day: str, expiry: str, futures_rows: Sequence[Any], rows: Iterable[Any]) -> Dict[str, Any]:
    """The ATM implied volatility of one expiry on one session, exactly as the chain route works it out
    (find_spot, atm_strike, model_summary, add_model, atm_iv), with the inputs it used. `atm_iv` is null with a
    `reason` when it cannot be worked out; nothing is filled in."""
    out: Dict[str, Any] = dict.fromkeys(IV_BUCKET_FIELDS)
    out["expiry"] = expiry
    raw = _chain_rows(rows)
    strikes = shape_strikes(raw)
    if not strikes:
        out["reason"] = f"no option contracts expiring {expiry} in the rows for {day}"
        return out
    spot = find_spot([item.get(side) for item in raw for side in _OPTION_SIDES])
    summary = model_summary(day, expiry, spot, futures_rows, strikes)
    k = _tidy(atm_strike([float(r["strike"]) for r in strikes], spot))
    out.update(days_to_expiry=summary["days_to_expiry"], atm_strike=k, spot=spot, forward=summary["forward"],
               forward_basis=summary["forward_basis"], future_settle=same_expiry_future(futures_rows, day, expiry))
    if spot is None:
        out["reason"] = "no underlying price in the day's rows, so no ATM strike"
        return out
    if summary["forward"] is None:
        out["reason"] = "no forward: no same-expiry future, no strike whose call and put both traded, and no time left or no spot"
        return out
    atm_row = next((r for r in strikes if r["strike"] == k), None)
    priced = add_model([atm_row], summary["forward"], option_pricing.year_fraction(summary["days_to_expiry"]))[0]
    for name in _SIDE_KIND:
        side = priced.get(name) or {}
        out[f"{name}_iv"], out[f"{name}_iv_price"] = side.get("iv"), side.get("iv_price")
    out["atm_iv"] = atm_iv(priced)
    if out["atm_iv"] is None:
        out["reason"] = ("neither the ATM call nor the ATM put has an implied volatility (no trade and no open interest, "
                         "or a price at or below intrinsic value)")
    return out


def session_iv(day: str, futures_rows: Sequence[Any], rows_by_expiry: Dict[str, Sequence[Any]]) -> Dict[str, Dict[str, Any]]:
    """{bucket: expiry_atm_iv(...)} for each bucket in fno_iv_history.BUCKETS. A bucket with no futures expiry
    to name it (or no rows read for that expiry) is all null with the reason."""
    expiries = session_expiries(day, futures_rows)
    out: Dict[str, Dict[str, Any]] = {}
    for i, name in enumerate(fno_iv_history.BUCKETS):
        expiry = expiries[i] if i < len(expiries) else None
        if expiry is not None and expiry in rows_by_expiry:
            out[name] = expiry_atm_iv(day, expiry, futures_rows, rows_by_expiry[expiry])
        else:
            blank = dict.fromkeys(IV_BUCKET_FIELDS)
            blank["expiry"] = expiry
            blank["reason"] = (f"no option rows were read for the {expiry} expiry" if expiry
                               else f"the rows for {day} list fewer than {i + 1} futures expiries after that day")
            out[name] = blank
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


# One expiry of one underlying on one day is a few hundred rows (NIFTY's busiest is under 1,000); 5,000 is the data
# platform's page limit. More pages than this is not a chain this module expects, so it is refused, not truncated.
_SESSION_PAGE = 5000
_SESSION_MAX_PAGES = 4


def _rows_for_day(body: Dict[str, Any], day: str, what: str) -> List[Dict[str, Any]]:
    """The rows of a /fno/{symbol}?on=day answer. An answer for any other day (a data platform that ignored `on`
    and sent its latest day) is a failed read, never another day's figures under this day's name."""
    rows = [r for r in (body.get("data") if isinstance(body.get("data"), list) else []) if isinstance(r, dict)]
    if _iso_day(body.get("as_of")) != day or any(_iso_day(r.get("as_of_date")) != day for r in rows):
        logger.warning("fno DaaS %s answered for another day than %s", what, day)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    return rows


async def _session_expiry_rows(sym: str, day: str, expiry: str) -> List[Dict[str, Any]]:
    """Every row (future, calls and puts) of one expiry on one day, through every page."""
    rows: List[Dict[str, Any]] = []
    offset = 0
    for _ in range(_SESSION_MAX_PAGES):
        body = await _daas(f"/fno/{sym}", {"on": day, "expiry": expiry, "limit": _SESSION_PAGE, "offset": offset}, sym)
        page = _rows_for_day(body, day, f"/fno/{sym} {expiry}")
        rows.extend(page)
        nxt = (body.get("pagination") or {}).get("next_offset") if isinstance(body.get("pagination"), dict) else None
        if not page or not isinstance(nxt, int) or isinstance(nxt, bool):
            return rows
        offset = nxt
    logger.warning("fno DaaS /fno/%s %s on %s ran past %d pages: refused, not truncated", sym, expiry, day, _SESSION_MAX_PAGES)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)


async def read_session(sym: str, day: str) -> Optional[Dict[str, Any]]:
    """The bhavcopy rows one session's IV history row is worked out from: {"futures": the day's futures rows,
    "expiries": {expiry: that expiry's rows} for the bucket expiries}. None when the data platform has no futures
    rows for the day (a holiday, a day not loaded, or no F&O on the underlying): nothing to record, nothing filled
    in. A failed read, or an answer for another day, raises HTTPException (the caller counts it as failed)."""
    bodies = await asyncio.gather(*(
        _daas(f"/fno/{sym}", {"on": day, "instrument_type": kind, "limit": _FUTURES_LIMIT}, sym) for kind in _FUTURES_TYPES
    ))
    futures_rows = [r for kind, b in zip(_FUTURES_TYPES, bodies) for r in _rows_for_day(b, day, f"/fno/{sym} {kind}")]
    if not futures_rows:
        return None
    expiries = session_expiries(day, futures_rows)[:len(fno_iv_history.BUCKETS)]
    by_expiry = {e: await _session_expiry_rows(sym, day, e) for e in expiries}
    return {"futures": futures_rows, "expiries": by_expiry}


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
    as_of, spot, lot_size, contracts = await _latest_futures(sym)
    return {"symbol": sym, "as_of": as_of, "spot": spot, "lot_size": lot_size, "futures": contracts, "count": len(contracts)}


async def _latest_futures(sym: str) -> Tuple[str, Optional[float], Optional[int], List[Dict[str, Any]]]:
    """(the latest day, spot, lot size, that day's shaped futures nearest first). 404 when there are none."""
    rows, read_days = await _futures_rows(sym)
    days = [d for d in [*read_days, *(_iso_day(r.get("as_of_date")) for r in rows)] if d]
    if not days:
        raise HTTPException(status_code=404, detail=no_data(sym))
    as_of = max(days)
    rows = [r for r in rows if _iso_day(r.get("as_of_date")) == as_of]
    spot = find_spot(rows)
    return as_of, spot, find_lot_size(rows), shape_futures(rows, spot)


OI_INTERVALS = ("5m", "15m", "30m", "60m")


@router.get("/{symbol}/futures/oi-buildup")
async def futures_oi_buildup(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=SYMBOL_MAX, pattern=SYMBOL_PATTERN),
    interval: str = Query("15m", description="5m | 15m | 30m | 60m"),
    window: int = Query(4, ge=1, le=12, description="Bars per window"),
    sessions: int = Query(2, ge=1, le=5, description="Sessions of windows sent"),
) -> Dict[str, Any]:
    """The futures' OI build-up by window for the current / next / far month and consolidated (services/fno_oi_windows.py).
    Kite candles with open interest when the platform Kite session works (mode intraday); otherwise the latest bhavcopy day
    per expiry (mode end_of_day, `kite_reason` says why). Read only: nothing is written and nothing is sent to a broker."""
    await get_current_user(request)
    if interval not in OI_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {', '.join(OI_INTERVALS)}")
    sym = symbol.upper()
    from routes.research_chart_intraday import get_service
    from services.kite_live_feed import config as kite_cfg
    from services.kite_live_feed.feed import get_feed
    from services.kite_live_feed.intraday import INTERVALS as KITE_INTERVALS
    await _refresh_platform_token()
    try:
        st = await get_feed().read_status() or {}
    except Exception as e:  # noqa: BLE001 — the feed status only sets the cache time
        logger.warning("fno oi-buildup: feed status unreadable (%s)", type(e).__name__)
        st = {}
    try:
        # One extra session is read as the baseline of the first window shown (fno_oi_windows.trim).
        raw = await get_service().futures_bars(sym, interval, sessions + 1, session_open=st.get("session") == "open")
        kite_reason = None if raw.get("availability") == "ok" else raw.get("availability")
    except RuntimeError:
        raw, kite_reason = None, "upstream_unavailable"
    if raw is not None and kite_reason is None:
        from datetime import datetime as _dt, timezone as _tz
        return fno_oi_windows.intraday_answer(sym, raw, interval, KITE_INTERVALS[interval][1], window, sessions,
                                              _dt.now(_tz.utc).astimezone(kite_cfg.IST))
    as_of, _spot, _lot, contracts = await _latest_futures(sym)
    return fno_oi_windows.eod_answer(sym, as_of, contracts, kite_reason)


async def _option_ref(spot: str) -> Optional[Dict[str, Any]]:
    """Today's Kite price of the options' cash symbol (live quote in the session, the saved Kite close after it), or None."""
    from services.kite_live_feed import day_quote
    from services.kite_live_feed.gateway import canon
    dq = await day_quote.day_quotes([spot])
    q = (dq.get("quotes") or {}).get(canon(spot))
    price = _positive((q or {}).get("ltp"))
    if q is None or price is None or dq.get("source") not in ("kite_live", "kite_close"):
        return None
    at = q.get("exchange_ts") or dq.get("as_of")
    return {"price": price, "source": dq["source"], "at": str(at) if at is not None else None}


@router.get("/{symbol}/options/intraday")
async def options_intraday(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=SYMBOL_MAX, pattern=SYMBOL_PATTERN),
    interval: str = Query("15m", description="5m | 15m | 30m | 60m"),
    sessions: int = Query(2, ge=1, le=5, description="Sessions of candles sent"),
    strikes: int = Query(5, ge=1, le=8, description="Listed strikes each side of the ATM strike"),
) -> Dict[str, Any]:
    """The nearest expiry's calls and puts around the ATM strike, Kite candles with open interest, and their per-candle sums
    (services/fno_options_intraday.py). Reloads the stored platform Kite login first. 200 with `availability` other than ok
    when Kite cannot answer. Read only: nothing is written and nothing is sent to a broker."""
    await get_current_user(request)
    if interval not in OI_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {', '.join(OI_INTERVALS)}")
    sym = symbol.upper()
    from routes.research_chart_intraday import get_service
    from services.kite_live_feed.feed import get_feed
    await _refresh_platform_token()
    try:
        st = await get_feed().read_status() or {}
    except Exception as e:  # noqa: BLE001 — the feed status only sets the cache time
        logger.warning("fno options intraday: feed status unreadable (%s)", type(e).__name__)
        st = {}
    return await get_service().options_intraday(sym, interval, sessions, strikes, session_open=st.get("session") == "open",
                                                ref_getter=_option_ref)


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


async def _refresh_platform_token() -> None:
    """Load the stored platform Kite token into this worker. A failed read leaves whatever the worker held (the calculator then answers 503 if that is stale)."""
    try:
        from deps import db
        from services.kite_live_feed import platform_token
        await platform_token.refresh_cache(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("fno margin: the platform token could not be reloaded (%s)", type(e).__name__)


class MarginLeg(BaseModel):
    side: str = Field(..., pattern="^(buy|sell)$")
    option_type: str = Field(..., pattern="^(call|put|future)$")
    expiry: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    strike: Optional[float] = Field(None, gt=0)
    lots: int = Field(..., ge=1, le=1000)


class MarginRequest(BaseModel):
    underlying: str = Field(..., min_length=1, max_length=SYMBOL_MAX, pattern=SYMBOL_PATTERN)
    legs: List[MarginLeg] = Field(..., min_length=1, max_length=fno_margin.MAX_LEGS)


@router.post("/margin")
async def margin(request: Request, body: MarginRequest) -> Dict[str, Any]:
    """Funds needed and order charges for a basket, from Zerodha's margin calculator (a CALCULATION through the platform's Kite session; nothing is placed). 503 kite_session_unavailable
    when the platform is not logged in to Kite today; 404 naming the legs with no listed contract; 502 on a Kite error, never provider text."""
    await get_current_user(request)
    legs = [l.model_dump() for l in body.legs]
    # The backend runs several workers and only the feed's leader reloads the platform token from Mongo, so this worker's copy can be yesterday's: reload it before asking Kite.
    await _refresh_platform_token()
    try:
        calc = fno_margin.default_calculator()
        out = await asyncio.to_thread(fno_margin.run, calc, body.underlying.upper(), legs)
    except fno_margin.NoSession:
        raise HTTPException(status_code=503, detail="kite_session_unavailable")
    except fno_margin.CalcError as e:
        logger.warning("fno margin: the calculator failed (%s)", e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=f"No listed contract for: {', '.join(out['missing_contracts'])}")
    out.pop("ok", None)
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


POSITIONING_DAYS_BACK = 16          # weekdays looked back over to find N trading sessions (holidays are skipped, not filled)


def _today() -> date:
    return date.today()


def _recent_weekdays(today: date, n: int) -> List[date]:
    """The last `n` weekdays up to and including `today`, newest first."""
    out: List[date] = []
    d = today
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def _positioning_row(body: Dict[str, Any], sym: str) -> Optional[Dict[str, Any]]:
    """The symbol's row in one day's build-up scan: an index row first, then a stock row. Only what the scan says; a missing figure is null."""
    for key in ("indices", "rows"):
        for r in body.get(key) or []:
            if isinstance(r, dict) and str(r.get("symbol") or "").upper() == sym:
                return {"label": r.get("label") if r.get("label") in fno_rules.CATEGORIES else None,
                        "price_chg_pct": fno_engine.num(r.get("price_chg_pct")), "oi_chg_pct": fno_engine.num(r.get("oi_chg_pct")),
                        "cash_confirmation": r.get("cash_confirmation") if r.get("cash_confirmation") in ("confirms", "diverges") else None}
    return None


@router.get("/{symbol}/positioning-history")
async def positioning_history(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=SYMBOL_MAX, pattern=SYMBOL_PATTERN),
    sessions: int = Query(5, ge=2, le=10, description="How many recent trading sessions"),
) -> Dict[str, Any]:
    """The near-month futures' build-up state per trading session for the last `sessions` sessions, oldest first: the label, the price change % and the OI change %
    each day's scan gives (DaaS /desk/fno-buildup?date=D, the same rule as the Lab). A day is kept only when the scan answers for exactly that day: a holiday, a day the
    platform has not loaded or a failed read is skipped and counted in `missing`, never filled in. Every day failing is 502, not an empty history. Read only."""
    await get_current_user(request)
    sym = symbol.upper()
    days = _recent_weekdays(_today(), POSITIONING_DAYS_BACK)
    gate = asyncio.Semaphore(4)

    async def one(d: date) -> Optional[Dict[str, Any]]:
        async with gate:
            try:
                body = await _daas("/desk/fno-buildup", {"date": d.isoformat()}, "stock futures")
            except HTTPException:
                return None
        if _iso_day(body.get("as_of")) != d.isoformat():
            return None
        row = _positioning_row(body, sym)
        return {"date": d.isoformat(), **(row or {"label": None, "price_chg_pct": None, "oi_chg_pct": None, "cash_confirmation": None})}

    answers = await asyncio.gather(*(one(d) for d in days))
    got = [a for a in answers if a is not None]
    if not got:
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    kept = sorted(got, key=lambda r: r["date"], reverse=True)[:sessions]
    return {"symbol": sym, "sessions": sorted(kept, key=lambda r: r["date"]), "requested": sessions, "missing": len(days) - len(got),
            "source": "NSE F&O bhavcopy via the build-up scan, near-month future", "read_only": True}


@router.get("/{symbol}/iv-history")
async def iv_history_series(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=SYMBOL_MAX, pattern=SYMBOL_PATTERN),
    days: int = Query(fno_iv_history.DEFAULT_DAYS, ge=1, le=fno_iv_history.MAX_DAYS, description="Recorded sessions sent in `series`"),
    bucket: str = Query(fno_iv_history.BUCKETS[0], pattern="^(" + "|".join(fno_iv_history.BUCKETS) + ")$",
                        description="near_month (1st futures expiry after the session) | next_month (2nd)"),
) -> Dict[str, Any]:
    """The underlying's recorded daily ATM implied volatility, oldest first, the latest session as `current`, and
    IV rank and IV percentile over the latest 252 recorded sessions (null with a `reason` until 252 exist). Only
    what was recorded (scripts/record_iv_history.py): a session that was not recorded is absent, never estimated.
    The store failing to answer is 502, never an empty history. Read only."""
    await get_current_user(request)
    from deps import db
    sym = symbol.upper()
    try:
        docs = await fno_iv_history.read_rows(db, sym)
    except Exception as e:  # noqa: BLE001
        logger.warning("fno iv history: the records for %s could not be read (%s)", sym, type(e).__name__)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    return fno_iv_history.history_answer(sym, docs, bucket, days)


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
