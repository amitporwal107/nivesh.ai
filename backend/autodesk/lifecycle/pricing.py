"""Prices of closing fills (PHASE3_DESIGN §4.3), on autodesk-fill-v1's parameters. PURE: no I/O, no clock.

A closing fill is priced from the leg's OWN session row: its open, the level that traded inside the row, its close, or (a
resting objective) the objective itself when price traded through it. A market-type price moves against the order by the
half spread and the seeded slippage, on the tick, and is kept inside the row's low–high: a price that did not trade is never
used. A leg with no row, or no trade in the session, cannot be priced. Live closings use Phase 2's decide_quote unchanged.
"""
from __future__ import annotations

import random
from decimal import Decimal
from typing import Any, Optional

from .. import contracts as C
from ..execution import fill_model as fm

H = C.PriceHow
CLOSE_SIDE = {"LONG": "SELL", "SHORT": "BUY"}


def leg_view(leg: dict, qty: int, *, ref: Optional[Decimal] = None) -> fm.OrderView:
    """The closing order of `qty` units of a position leg, as the fill model sees it."""
    from ..market.session_bars import LegRef
    key = LegRef(kind=leg["kind"], underlying=leg["underlying"], expiry=leg.get("expiry"), strike=leg.get("strike")).key
    return fm.OrderView(key=key, kind=leg["kind"], side=CLOSE_SIDE[leg["side"]], order_type="MARKET", quantity=qty,
                        lot_size=leg["lot_size"], ref_price=ref or Decimal(str(leg["avg_price"])), leg_id=leg["leg_id"])


def rng_for(seed: int, session, key: str, reason: str, n: int, side: str) -> random.Random:
    """One stream per closing order, never shared with the opening order of the same instrument."""
    return fm.rng_for(seed, session, f"{key}|CLOSE|{reason}|{n}", side)


def price_row(view: fm.OrderView, bar: Any, how: C.PriceHow, *, level: Optional[Decimal], params: fm.FillParams,
              rng: random.Random) -> fm.Decision:
    """One leg's closing from its session row."""
    factor = Decimal(str(round(rng.uniform(*params.slippage_factor), 6)))
    latency = rng.randint(*params.latency_ms)
    if bar is None or not bar.traded or bar.low is None or bar.high is None:
        return fm.rest("CLOSE_BLOCKED_NO_DATA", "the leg did not trade in this session, so no real price can close it")
    low, high = bar.low, bar.high
    sell = view.side == "SELL"
    if how == H.OBJECTIVE:
        if level is None:
            return fm.rest("CLOSE_BLOCKED_NO_DATA", "no objective level to rest at")
        px = fm.to_tick(level, up=sell)          # a resting limit on the tick, never more aggressive than the level
        through = high > px if sell else low < px
        if not through:
            return fm.rest("LIMIT_NOT_REACHED", f"the row {low} to {high} did not trade through {px}")
        arrival, hs_total = px, Decimal("0")
    else:
        if how == H.OPEN:
            arrival = bar.open
        elif how == H.CLOSE:
            arrival = bar.close
        elif how == H.LEVEL:
            arrival = min(max(level, low), high) if level is not None else None
        else:
            raise ValueError(f"no row price for {how}")
        if arrival is None or arrival <= 0:
            return fm.rest("CLOSE_BLOCKED_NO_DATA", f"the row has no {how.value} price")
        px, _hs, _slip = fm._priced(view, arrival, params, factor)
        px = max(px, low) if sell else min(px, high)            # never outside what traded
        hs_total = fm.half_spread(view.kind, arrival, params)
    qty = fm.volume_cap(view, bar.traded_units, params)
    if qty <= 0:
        return fm.rest("VOLUME_CAP", f"{params.participation_pct}% of the session's {bar.traded_units} traded units is "
                                     f"below one lot of this order")
    adverse = (arrival - px) if sell else (px - arrival)
    adverse = max(adverse, Decimal("0"))
    spread = min(hs_total, adverse)
    return fm.Decision(action="FILL", qty=qty, price=px, arrival=arrival, spread_rs=spread * qty,
                       slippage_rs=(adverse - spread) * qty, latency_ms=latency,
                       source=f"{bar.source} {how.value} {arrival}")


def intrinsic(kind: str, strike: Decimal, underlying: Decimal) -> Decimal:
    if kind == "CE":
        return max(underlying - strike, Decimal("0"))
    if kind == "PE":
        return max(strike - underlying, Decimal("0"))
    raise ValueError(kind)
