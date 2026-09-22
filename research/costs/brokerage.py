"""Generic brokerage computation: pure functions of a `spec` dict, no broker name in the code.

PRD requirement: brokerage types (percentage, flat, per-order, cap, broker plans, effective dates)
"with no single broker hard-coded". A `spec` is plain data (typically one profile loaded from a
rules/*.json bundled broker plan, or a hand-built dict in a test); this module never branches on a
broker's name -- only on `spec["type"]`.

Supported spec["type"] values:
- "percentage"        : pct * value / 100, optionally capped by spec["cap_inr"].
- "flat"               : spec["flat_inr"] regardless of value (e.g. a subscription/flat-fee plan).
- "per_order"          : same as "flat" (kept as a distinct name because PRD lists it separately --
                          "per order" flat charges and "flat" fee plans are the same arithmetic, but
                          some broker plans express one, some the other, and a caller may want to
                          tell them apart in reporting).
- "percentage_or_flat_min": max(percentage, flat_inr) -- e.g. "0.5% or Rs 20, whichever is HIGHER"
                          full-service plans (as opposed to Zerodha's "whichever is LOWER" style,
                          which is percentage + cap, i.e. type "percentage" with cap_inr set).

The old zerodha-equity-v1 / prd-illustrative-v1 bundled JSON files keep their own legacy
"brokerage_pct" + "brokerage_cap_inr" fields (read directly by engine.py's legacy path, to
reproduce old numbers exactly). This module is the general-purpose path for anything that is not
that legacy reproduction, and is exercised independently in tests/test_brokerage.py against
several distinct plan shapes to prove no broker is hard-coded.
"""
from __future__ import annotations

from decimal import Decimal

_TYPES = ("percentage", "flat", "per_order", "percentage_or_flat_min")


class BrokerageSpecError(ValueError):
    pass


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def compute_brokerage(spec: dict, value: Decimal) -> Decimal:
    """Brokerage for one fill of `value` rupees, per `spec`. Unrounded (paisa-rounding is the
    engine's job, applied uniformly to every cost component)."""
    value = _d(value)
    if value < 0:
        raise BrokerageSpecError(f"negative fill value {value!r}")
    kind = spec.get("type")
    if kind not in _TYPES:
        raise BrokerageSpecError(f"unknown brokerage spec type {kind!r}; expected one of {_TYPES}")
    if kind == "flat" or kind == "per_order":
        return _d(spec["flat_inr"])
    if kind == "percentage":
        pct = _d(spec["pct"])
        amount = value * pct / 100
        cap = spec.get("cap_inr")
        if cap is not None:
            amount = min(amount, _d(cap))
        return amount
    # percentage_or_flat_min
    pct = _d(spec["pct"])
    return max(value * pct / 100, _d(spec["flat_inr"]))
