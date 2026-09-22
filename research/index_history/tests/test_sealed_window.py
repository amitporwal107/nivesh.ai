"""Synthetic-only: the sealed out-of-sample window (2023-01-01..2024-07-31 inclusive)
must be rejected wherever we're about to store a row dated inside it."""
from datetime import date

import pytest

from research.index_history.manifest import (
    SEALED_END, SEALED_START, SEALED_WINDOW, assert_no_sealed_dates, is_sealed,
)


def test_sealed_window_constants():
    assert SEALED_START == date(2023, 1, 1)
    assert SEALED_END == date(2024, 7, 31)
    assert SEALED_WINDOW == ("2023-01-01", "2024-07-31")


@pytest.mark.parametrize("d", ["2023-01-01", "2024-07-31", "2023-06-15", date(2023, 12, 25)])
def test_is_sealed_true_inside_window_inclusive(d):
    assert is_sealed(d) is True


@pytest.mark.parametrize("d", ["2022-12-31", "2024-08-01", "2019-07-01", date(2026, 9, 22)])
def test_is_sealed_false_outside_window(d):
    assert is_sealed(d) is False


def test_assert_no_sealed_dates_passes_on_clean_series():
    dates = ["2022-12-30", "2022-12-31", "2024-08-01", "2024-08-02"]
    assert_no_sealed_dates(dates)  # must not raise


def test_assert_no_sealed_dates_rejects_a_row_in_the_window():
    dates = ["2022-12-31", "2023-01-01", "2024-08-01"]  # one offending row
    with pytest.raises(ValueError, match="sealed out-of-sample date"):
        assert_no_sealed_dates(dates)


def test_assert_no_sealed_dates_rejects_the_last_day_of_the_window_too():
    with pytest.raises(ValueError):
        assert_no_sealed_dates(["2024-07-31"])


def test_assert_no_sealed_dates_accepts_datetime_with_time_and_tz_suffix():
    # e.g. phase1-style "YYYY-MM-DD HH:MM:SS+05:30" strings
    assert_no_sealed_dates(["2024-08-01 00:00:00+05:30"])
    with pytest.raises(ValueError):
        assert_no_sealed_dates(["2023-05-01 00:00:00+05:30"])
