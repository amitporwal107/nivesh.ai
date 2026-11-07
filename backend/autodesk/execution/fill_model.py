"""The paper fill model `autodesk-fill-v1` (PRD §11.5, ARCH §10.6, PHASE2_DESIGN §6). PURE: no I/O, no clock, no database.

decide_open   a session's OPEN from its daily row. Sees only the open, the previous close, the lot and the traded quantity.
decide_close  a resting limit at the CLOSE, when the whole bar has happened. Fills only if price traded THROUGH the limit.
decide_quote  the live desk: one live quote (already checked for freshness by market/live_quotes.check_quote).
basket_*      several legs: all or none, inside a net limit.

Randomness comes only from a `random.Random` the caller seeds per order (see rng_for), so a simulation is reproducible.
Prices are Decimal; a filled price is on the tick, rounded against the order. Reasons are narrative: AD-92 words stay out.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, Decimal
from typing import Optional

from ..market.live_quotes import LiveQuote

VERSION = "autodesk-fill-v1"
TICK = Decimal("0.05")
BPS = Decimal("10000")
PCT = Decimal("100")
ALL_OR_NONE = "the legs of a several-leg plan fill together or not at all in Phase 2"


@dataclass(frozen=True)
class FillParams:
    """Assumptions, recorded with every simulation's results. They are proxies: end-of-day rows have no bid or ask."""
    half_spread_pct: dict = field(default_factory=lambda: {"EQ": Decimal("0.05"), "FUT": Decimal("0.02"),
                                                           "CE": Decimal("0.50"), "PE": Decimal("0.50")})
    slippage_bps: dict = field(default_factory=lambda: {"EQ": Decimal("3"), "FUT": Decimal("2"), "CE": Decimal("20"),
                                                        "PE": Decimal("20")})
    slippage_factor: tuple = (0.5, 1.5)        # seeded in a simulation; 1 on the live desk
    participation_pct: Decimal = Decimal("10")  # at most this share of the session's traded quantity
    latency_ms: tuple = (50, 400)              # on the simulated clock
    price_band_pct: Decimal = Decimal("20")    # proxy for the exchange's band: there is no band file (not applied to options)
    reference_move_pct: Decimal = Decimal("10")  # shares, futures: a gap or a corporate action the plan does not know
    market_collar_pct: dict = field(default_factory=lambda: {"EQ": Decimal("3"), "FUT": Decimal("3"), "CE": Decimal("15"),
                                                             "PE": Decimal("15")})
    option_limit_pct: Decimal = Decimal("15")  # one option's limit from its plan premium
    basket_net_pct: Decimal = Decimal("15")    # a basket's net limit from its plan net
    no_depth_share: Decimal = Decimal("0.25")  # live desk: share of the order per tick when no quantity is displayed

    def describe(self) -> dict:
        d = asdict(self)
        return {"version": VERSION, "tick": str(TICK), **{k: _plain(v) for k, v in d.items()}}


def _plain(v):
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return str(v) if isinstance(v, Decimal) else v


DEFAULT_PARAMS = FillParams()


def rng_for(seed: int, session: date, key: str, side: str) -> random.Random:
    """One stream per order, from stable facts only: not the order's id, not the order of processing."""
    return random.Random(f"{seed}|{session.isoformat()}|{key}|{side}")


def to_tick(px: Decimal, *, up: bool) -> Decimal:
    n = (px / TICK).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)
    return max(n * TICK, TICK)


def on_tick(px: Decimal) -> bool:
    return (px / TICK) == (px / TICK).to_integral_value()


@dataclass(frozen=True)
class OrderView:
    key: str
    kind: str                         # EQ | FUT | CE | PE
    side: str                         # BUY | SELL
    order_type: str                   # MARKET | LIMIT | BASKET_LEG
    quantity: int
    lot_size: int
    ref_price: Decimal
    filled_qty: int = 0
    limit_price: Optional[Decimal] = None
    invalidation: Optional[Decimal] = None   # a long single leg's invalidation level
    leg_id: str = "L1"

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled_qty


@dataclass(frozen=True)
class OpenPrint:
    """All the OPEN decision may see. High, low and close are deliberately absent (AD-P2-49)."""
    exists: bool
    open: Optional[Decimal] = None
    prev_close: Optional[Decimal] = None
    traded: bool = False
    traded_units: int = 0
    lot_size: Optional[int] = None
    source: str = ""


@dataclass(frozen=True)
class CloseRange:
    low: Optional[Decimal]
    high: Optional[Decimal]
    traded: bool
    traded_units: int
    source: str = ""


@dataclass(frozen=True)
class Decision:
    action: str                         # FILL | REST | REJECT
    qty: int = 0
    price: Optional[Decimal] = None
    arrival: Optional[Decimal] = None
    spread_rs: Decimal = Decimal("0")
    slippage_rs: Decimal = Decimal("0")
    latency_ms: int = 0
    code: Optional[str] = None
    reason: str = ""
    source: str = ""


def rest(code: str, reason: str) -> Decision:
    return Decision(action="REST", code=code, reason=reason)


def reject(code: str, reason: str) -> Decision:
    return Decision(action="REJECT", code=code, reason=reason)


def half_spread(kind: str, price: Decimal, params: FillParams) -> Decimal:
    hs = price * params.half_spread_pct[kind] / PCT
    return max(hs, TICK) if kind in ("CE", "PE") else hs


def volume_cap(order: OrderView, traded_units: int, params: FillParams) -> int:
    """What this order may still fill under the session's volume share, in whole lots."""
    cap = int(Decimal(traded_units) * params.participation_pct / PCT)
    lots_cap = (cap // order.lot_size) * order.lot_size
    return max(0, min(order.remaining, lots_cap - order.filled_qty))


def _guards(order: OrderView, px: Decimal, *, prev_close: Optional[Decimal], params: FillParams) -> Optional[tuple[str, str]]:
    """Price checks that do not depend on the side's spread. Returns (code, reason) or None."""
    if order.kind in ("EQ", "FUT"):
        if prev_close and abs(px / prev_close - 1) * PCT > params.price_band_pct:
            return "PRICE_BAND", (f"{px} is outside the ±{params.price_band_pct}% band around the previous close "
                                  f"{prev_close}")
        if order.order_type != "BASKET_LEG" and abs(px / order.ref_price - 1) * PCT > params.reference_move_pct:
            return "REFERENCE_MOVED", (f"{px} is more than {params.reference_move_pct}% from the plan's price "
                                       f"{order.ref_price}: a large gap or a corporate action the plan does not know")
        if order.invalidation is not None and order.side == "BUY" and px <= order.invalidation:
            return "THROUGH_INVALIDATION", f"{px} is at or through the plan's invalidation level {order.invalidation}"
    return None


def _priced(order: OrderView, arrival: Decimal, params: FillParams, factor: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """(filled price on the tick, half spread, slippage per unit including the rounding)."""
    hs = half_spread(order.kind, arrival, params)
    slip = arrival * params.slippage_bps[order.kind] * factor / BPS
    if order.side == "BUY":
        px = to_tick(arrival + hs + slip, up=True)
        return px, hs, px - arrival - hs
    px = to_tick(arrival - hs - slip, up=False)
    return px, hs, arrival - hs - px


def _market_collar_breached(order: OrderView, px: Decimal, params: FillParams) -> bool:
    return order.order_type == "MARKET" and abs(px / order.ref_price - 1) * PCT > params.market_collar_pct[order.kind]


def _limit_blocks(order: OrderView, px: Decimal) -> bool:
    if order.order_type != "LIMIT":
        return False
    return px > order.limit_price if order.side == "BUY" else px < order.limit_price


def decide_open(order: OrderView, p: OpenPrint, params: FillParams, rng: random.Random) -> Decision:
    """The order at the session's open (table in PHASE2_DESIGN §6.1)."""
    factor = Decimal(str(round(rng.uniform(*params.slippage_factor), 6)))
    latency = rng.randint(*params.latency_ms)
    if not p.exists:
        return rest("NO_BAR", "the exchange has no row for this instrument in this session")
    if not p.traded or p.open is None or p.open <= 0:
        if order.kind == "EQ":
            return rest("NOT_TRADED", "the share did not trade in this session")
        return reject("UNTRADED_CONTRACT", "the contract did not trade in this session, so its row carries an old price")
    if p.lot_size and order.lot_size != p.lot_size:
        return reject("LOT_SIZE", f"the plan's lot {order.lot_size} is not the exchange's lot {p.lot_size} in this session")
    g = _guards(order, p.open, prev_close=p.prev_close, params=params)
    if g:
        return reject(*g)
    px, hs, slip = _priced(order, p.open, params, factor)
    if _market_collar_breached(order, px, params):
        return reject("COLLAR", f"{px} is outside the ±{params.market_collar_pct[order.kind]}% collar around the plan's "
                                f"price {order.ref_price}")
    if _limit_blocks(order, px):
        return rest("LIMIT_NOT_REACHED", f"{px} at the open is past the limit {order.limit_price}")
    qty = volume_cap(order, p.traded_units, params)
    if qty <= 0:
        return rest("VOLUME_CAP", f"{params.participation_pct}% of the session's {p.traded_units} traded units is below "
                                  f"one lot of this order")
    return Decision(action="FILL", qty=qty, price=px, arrival=p.open, spread_rs=hs * qty, slippage_rs=slip * qty,
                    latency_ms=latency, source=f"{p.source} open {p.open}")


def decide_close(order: OrderView, r: CloseRange, params: FillParams) -> Decision:
    """A resting limit at the close. A touch is not a fill: price must trade through. Passive: no spread, no slippage."""
    if order.order_type != "LIMIT" or order.filled_qty > 0:
        return rest("SESSION_ENDED", "the session ended with this quantity unfilled")
    if not r.traded or r.low is None or r.high is None:
        return rest("SESSION_ENDED", "no trade in this session")
    lim = order.limit_price
    through = r.low < lim if order.side == "BUY" else r.high > lim
    if not through:
        return rest("LIMIT_NOT_REACHED", f"the session's range {r.low} to {r.high} did not trade through the limit {lim}")
    qty = volume_cap(order, r.traded_units, params)
    if qty <= 0:
        return rest("VOLUME_CAP", f"{params.participation_pct}% of the session's {r.traded_units} traded units is below "
                                  f"one lot of this order")
    return Decision(action="FILL", qty=qty, price=lim, arrival=lim, source=f"{r.source} traded through the limit")


# ── several legs ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _signed_value(order: OrderView, d: Decision) -> Decimal:
    v = d.price * d.qty
    return v if order.side == "BUY" else -v


def basket_finish(pairs: list[tuple[OrderView, Decision]], net_limit_rs: Optional[Decimal]) -> tuple[Optional[Decision], Decimal]:
    """All legs decided: (None, net) when they all fill in full inside the net limit, else (the reject, net so far)."""
    net = Decimal("0")
    for o, d in pairs:
        if d.action == "REJECT":
            return reject(d.code or "REJECTED", f"leg {o.leg_id}: {d.reason}; {ALL_OR_NONE}"), net
        if d.action != "FILL" or d.qty < o.remaining:
            code = "UNTRADED_CONTRACT" if d.code in ("NO_BAR", "NOT_TRADED") else "BASKET_VOLUME_CAP"
            why = d.reason or f"only {d.qty} of {o.remaining} could fill"
            return reject(code, f"leg {o.leg_id}: {why}; {ALL_OR_NONE}"), net
        net += _signed_value(o, d)
    if net_limit_rs is not None and net > net_limit_rs:
        return reject("BASKET_NET_LIMIT", f"net value {net} is past the net limit {net_limit_rs}; {ALL_OR_NONE}"), net
    return None, net


# ── live quote ────────────────────────────────────────────────────────────────────────────────────────────────────────

def decide_quote(order: OrderView, q: LiveQuote, params: FillParams, *, whole: bool = False,
                 last_quote_ref: Optional[str] = None) -> Decision:
    """One fresh live quote (market/live_quotes.check_quote passed it). `whole`: a basket leg, which never fills in part.
    Anything that prevents a fill now is REST: the order retries on the next tick and never fills at an old price."""
    if last_quote_ref is not None and last_quote_ref == q.ref:
        return rest("QUOTE_ALREADY_USED", "this quote's displayed quantity was already used by this order")
    if q.lot_size and order.kind != "EQ" and q.lot_size != order.lot_size:
        return reject("LOT_SIZE", f"the plan's lot {order.lot_size} is not the exchange's lot {q.lot_size}")
    buy = order.side == "BUY"
    top = q.ask if buy else q.bid
    hs = half_spread(order.kind, q.ltp, params)
    book = top if top is not None else (q.ltp + hs if buy else q.ltp - hs)
    g = _guards(order, q.ltp, prev_close=None, params=params)
    if g:
        return rest(*g)
    slip = book * params.slippage_bps[order.kind] / BPS
    px = to_tick(book + slip, up=True) if buy else to_tick(book - slip, up=False)
    if _market_collar_breached(order, px, params):
        return rest("COLLAR", f"{px} is outside the ±{params.market_collar_pct[order.kind]}% collar around the plan's "
                              f"price {order.ref_price}")
    if _limit_blocks(order, px):
        lim = order.limit_price
        if (buy and book <= lim) or (not buy and book >= lim):
            px = lim                  # the book is inside the limit; slippage cannot take it past
        else:
            return rest("LIMIT_NOT_REACHED", f"the quote {book} is past the limit {lim}")
    displayed = q.ask_qty if buy else q.bid_qty
    if displayed:
        qty = min(order.remaining, (displayed // order.lot_size) * order.lot_size)
    else:
        share = int(Decimal(order.quantity) * params.no_depth_share)
        qty = min(order.remaining, max((share // order.lot_size) * order.lot_size, order.lot_size))
        if whole:
            qty = order.remaining
    if qty <= 0:
        return rest("NO_DISPLAYED_QUANTITY", f"the {displayed} displayed is below one lot of this order")
    if whole and qty < order.remaining:
        return rest("BASKET_VOLUME_CAP", f"only {qty} of {order.remaining} is displayed")
    mid = (q.bid + q.ask) / 2 if q.bid is not None and q.ask is not None else q.ltp
    spread = abs(book - mid) * qty
    slippage = abs(px - book) * qty
    label = "top of book" if top is not None else "ltp_spread"
    return Decision(action="FILL", qty=qty, price=px, arrival=mid.quantize(Decimal("0.0001"), rounding=ROUND_DOWN),
                    spread_rs=spread, slippage_rs=slippage, source=f"live quote {q.ref} ({label})")
