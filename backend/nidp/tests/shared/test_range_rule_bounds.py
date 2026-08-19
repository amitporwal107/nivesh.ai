"""RangeRule bounds must mean what the caller wrote.

`lo`/`hi` arrive as Python floats. Binding a float into a numeric
comparison expands its full binary value, so 0.0001 reaches Postgres as

    0.000100000000000000004792173602385929598312941379845142364501953125

which is strictly greater than the 0.0001 a numeric(14,4) column stores.
A value sitting exactly on an inclusive bound then reads as outside it —
amfi_nav reported "1 row(s) outside [0.0001, 5000000.0] for nav" for a
NAV of exactly 0.0001, on a run that was otherwise clean, and that single
ERROR finding was enough to hold the run at PARTIAL.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from nidp.shared.validation.rules import RangeRule


def _rule(lo=0.0001, hi=5_000_000.0):
    return RangeRule(name="t.range", table="t", column="nav", lo=lo, hi=hi)


def test_bounds_are_stored_as_exact_decimals():
    r = _rule()
    assert isinstance(r._lo, Decimal)
    assert isinstance(r._hi, Decimal)


def test_lower_bound_is_the_decimal_the_caller_wrote():
    """The bug: the bound was 0.00010000000000000000479… not 0.0001."""
    assert _rule()._lo == Decimal("0.0001")


def test_upper_bound_is_the_decimal_the_caller_wrote():
    assert _rule()._hi == Decimal("5000000.0")


def test_value_exactly_on_the_lower_bound_is_inside_the_range():
    """The amfi_nav case: nav == lo must not be flagged."""
    nav = Decimal("0.0001")
    r = _rule()
    assert not (nav < r._lo or nav > r._hi)


def test_value_exactly_on_the_upper_bound_is_inside_the_range():
    nav = Decimal("5000000.0")
    r = _rule()
    assert not (nav < r._lo or nav > r._hi)


def test_naive_float_binding_would_have_failed():
    """Pin why the fix is needed, so nobody 'simplifies' it back."""
    assert Decimal("0.0001") < Decimal(0.0001)   # full binary expansion
    assert not (Decimal("0.0001") < Decimal(repr(0.0001)))


@pytest.mark.parametrize("nav,inside", [
    ("0.00009", False),
    ("0.0001", True),
    ("0.0002", True),
    ("5000000.0", True),
    ("5000000.0001", False),
])
def test_range_edges(nav, inside):
    r = _rule()
    v = Decimal(nav)
    assert (not (v < r._lo or v > r._hi)) is inside
