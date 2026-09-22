"""PRD slippage models. Every function takes only values a real strategy would know AT THE SIGNAL
TIME (a price, a trailing ADV/ATR figure the caller already computed from bars strictly before the
signal, a static bps/pct parameter) and returns a per-share or percentage slippage amount. None of
them accept a bar, a list of bars, or anything shaped like OHLC data -- that is the point-in-time /
no-look-ahead guarantee the PRD asks for: it is enforced by the function *signatures* themselves
(there is nothing here a caller could pass "the next bar" into), and tests/test_no_lookahead.py
additionally asserts this via introspection so a future edit can't quietly add a bars-shaped
parameter.

All five PRD-named models plus one convenience primitive:
- fixed_pct            : slippage = price * pct / 100 (a flat percentage of price, PRD "fixed %").
- fixed_bps            : slippage = price * bps / 10000 (PRD "fixed bps").
- liquidity_bucket      : slippage = price * bucket_pct(adv) / 100, tiered by trailing average daily
                          traded value (the model already used by zerodha-equity-v1's slippage_pct()
                          -- ported here as one case of the general model, not a separate engine).
- volume_dependent      : slippage = price * (base_pct + liquidity_penalty_pct + volatility_penalty_pct) / 100,
                          the PRD's explicit "base + liquidity + volatility penalty" composite.
- atr_based             : slippage = n_atr * atr (i.e. N times ATR, expressed in price units directly
                          -- the PRD's "N x ATR/price" model; also exposed as a pct-of-price via
                          atr_based_pct for composing with the other models).
- fixed_amount          : slippage = amount_per_share (rupees), a direct/absolute convenience used
                          for reproducing a literal worked example (not itself a named PRD model).

Every model returns a Decimal RUPEE-PER-SHARE slippage amount except where noted; the direction
(does slippage move the fill against the trader) is the caller's job -- apply_slippage() below shows
the standard convention (BUY fills worse i.e. higher, SELL fills worse i.e. lower).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def fixed_pct(price: Decimal, pct: Decimal) -> Decimal:
    """PRD 'fixed %' model: slippage per share = price * pct / 100."""
    return _d(price) * _d(pct) / 100


def fixed_bps(price: Decimal, bps: Decimal) -> Decimal:
    """PRD 'fixed bps' model: slippage per share = price * bps / 10000."""
    return _d(price) * _d(bps) / 10000


def liquidity_bucket_pct(adv_inr: Decimal, buckets: tuple) -> Decimal:
    """Per-side slippage % for a stock with trailing average daily traded value `adv_inr`, using a
    (min_adv_inr, pct) bucket table sorted high to low -- the same shape as
    zerodha-equity-v1.json's slippage_per_side_pct.buckets, and the model execution.py has always
    consumed (it never looked forward; it took a single already-known figure and multiplied)."""
    v = _d(adv_inr) if adv_inr is not None else Decimal(0)
    ordered = sorted(((_d(floor), _d(pct)) for floor, pct in buckets), reverse=True)
    for floor, pct in ordered:
        if v >= floor:
            return pct
    return ordered[-1][1]


def liquidity_bucket(price: Decimal, adv_inr: Decimal, buckets: tuple) -> Decimal:
    """PRD 'liquidity buckets' model: slippage per share = price * liquidity_bucket_pct(adv) / 100."""
    return _d(price) * liquidity_bucket_pct(adv_inr, buckets) / 100


def volume_dependent(price: Decimal, base_pct: Decimal, liquidity_penalty_pct: Decimal,
                      volatility_penalty_pct: Decimal) -> Decimal:
    """PRD 'volume-dependent' model: base + liquidity penalty + volatility penalty, all supplied by
    the caller as already-known percentages (e.g. liquidity_penalty derived from a trailing
    position/ADV ratio via liquidity.py, volatility_penalty from a trailing ATR/price ratio) -- this
    function does no lookback itself, it only sums percentages it is handed."""
    total_pct = _d(base_pct) + _d(liquidity_penalty_pct) + _d(volatility_penalty_pct)
    return _d(price) * total_pct / 100


def atr_based(atr: Decimal, n_atr: Decimal) -> Decimal:
    """PRD 'ATR-based N x ATR/price' model: slippage per share = n_atr * atr. `atr` must be an ATR
    value already computed by the caller from bars strictly before the signal date -- this function
    accepts only the scalar, never bars, so it cannot look ahead by construction."""
    return _d(n_atr) * _d(atr)


def atr_based_pct(atr: Decimal, price: Decimal, n_atr: Decimal) -> Decimal:
    """atr_based() expressed as a percentage of price, for composing with the other pct-based
    models (e.g. as the volatility_penalty_pct input to volume_dependent())."""
    price = _d(price)
    if price == 0:
        return Decimal(0)
    return atr_based(atr, n_atr) / price * 100


def fixed_amount(amount_per_share: Decimal) -> Decimal:
    """Direct rupee-per-share slippage, supplied as-is (used e.g. to reproduce a worked example
    that states "Rs 3/share slippage" without going through a %/bps model first)."""
    return _d(amount_per_share)


def apply_slippage(price: Decimal, side: str, slippage_per_share: Decimal) -> Decimal:
    """The standard sign convention: a BUY fills at a worse (higher) price, a SELL fills at a worse
    (lower) price. `slippage_per_share` must already be non-negative (a magnitude); this function
    applies the direction, it does not compute the magnitude."""
    price, slip = _d(price), _d(slippage_per_share)
    if slip < 0:
        raise ValueError(f"slippage_per_share must be a non-negative magnitude, got {slip!r}")
    if side == "BUY":
        return price + slip
    if side == "SELL":
        return price - slip
    raise ValueError(f"side must be BUY or SELL, got {side!r}")
