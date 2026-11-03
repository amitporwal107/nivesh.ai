"""Charges for a Quick Hedge, from the desk's own cost card (services/desk_cost_card.py) so a paper hedge costs what any other
paper option trade costs. Entry: each leg on its own order side at its premium. Expiry: a long leg is sold at its
intrinsic value and a short leg is bought back at its intrinsic value (a leg that expires worthless still carries the
exit side's brokerage and GST, the card's conservative convention). Estimates, not contract notes."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def make_charges(model: Optional[Dict[str, Any]] = None) -> Callable[[List[Dict[str, Any]], Optional[float]], float]:
    from services import desk_cost_card as card

    def charges(legs: List[Dict[str, Any]], s_t: Optional[float]) -> float:
        total = 0.0
        for leg in legs:
            long_leg = leg["side"] == "buy"
            if s_t is None:
                side, value = ("BUY" if long_leg else "SELL"), float(leg["premium"]) * leg["qty"]
            else:
                side, value = ("SELL" if long_leg else "BUY"), max(0.0, float(leg["strike"]) - s_t) * leg["qty"]
            total += card.order_side("options", side, value, model)["total"]
        return total

    return charges
