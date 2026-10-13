"""Black-76 price, implied volatility and Greeks for a European option on a forward. Pure functions: no
network, no database, standard library only.

NSE index and stock options are European (exercised only at expiry), so each is priced as an option on the
forward for its own expiry date:

    d1 = [ln(F/K) + σ²T/2] / (σ√T)          d2 = d1 − σ√T          DF = e^(−rT)
    call = DF·[F·N(d1) − K·N(d2)]           put = DF·[K·N(−d2) − F·N(−d1)]
    put-call parity:  call − put = DF·(F − K)

    F  forward for the expiry     K  strike     σ  volatility, a year (0.14 = 14%)
    T  time to expiry in years    r  RISK_FREE_RATE, continuously compounded

The forward (`choose_forward`), in order:
    "future"           the settlement price of the future that expires on the same day as the option: the
                       market's own forward, with dividends and funding already in it. Nothing is carried.
    "put-call parity"  no future expires that day (weekly index expiries, far months): the forward the options
                       themselves imply. Parity gives  F = K + (C − P)·e^(rT)  at any strike; it is read at the
                       strike K* where the call and the put are closest in price (|C − P| smallest, the strike
                       nearest the forward, where both sides are most traded and least stale; a tie goes to the
                       lower strike). Only a strike whose call AND put both traded that day is used
                       (`parity_forward`; the caller passes those pairs).
    "carried spot"     the last resort, when no strike has such a pair: spot × e^(rT). This ignores dividends,
                       and it assumes the day's spot and option prices were struck at the same moment. When they
                       were not, calls and puts at one strike imply different volatilities
                       (tests/test_option_pricing.py :: test_a_wrong_forward_splits_the_two_sides_apart). On the
                       NIFTY weekly chain of 13 Oct 2026 the carried spot sat 60 points under the parity forward
                       and split the at-the-money call and put by five volatility points.

Time to expiry (`days_between`, `year_fraction`): calendar days from the data's day to the expiry day ÷ 365.
The data is an end-of-day snapshot and the option expires at the close of its expiry day, so whole days are
exact; a contract whose expiry is the data's day has no time left.

Implied volatility (`implied_vol`) is the σ that reproduces a price, found by bisection between MIN_VOL and
MAX_VOL (the price rises with σ, so the root is unique). It is None, never a stand-in number, when:
    · the option expires on the data's day, or has expired (T ≤ 0)
    · the price is zero, negative or not a number
    · the price is at or below the discounted intrinsic value DF·max(F − K, 0) (put: DF·max(K − F, 0)):
      no volatility prices it
    · the price is at or above the most the option can be worth (call: DF·F, put: DF·K)
    · the σ that fits lies outside [MIN_VOL, MAX_VOL]
    · the forward or the strike is missing, zero or negative

Greeks, per one unit of the underlying (multiply by lot size × lots for a position):
    delta   ∂price/∂F          call DF·N(d1), put −DF·N(−d1): price change per one-point move in the forward
    gamma   ∂²price/∂F²        DF·φ(d1) / (F·σ√T): change in delta per one-point move in the forward
    vega    ∂price/∂σ ÷ 100    DF·F·φ(d1)·√T / 100: price change per one volatility point (14% → 15%)
    theta   −∂price/∂T ÷ 365   [r·price − DF·F·φ(d1)·σ/(2√T)] / 365: price change over one calendar day with
                               the forward and the volatility unchanged
Each is None when T ≤ 0 or σ ≤ 0 (the formulas divide by σ√T).
"""
from __future__ import annotations

import math
from datetime import date
from typing import Iterable, NamedTuple, Optional, Tuple

# Annual interest rate, continuously compounded: discounts every option price and carries the spot when no
# future expires with the option.
# Where 5.75% comes from: it is the rate the exchange's own theoretical settlement prices imply. NSE settles a
# deep in-the-money call that did not trade at S − K·e^(−rT); in the staging F&O bhavcopy of 13 Oct 2026 that
# gives r = 5.75% at the 6-day and at the 14-day NIFTY expiry (worked in tests/test_option_pricing.py ::
# test_the_rate_constant_is_the_one_the_exchanges_own_settlement_prices_imply). It is a constant, so it goes
# stale when money-market rates move; the data platform's nidp.rbi_yields (91-day T-bill) is the feed to wire in
# if this is to follow the market. Over 14 days a full percentage point of error moves a carried forward by 0.04%.
RISK_FREE_RATE = 0.0575

DAYS_PER_YEAR = 365

# Bounds of the implied-volatility search: 0.01% and 500% a year.
MIN_VOL = 0.0001
MAX_VOL = 5.0
_VOL_TOLERANCE = 1e-10
_MAX_BISECTIONS = 100

FORWARD_FROM_FUTURE = "future"
FORWARD_FROM_PARITY = "put-call parity"
FORWARD_FROM_SPOT = "carried spot"

_CALL, _PUT = "CE", "PE"
_SQRT_2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)


class Greeks(NamedTuple):
    delta: float
    gamma: float
    theta: float  # per calendar day
    vega: float   # per one volatility point


# ── the normal distribution ──────────────────────────────────────────────────

def norm_cdf(x: float) -> float:
    """N(x), the standard normal distribution function. erfc keeps the lower tail accurate."""
    return 0.5 * math.erfc(-x / _SQRT_2)


def norm_pdf(x: float) -> float:
    """φ(x), the standard normal density."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


# ── inputs ───────────────────────────────────────────────────────────────────

def _is_call(kind: str) -> bool:
    if kind == _CALL:
        return True
    if kind == _PUT:
        return False
    raise ValueError(f"option type must be CE or PE, not {kind!r}")


def _positive(x: Optional[float]) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def days_between(as_of: date, expiry: date) -> int:
    """Calendar days from the data's day to the expiry day. 0 = expires at that day's close; negative = expired."""
    return (expiry - as_of).days


def year_fraction(days: int) -> float:
    """Calendar days as a fraction of a 365-day year."""
    return days / DAYS_PER_YEAR


def parity_forward(pairs: Optional[Iterable[Tuple[float, float, float]]], t: float,
                   rate: float = RISK_FREE_RATE) -> Optional[float]:
    """The forward implied by put-call parity: F = K* + (C − P)·e^(rT) at the strike K* where |C − P| is
    smallest (a tie goes to the lower strike). `pairs` are (strike, call price, put price) for the strikes the
    caller accepts: both contracts must have traded that day, or the prices are not a market's view of the
    forward. None when there is no usable pair or no time left."""
    if not math.isfinite(t) or t <= 0:
        return None
    usable = [(abs(c - p), k, c, p) for k, c, p in pairs or [] if _positive(k) and _positive(c) and _positive(p)]
    if not usable:
        return None
    _, strike, call, put = min(usable)
    forward = strike + (call - put) * math.exp(rate * t)
    return forward if _positive(forward) else None


def choose_forward(future_settle: Optional[float], spot: Optional[float], t: float, rate: float = RISK_FREE_RATE,
                   pairs: Optional[Iterable[Tuple[float, float, float]]] = None) -> Optional[Tuple[float, str]]:
    """(forward, how it was found), by the first of three rules that applies:
        "future"           `future_settle`, the settlement price of the future expiring on the option's own
                           expiry day (None when no future does)
        "put-call parity"  the forward `pairs` imply (see `parity_forward`)
        "carried spot"     spot × e^(rT)
    None when none of the three can be worked out."""
    if _positive(future_settle):
        return float(future_settle), FORWARD_FROM_FUTURE
    implied = parity_forward(pairs, t, rate)
    if implied is not None:
        return implied, FORWARD_FROM_PARITY
    if _positive(spot) and math.isfinite(t):
        return float(spot) * math.exp(rate * max(t, 0.0)), FORWARD_FROM_SPOT
    return None


# ── price ────────────────────────────────────────────────────────────────────

def _d1_d2(forward: float, strike: float, t: float, vol: float) -> Tuple[float, float]:
    spread = vol * math.sqrt(t)
    d1 = (math.log(forward / strike) + 0.5 * vol * vol * t) / spread
    return d1, d1 - spread


def _check(forward: float, strike: float) -> None:
    if not _positive(forward) or not _positive(strike):
        raise ValueError("forward and strike must be positive numbers")


def intrinsic(kind: str, forward: float, strike: float, t: float, rate: float = RISK_FREE_RATE) -> float:
    """The discounted intrinsic value, DF·max(F − K, 0) for a call: the least the option can be worth."""
    call = _is_call(kind)
    _check(forward, strike)
    df = math.exp(-rate * max(t, 0.0))
    return df * max(forward - strike if call else strike - forward, 0.0)


def price(kind: str, forward: float, strike: float, t: float, vol: float, rate: float = RISK_FREE_RATE) -> float:
    """Black-76 price per unit. With no time or no volatility left it is the discounted intrinsic value."""
    call = _is_call(kind)
    _check(forward, strike)
    if t <= 0 or vol <= 0:
        return intrinsic(kind, forward, strike, t, rate)
    d1, d2 = _d1_d2(forward, strike, t, vol)
    df = math.exp(-rate * t)
    if call:
        return df * (forward * norm_cdf(d1) - strike * norm_cdf(d2))
    return df * (strike * norm_cdf(-d2) - forward * norm_cdf(-d1))


# ── implied volatility ───────────────────────────────────────────────────────

def implied_vol(kind: str, option_price: Optional[float], forward: Optional[float], strike: Optional[float],
                t: float, rate: float = RISK_FREE_RATE) -> Optional[float]:
    """The volatility (a year, 0.14 = 14%) at which `price` gives `option_price`, or None when there is no
    such volatility inside [MIN_VOL, MAX_VOL]. The None cases are listed in the module docstring."""
    call = _is_call(kind)
    if not (_positive(option_price) and _positive(forward) and _positive(strike)):
        return None
    if not math.isfinite(t) or t <= 0:
        return None
    df = math.exp(-rate * t)
    floor = df * max(forward - strike if call else strike - forward, 0.0)
    cap = df * (forward if call else strike)
    if option_price <= floor or option_price >= cap:
        return None
    lo, hi = MIN_VOL, MAX_VOL
    # The price rises with volatility, so the target must lie between the prices at the two bounds.
    if price(kind, forward, strike, t, lo, rate) > option_price or price(kind, forward, strike, t, hi, rate) < option_price:
        return None
    for _ in range(_MAX_BISECTIONS):
        mid = 0.5 * (lo + hi)
        if price(kind, forward, strike, t, mid, rate) < option_price:
            lo = mid
        else:
            hi = mid
        if hi - lo < _VOL_TOLERANCE:
            break
    return 0.5 * (lo + hi)


# ── Greeks ───────────────────────────────────────────────────────────────────

def greeks(kind: str, forward: Optional[float], strike: Optional[float], t: float, vol: Optional[float],
           rate: float = RISK_FREE_RATE) -> Optional[Greeks]:
    """Delta, gamma, theta per calendar day and vega per volatility point, per unit of the underlying.
    None when they are not defined: no time left, no volatility, or a missing forward or strike."""
    call = _is_call(kind)
    if not (_positive(forward) and _positive(strike) and _positive(vol)) or not math.isfinite(t) or t <= 0:
        return None
    root_t = math.sqrt(t)
    d1, d2 = _d1_d2(forward, strike, t, vol)
    df = math.exp(-rate * t)
    density = norm_pdf(d1)
    if call:
        value = df * (forward * norm_cdf(d1) - strike * norm_cdf(d2))
        delta_ = df * norm_cdf(d1)
    else:
        value = df * (strike * norm_cdf(-d2) - forward * norm_cdf(-d1))
        delta_ = -df * norm_cdf(-d1)
    decay = df * forward * density * vol / (2.0 * root_t)
    return Greeks(
        delta=delta_,
        gamma=df * density / (forward * vol * root_t),
        theta=(rate * value - decay) / DAYS_PER_YEAR,
        vega=df * forward * density * root_t / 100.0,
    )


def delta(kind: str, forward: float, strike: float, t: float, vol: float, rate: float = RISK_FREE_RATE) -> Optional[float]:
    """Price change per one-point move in the forward."""
    g = greeks(kind, forward, strike, t, vol, rate)
    return None if g is None else g.delta


def gamma(forward: float, strike: float, t: float, vol: float, rate: float = RISK_FREE_RATE) -> Optional[float]:
    """Change in delta per one-point move in the forward. The same for a call and a put."""
    g = greeks(_CALL, forward, strike, t, vol, rate)
    return None if g is None else g.gamma


def theta_per_day(kind: str, forward: float, strike: float, t: float, vol: float, rate: float = RISK_FREE_RATE) -> Optional[float]:
    """Price change over one calendar day, forward and volatility unchanged. Usually negative."""
    g = greeks(kind, forward, strike, t, vol, rate)
    return None if g is None else g.theta


def vega_per_point(forward: float, strike: float, t: float, vol: float, rate: float = RISK_FREE_RATE) -> Optional[float]:
    """Price change per one volatility point (0.01). The same for a call and a put."""
    g = greeks(_CALL, forward, strike, t, vol, rate)
    return None if g is None else g.vega
