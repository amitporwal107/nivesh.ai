"""The desk's cost card `desk-cost-v2`: what a paper trade is charged, side by side, by segment.

    one order side = brokerage + STT + exchange transaction charge + SEBI fee + stamp duty + GST + slippage

Three of those are DESK ASSUMPTIONS, not anybody's tariff, and say so on every trade that snapshots this card:
  * brokerage   ₹20 per order side for every segment: the figure the desk has always charged (desk-flat-v1). It is not a
                broker's published tariff (Zerodha, for one, charges ₹0 for equity delivery and ₹20 or 0.03% for F&O).
                Which broker's card the desk should follow is an owner decision.
  * slippage    0.05% of the traded value per side. It is also the SPREAD allowance: the desk trades on end-of-day
                bars, which carry no bid or ask, so the spread cannot be measured and is not charged separately.
  * GST         18% of (brokerage + exchange charge + SEBI fee), the base the broker card in the repo uses.
The statutory rates are below, each with its source and the date it took effect. The equity rates are the ones the
repo already holds (research/costs/rules/zerodha-equity-v1.json and nse-equity-statutory-v1.json; copied here as
constants, nothing is imported from research/). The REPO HAD NO F&O RATES (services/fno_margin.py reads Kite's computed
charges and holds none; services/fno_backtest/outcomes.py has only an aggregate "about 0.03%"), so the futures and
options rates are the ones published on https://zerodha.com/charges/ when retrieved on 2026-10-27; that page states no
effective date for them, so their effective date is UNVERIFIED and recorded as such.

Not charged: DP (depository) charges on a delivery sale (₹15.34 per scrip per sell day at Zerodha: a depository and
broker fee, not statutory, and broker-specific); STT on exercise beyond the convention below; IPFT and clearing charges;
income tax on gains. An option held to expiry is priced as SOLD at its settlement value (intrinsic): the exercise STT on
a long in-the-money option (0.15% of the intrinsic value) has the same rate and base. A leg that expires worthless is
still charged its exit side's brokerage and GST (conservative, the desk's convention since desk-flat-v1).

Rounding: each component of one order side is rounded to the paisa (half up), GST on the rounded brokerage, exchange
charge and SEBI fee, and the side's total is the sum of its rounded components, as a contract note adds them up.
Nothing here places an order or talks to a broker.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, Optional

VERSION = "desk-cost-v2"

#: Desk assumptions (see the docstring): not a broker's tariff, not statutory.
BROKERAGE_RS_PER_SIDE = 20.0
SLIPPAGE_PCT_PER_SIDE = 0.05


@dataclass(frozen=True)
class Rate:
    value: float
    unit: str
    source: str
    effective_from: Optional[str]
    note: str = ""


_EQ_CARD = "research/costs/rules/zerodha-equity-v1.json (Zerodha's published schedule, retrieved 2026-09-19), delivery profile"
_EQ_STAT = "research/costs/rules/nse-equity-statutory-v1.json"
_ZERODHA_PAGE = "https://zerodha.com/charges/ (retrieved 2026-10-27; not in the repo before this card)"
_NO_DATE = None          # the source states no effective date

#: Statutory charges by segment. Percentages are of the traded value of that order side (for options, the premium).
STATUTORY: Dict[str, Dict[str, Rate]] = {
    "equity_delivery": {
        "stt_buy_pct": Rate(0.1, "% of the buy value", f"{_EQ_CARD}; {_EQ_STAT} (stt, delivery, BUY)", "2021-01-01",
                            "In force since 2013 per the statutory file; the 2023 and 2024 STT changes applied to F&O only."),
        "stt_sell_pct": Rate(0.1, "% of the sell value", f"{_EQ_CARD}; {_EQ_STAT} (stt, delivery, SELL)", "2021-01-01"),
        "exchange_pct": Rate(0.00307, "% of the traded value, each side", f"{_EQ_CARD} txn_pct NSE; {_EQ_STAT}", "2026-03-01",
                             "NSE cash. The statutory file marks the 2026-03-01 start date UNVERIFIED (rate verified on "
                             "zerodha.com/charges 2026-09-19, and again 2026-10-27)."),
        "sebi_per_crore_rs": Rate(10.0, "₹ per crore of traded value, each side", f"{_EQ_CARD}; {_EQ_STAT} (sebi_fee)", "2021-04-01"),
        "stamp_buy_pct": Rate(0.015, "% of the buy value", f"{_EQ_CARD}; {_EQ_STAT} (stamp_duty, delivery)", "2020-07-01",
                              "Indian Stamp Act as amended by the Finance Act 2019, uniform from 1 Jul 2020."),
        "gst_pct": Rate(18.0, "% of brokerage + exchange charge + SEBI fee", f"{_EQ_CARD}; {_EQ_STAT} (gst)", "2017-07-01"),
    },
    "futures": {
        "stt_sell_pct": Rate(0.05, "% of the sell value", _ZERODHA_PAGE, _NO_DATE, "Page text: \"0.05% on the sell side\"."),
        "exchange_pct": Rate(0.00183, "% of the traded value, each side", _ZERODHA_PAGE, _NO_DATE, "Page text: \"NSE: 0.00183%\"."),
        "sebi_per_crore_rs": Rate(10.0, "₹ per crore of traded value, each side", _ZERODHA_PAGE, _NO_DATE, "Page text: \"₹10 / crore\"."),
        "stamp_buy_pct": Rate(0.002, "% of the buy value", _ZERODHA_PAGE, _NO_DATE, "Page text: \"0.002% or ₹200 / crore on buy side\"."),
        "gst_pct": Rate(18.0, "% of brokerage + exchange charge + SEBI fee", _ZERODHA_PAGE, _NO_DATE),
    },
    "options": {
        "stt_sell_pct": Rate(0.15, "% of the sell-side premium", _ZERODHA_PAGE, _NO_DATE,
                             "Page text: \"0.15% on sell side (on premium)\"; also 0.15% of the intrinsic value on options bought "
                             "and exercised (see the expiry convention in the docstring)."),
        "exchange_pct": Rate(0.03553, "% of the premium, each side", _ZERODHA_PAGE, _NO_DATE, "Page text: \"NSE: 0.03553% (on premium)\"."),
        "sebi_per_crore_rs": Rate(10.0, "₹ per crore of premium turnover, each side", _ZERODHA_PAGE, _NO_DATE, "Page text: \"₹10 / crore\"."),
        "stamp_buy_pct": Rate(0.003, "% of the buy-side premium", _ZERODHA_PAGE, _NO_DATE, "Page text: \"0.003% or ₹300 / crore on buy side\"."),
        "gst_pct": Rate(18.0, "% of brokerage + exchange charge + SEBI fee", _ZERODHA_PAGE, _NO_DATE),
    },
}
SEGMENTS = tuple(STATUTORY)
COMPONENTS = ("brokerage", "stt", "exchange", "sebi", "stamp", "gst", "slippage")

#: What a trade snapshots (`cost_model`) when it is opened under this card.
SNAPSHOT: Dict[str, Any] = {
    "name": "desk cost card",
    "version": VERSION,
    "slippage_pct_per_side": SLIPPAGE_PCT_PER_SIDE,
    "brokerage_rs_per_side": BROKERAGE_RS_PER_SIDE,
    "statutory": "STT, exchange transaction charge, SEBI fee, stamp duty and GST by segment (equity delivery, futures, options)",
    "brokerage_basis": "a desk assumption of ₹20 per order side, not a broker's tariff",
    "slippage_basis": "0.05% of the traded value per side, also the spread allowance (end-of-day data has no bid or ask)",
    "excludes": ["DP charges", "IPFT and clearing charges", "income tax on gains"],
    "source": "services/desk_cost_card.py",
}


def is_card(model: Optional[Dict[str, Any]]) -> bool:
    """True when a cost-model snapshot is this card; anything else (desk-flat-v1, or no version) is the flat model."""
    return bool(model) and model.get("version") == VERSION


def paisa(x: float) -> float:
    """Round to the paisa, half up on the decimal value (as a contract note does)."""
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def order_side(segment: str, side: str, value: float, model: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """The charges on one order side of `value` rupees (premium for options): {brokerage, stt, exchange, sebi, stamp,
    gst, slippage, total}. `side` is "BUY" or "SELL"; `model` overrides the slippage % and brokerage (a snapshot)."""
    if segment not in STATUTORY:
        raise ValueError(f"unknown segment {segment!r}")
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, not {side!r}")
    model = model or SNAPSHOT
    r = STATUTORY[segment]
    v = max(float(value), 0.0)
    brokerage = paisa(float(model.get("brokerage_rs_per_side", BROKERAGE_RS_PER_SIDE)))
    stt_key = "stt_buy_pct" if side == "BUY" else "stt_sell_pct"           # F&O: no STT on the buy side
    stt = paisa(v * r[stt_key].value / 100.0) if stt_key in r else 0.0
    exchange = paisa(v * r["exchange_pct"].value / 100.0)
    sebi = paisa(v * r["sebi_per_crore_rs"].value / 1e7)
    stamp = paisa(v * r["stamp_buy_pct"].value / 100.0) if side == "BUY" else 0.0
    gst = paisa((brokerage + exchange + sebi) * r["gst_pct"].value / 100.0)
    slippage = paisa(v * float(model.get("slippage_pct_per_side", SLIPPAGE_PCT_PER_SIDE)) / 100.0)
    out = {"brokerage": brokerage, "stt": stt, "exchange": exchange, "sebi": sebi, "stamp": stamp, "gst": gst, "slippage": slippage}
    out["total"] = paisa(sum(out.values()))
    return out


def add(*sides: Dict[str, float]) -> Dict[str, float]:
    """Component-wise sum of order sides (or of earlier sums), totals included."""
    out = {k: paisa(sum(s.get(k, 0.0) for s in sides)) for k in COMPONENTS}
    out["total"] = paisa(sum(s["total"] for s in sides))
    return out


def round_trip(segment: str, units: float, entry_price: float, exit_price: float, *, long: bool = True,
               model: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, float]]:
    """{entry, exit, total}: the entry side (a buy for a long, a sale for a short), the exit side (the opposite), and their
    component-wise sum. `units` is the quantity in shares or contract units (lots x lot size)."""
    entry = order_side(segment, "BUY" if long else "SELL", entry_price * units, model)
    exit_ = order_side(segment, "SELL" if long else "BUY", exit_price * units, model)
    return {"entry": entry, "exit": exit_, "total": add(entry, exit_)}


def max_lots_within(budget: float, risk_per_unit: float, lot_units: int, cost_at_stop: Callable[[int], float]) -> int:
    """The most whole lots n with n x lot_units x risk_per_unit + cost_at_stop(n x lot_units) <= budget, for a cost that
    never falls as the quantity grows. Exact against the pricing function (a binary search, no linear shortcut), so the
    loss at the stop after costs never exceeds the budget because of a rounding the sizing did not see. 0 when none fits."""
    if budget <= 0 or risk_per_unit <= 0 or lot_units < 1:
        return 0

    def fits(n: int) -> bool:
        units = n * lot_units
        return n == 0 or units * risk_per_unit + cost_at_stop(units) <= budget + 1e-9

    hi = max(0, math.floor(budget / (risk_per_unit * lot_units)))    # costs are never negative
    lo = 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo
