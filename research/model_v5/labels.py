"""Trade-outcome labels for roadmap v2 Phases 2-3 (docs/ai_research/tpd3/model_v5/PREREGISTRATION_P2_P3.md §4, FROZEN
at 50fe02fd). Pure functions over the five sessions after the decision day D: s1 = D+1 ... s5. Arrays have shape
(n, 5), one row per (symbol, D), NaN where the stock has no bar on that calendar session. Entry = the open of s1.

Readings of the frozen text (recorded in RESULTS.md):
- A missing bar inside s2..s5 (suspension) is skipped; a trade still open expires at the close of the last bar it
  had within s1..s5.
- tbs: on s1 the open is the entry, so the open checks cannot fire there; the same code runs for every session.
- dir_5_5d: the frozen rule is applied literally: any bar reaching both +5% (high) and -5% (low) is AMBIGUOUS, even
  if its open had already gapped past one of them.
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

import numpy as np

POSITION_INR = Decimal("50000")
SESSIONS = 5
EPS = 1e-9          # relative: a price exactly at a level counts although entry * 1.10 is 110.00000000000001 in binary


def _up(x, level):
    return x >= level * (1 - EPS)


def _down(x, level):
    return x <= level * (1 + EPS)


def hit_high(entry: np.ndarray, H: np.ndarray, mult: float, k: int) -> np.ndarray:
    """1.0 if max high(s1..sk) >= entry * mult. Missing bars are ignored (they cannot touch anything)."""
    return _up(np.nanmax(H[:, :k], axis=1), entry * mult).astype(float)


def hit_low(entry: np.ndarray, L: np.ndarray, mult: float, k: int) -> np.ndarray:
    return _down(np.nanmin(L[:, :k], axis=1), entry * mult).astype(float)


def hit_close(entry: np.ndarray, C: np.ndarray, mult: float, k: int) -> np.ndarray:
    return _up(np.nanmax(C[:, :k], axis=1), entry * mult).astype(float)


def target_before_stop(entry, O, H, L, C, target_mult: float, stop_mult: float) -> dict:
    """§4 tbs rule. Per session, in order: open <= stop -> STOP at the open (gap-through); open >= target -> TARGET at
    the open; low <= stop -> STOP at the stop (this includes a bar that also reached the target: stop first);
    high >= target -> TARGET at the target. Still open after s5 -> EXPIRED at the last available close."""
    n = len(entry)
    tgt, stp = entry * target_mult, entry * stop_mult
    outcome = np.full(n, "", dtype=object)
    exit_px = np.full(n, np.nan)
    exit_k = np.full(n, -1, dtype=int)
    live = np.ones(n, dtype=bool)
    last_close = np.full(n, np.nan)
    last_k = np.full(n, -1, dtype=int)
    for k in range(O.shape[1]):
        o, h, lo, c = O[:, k], H[:, k], L[:, k], C[:, k]
        have = live & ~np.isnan(o)
        gap_stop = have & _down(o, stp)
        gap_tgt = have & ~gap_stop & _up(o, tgt)
        rest = have & ~gap_stop & ~gap_tgt
        stop = rest & _down(lo, stp)
        target = rest & ~stop & _up(h, tgt)
        for mask, name, price in ((gap_stop, "STOP", o), (gap_tgt, "TARGET", o), (stop, "STOP", stp), (target, "TARGET", tgt)):
            outcome[mask], exit_px[mask], exit_k[mask] = name, price[mask], k
        live &= ~(gap_stop | gap_tgt | stop | target)
        seen = live & ~np.isnan(c)
        last_close[seen], last_k[seen] = c[seen], k
    outcome[live], exit_px[live], exit_k[live] = "EXPIRED", last_close[live], last_k[live]
    return {"outcome": outcome, "exit_px": exit_px, "exit_k": exit_k}


def direction(entry, H, L, up_mult: float = 1.05, down_mult: float = 0.95) -> np.ndarray:
    """dir_5_5d: UP if +5% (high) is reached before -5% (low) within s1..s5, DOWN if -5% first, NONE if neither;
    a bar reaching both is AMBIGUOUS."""
    n = len(entry)
    out = np.full(n, "NONE", dtype=object)
    open_ = np.ones(n, dtype=bool)
    for k in range(H.shape[1]):
        h, lo = H[:, k], L[:, k]
        have = open_ & ~np.isnan(h)
        up, dn = have & _up(h, entry * up_mult), have & _down(lo, entry * down_mult)
        out[up & dn], out[up & ~dn], out[dn & ~up] = "AMBIGUOUS", "UP", "DOWN"
        open_ &= ~(up | dn)
    return out


def net_return(entry_px: float, exit_px: float, slip_pct: Decimal, cost_model, fill_costs, entry_date, exit_date) -> float:
    """Net return of one ₹50,000 delivery trade (§3): the fills carry `slip_pct` per side; Zerodha charges on both
    fills (the DP charge on the sale), applied retroactively. Quantity = floor(50,000 / entry fill), at least 1.
    Return = (sale - purchase - charges) / purchase."""
    e = Decimal(repr(float(entry_px))) * (1 + slip_pct / 100)
    x = Decimal(repr(float(exit_px))) * (1 - slip_pct / 100)
    qty = max(1, int((POSITION_INR / e).to_integral_value(rounding=ROUND_FLOOR)))
    buy, sell = e * qty, x * qty
    cb = fill_costs(cost_model, "delivery", "NSE", "BUY", buy, dp_applies=False, on_date=entry_date, allow_retroactive=True)
    cs = fill_costs(cost_model, "delivery", "NSE", "SELL", sell, dp_applies=True, on_date=exit_date, allow_retroactive=True)
    return float((sell - buy - cb["total"] - cs["total"]) / buy)
