"""Generic brokerage computation: the same function must handle several distinct plan shapes
(percentage+cap, flat, per-order, percentage-or-flat-minimum) purely from the `spec` dict --
proving brokerage.py has no broker hard-coded into it."""
from decimal import Decimal

import pytest

from research.costs.brokerage import BrokerageSpecError, compute_brokerage


def test_percentage_no_cap():
    spec = {"type": "percentage", "pct": "0.10"}
    assert compute_brokerage(spec, Decimal("100000")) == Decimal("100.000")


def test_percentage_with_cap_zerodha_style():
    spec = {"type": "percentage", "pct": "0.03", "cap_inr": "20"}
    assert compute_brokerage(spec, Decimal("1000")) == Decimal("0.3")   # below cap
    assert compute_brokerage(spec, Decimal("500000")) == Decimal("20")  # capped


def test_flat_fee_plan():
    spec = {"type": "flat", "flat_inr": "0"}
    assert compute_brokerage(spec, Decimal("999999")) == Decimal("0")


def test_per_order_flat_plan():
    spec = {"type": "per_order", "flat_inr": "20"}
    assert compute_brokerage(spec, Decimal("1")) == Decimal("20")
    assert compute_brokerage(spec, Decimal("10000000")) == Decimal("20")  # value-independent


def test_percentage_or_flat_min_full_service_style():
    spec = {"type": "percentage_or_flat_min", "pct": "0.5", "flat_inr": "20"}
    assert compute_brokerage(spec, Decimal("1000")) == Decimal("20")     # 0.5% of 1000 = 5, floor wins
    assert compute_brokerage(spec, Decimal("100000")) == Decimal("500")  # 0.5% of 100000 = 500, pct wins


def test_unknown_type_rejected():
    with pytest.raises(BrokerageSpecError):
        compute_brokerage({"type": "subscription"}, Decimal("1000"))


def test_negative_value_rejected():
    with pytest.raises(BrokerageSpecError):
        compute_brokerage({"type": "flat", "flat_inr": "0"}, Decimal("-1"))
