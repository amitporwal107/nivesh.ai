"""Liquidity filter: position value / ADV."""
from decimal import Decimal

from research.costs.liquidity import is_liquid, participation_ratio


def test_participation_ratio_basic():
    assert participation_ratio(Decimal("500000"), Decimal("10000000")) == Decimal("0.05")


def test_participation_ratio_zero_adv_is_infinite_not_zero():
    ratio = participation_ratio(Decimal("500000"), Decimal("0"))
    assert ratio.is_infinite()


def test_is_liquid_threshold_boundary():
    # exactly 5% of ADV, threshold 5% -> liquid (boundary inclusive)
    assert is_liquid(Decimal("500000"), Decimal("10000000"), Decimal("5")) is True
    # just over the threshold -> not liquid
    assert is_liquid(Decimal("500001"), Decimal("10000000"), Decimal("5")) is False


def test_is_liquid_false_for_untraded_name():
    assert is_liquid(Decimal("1"), Decimal("0"), Decimal("5")) is False
