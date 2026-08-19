"""One malformed percentage must not abort a 158k-row holdings upsert.

nidp.mf_holdings_monthly stores weight_pct as numeric(7,4) (|v| < 1000) and
ytm_pct as numeric(8,4) (|v| < 10000). A 2026-07 run wrote 100,000 of 158,868
rows and then died on

    NumericValueOutOfRangeError: numeric field overflow
    DETAIL:  A field with precision 7, scale 4 must round to an absolute
             value less than 10^3.

rolling the remainder back. The holding is still real when only its percentage
is junk, so the value is nulled and reported — never clamped into something
that looks plausible.
"""
from __future__ import annotations

import pytest

from nidp.services.mf_holdings.writer import _drop_overflowing_pcts


def _row(**kw):
    base = {"scheme_code": "100177", "security_name": "ACME LTD",
            "weight_pct": 4.2, "ytm_pct": None}
    base.update(kw)
    return base


def test_sane_weight_is_untouched():
    rows = _drop_overflowing_pcts([_row(weight_pct=4.2)])
    assert rows[0]["weight_pct"] == 4.2


def test_hundred_percent_is_kept():
    """A 100% cash weight is legitimate and must survive."""
    assert _drop_overflowing_pcts([_row(weight_pct=100.0)])[0]["weight_pct"] == 100.0


@pytest.mark.parametrize("bad", [1000.0, 1500.5, -2000.0, 987654.32])
def test_overflowing_weight_is_nulled(bad):
    assert _drop_overflowing_pcts([_row(weight_pct=bad)])[0]["weight_pct"] is None


def test_negative_weight_within_range_is_kept():
    """Short/derivative legs can be negative — only overflow is removed."""
    assert _drop_overflowing_pcts([_row(weight_pct=-12.5)])[0]["weight_pct"] == -12.5


def test_ytm_has_its_own_wider_bound():
    assert _drop_overflowing_pcts([_row(ytm_pct=5000.0)])[0]["ytm_pct"] == 5000.0
    assert _drop_overflowing_pcts([_row(ytm_pct=10000.0)])[0]["ytm_pct"] is None


def test_none_is_left_alone():
    assert _drop_overflowing_pcts([_row(weight_pct=None)])[0]["weight_pct"] is None


def test_unparseable_value_is_nulled_not_raised():
    assert _drop_overflowing_pcts([_row(weight_pct="n/a")])[0]["weight_pct"] is None


def test_only_the_bad_field_is_touched():
    r = _drop_overflowing_pcts([_row(weight_pct=99999.0, ytm_pct=7.1)])[0]
    assert r["weight_pct"] is None
    assert r["ytm_pct"] == 7.1
    assert r["security_name"] == "ACME LTD"


def test_good_rows_survive_alongside_a_bad_one():
    """The whole point: a single bad row must not take the batch down."""
    rows = _drop_overflowing_pcts([
        _row(security_name="GOOD A", weight_pct=1.5),
        _row(security_name="BAD",    weight_pct=123456.0),
        _row(security_name="GOOD B", weight_pct=2.5),
    ])
    assert len(rows) == 3
    assert [r["weight_pct"] for r in rows] == [1.5, None, 2.5]
