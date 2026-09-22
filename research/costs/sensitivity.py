"""PRD cost-sensitivity scenarios: optimistic 0.05% / base 0.15% / conservative 0.30% / stress 0.50%
per-side slippage. Each scenario recomputes the round trip's net-before-tax (Series A) at that
slippage assumption, holding every statutory/brokerage cost fixed -- only the slippage line moves.

This is deliberately independent of, and does not replace, the liquidity-bucket or ATR-based
slippage MODELS in slippage.py: those estimate a plausible slippage from data (ADV, ATR); the four
scenarios here are a fixed-percentage stress ladder used to bound "how much would the answer change
if slippage were worse/better than modelled", per the PRD.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from research.costs.engine import TradeRecord, compute_round_trip
from research.costs.slippage import fixed_pct

SCENARIOS = (
    ("optimistic", Decimal("0.05")),
    ("base", Decimal("0.15")),
    ("conservative", Decimal("0.30")),
    ("stress", Decimal("0.50")),
)


def run_scenarios(*, entry_price: Decimal, exit_price: Decimal, round_trip_kwargs: dict) -> dict:
    """Returns {scenario_name: TradeRecord}, one per (name, per_side_slippage_pct) in SCENARIOS.
    `round_trip_kwargs` are passed to compute_round_trip() unchanged except for the slippage
    fields, which this function derives from each scenario's percentage via slippage.fixed_pct()."""
    out = {}
    for name, pct in SCENARIOS:
        entry_slip = fixed_pct(entry_price, pct)
        exit_slip = fixed_pct(exit_price, pct)
        kwargs = dict(round_trip_kwargs)
        kwargs.update(entry_price=entry_price, exit_price=exit_price,
                      entry_slippage_per_share=entry_slip, exit_slippage_per_share=exit_slip,
                      slippage_model_version=f"fixed_pct_v1[{pct}%,{name}]")
        out[name] = compute_round_trip(**kwargs)
    return out
