"""Unit tests for the snapshot builder — preflight logic + carry-forward
dataclass behavior. The actual SQL-driven build is integration-tested
against a live PG (out of scope for parser-test layer)."""
from __future__ import annotations

from datetime import date

import pytest

from nidp.services.snapshot_builder.market_builder import CarryForward, _lag
from nidp.services.snapshot_builder.preconditions import PreflightResult


def test_lag_zero_when_actual_equals_target():
    assert _lag(date(2026, 5, 4), date(2026, 5, 4)) == 0


def test_lag_positive_when_actual_before_target():
    assert _lag(date(2026, 5, 4), date(2026, 5, 1)) == 3


def test_lag_zero_when_actual_none():
    assert _lag(date(2026, 5, 4), None) == 0


def test_carry_forward_dataclass_round_trip():
    cf = CarryForward("fii_dii_flows[FII cash]", date(2026, 5, 1), 3)
    assert cf.domain == "fii_dii_flows[FII cash]"
    assert cf.lag_days == 3


def test_preflight_default_is_ok():
    p = PreflightResult(ok=True)
    assert p.ok
    assert p.reasons == []


def test_preflight_add_flips_ok_and_appends_reason():
    p = PreflightResult(ok=True)
    p.add("hard-required prices_eod missing")
    assert not p.ok
    assert p.reasons == ["hard-required prices_eod missing"]


def test_preflight_multiple_reasons_accumulate():
    p = PreflightResult(ok=True)
    p.add("a")
    p.add("b")
    assert p.reasons == ["a", "b"]
    assert not p.ok
