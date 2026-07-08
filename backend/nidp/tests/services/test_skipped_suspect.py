"""WORK-0138: trading-day-aware SUSPECT classification of empty/0-row SKIPs."""
from __future__ import annotations

from datetime import date, timedelta

from nidp.shared.trading_day import is_trading_day
from nidp.shared.ingester_base import _empty_skip_class


def _a_weekday() -> date:
    d = date(2026, 7, 6)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _a_weekend() -> date:
    d = date(2026, 7, 6)
    while d.weekday() < 5:
        d += timedelta(days=1)
    return d


def test_is_trading_day_matches_weekday():
    for i in range(10):
        d = date(2026, 7, 6) + timedelta(days=i)
        assert is_trading_day(d) == (d.weekday() < 5)


def test_is_trading_day_holiday_excluded():
    wd = _a_weekday()
    assert is_trading_day(wd) is True
    assert is_trading_day(wd, holidays={wd}) is False


def test_empty_skip_class_trading_day_is_suspect():
    assert _empty_skip_class(_a_weekday()) == "SUSPECT_EMPTY"


def test_empty_skip_class_weekend_is_benign():
    assert _empty_skip_class(_a_weekend()) is None


def test_empty_skip_class_no_date_is_benign():
    assert _empty_skip_class(None) is None
