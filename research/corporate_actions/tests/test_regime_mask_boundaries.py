"""Synthetic-only: regime_break_mask boundary behaviour (T-5, T+5, T+-6), multiple events
per symbol, and a symbol with none. Uses hand-built DemergerEvent objects passed via
`events=` so nothing here touches the stored data/demergers.csv.
"""
from datetime import date, timedelta

import pandas as pd
import pytest

from research.corporate_actions.events import DemergerEvent
from research.corporate_actions.regime import regime_break_mask

BASE = date(2024, 1, 1)


def _event(symbol: str, ex_date: date, category: str = "DEMERGER", verified: bool = True) -> DemergerEvent:
    return DemergerEvent(
        symbol=symbol, ex_date=ex_date, date_type="EX_DATE", record_date=ex_date,
        category=category, resulting_entity="", resulting_symbol="",
        source="TEST", source_reference="TEST", retrieved_at="2026-01-01T00:00:00Z",
        verified=verified, gap_pct_kite=None, review_reason="",
    )


def _session_dates(n: int, start: date = BASE):
    """n consecutive calendar dates -- regime_break_mask counts SESSIONS in the sequence
    given, so consecutive calendar days stand in fine for consecutive trading sessions."""
    return [start + timedelta(days=i) for i in range(n)]


def test_symbol_with_no_events_is_all_false():
    dates = _session_dates(20)
    mask = regime_break_mask("NOEVENTS", dates, events=[])
    assert len(mask) == 20
    assert not mask.any()


def test_window_is_exactly_t_minus_5_to_t_plus_5_inclusive():
    dates = _session_dates(21)  # indices 0..20
    ex_date = dates[10]  # anchor at index 10, exact match
    ev = _event("TESTCO", ex_date)
    mask = regime_break_mask("TESTCO", dates, events=[ev])

    # T-5..T+5 = indices 5..15 inclusive (11 sessions)
    expected_true = set(range(5, 16))
    true_idx = {i for i, v in enumerate(mask) if v}
    assert true_idx == expected_true, (true_idx, expected_true)


def test_t_plus_minus_6_is_excluded_from_the_window():
    dates = _session_dates(21)
    ex_date = dates[10]
    ev = _event("TESTCO", ex_date)
    mask = regime_break_mask("TESTCO", dates, events=[ev])

    assert mask[10 - 5] == True and mask[10 - 6] == False  # T-6 excluded, T-5 included
    assert mask[10 + 5] == True and mask[10 + 6] == False  # T+5 included, T+6 excluded


def test_window_clips_at_the_start_and_end_of_the_series():
    # Event anchored at index 2 -- T-5 would go negative, must clip to index 0.
    dates = _session_dates(10)
    ev = _event("EARLY", dates[2])
    mask = regime_break_mask("EARLY", dates, events=[ev])
    true_idx = {i for i, v in enumerate(mask) if v}
    assert true_idx == set(range(0, 8))  # clipped lower bound, T+5 = index 7

    # Event anchored at the last index -- T+5 must clip to the last index.
    dates2 = _session_dates(10)
    ev2 = _event("LATE", dates2[9])
    mask2 = regime_break_mask("LATE", dates2, events=[ev2])
    true_idx2 = {i for i, v in enumerate(mask2) if v}
    assert true_idx2 == set(range(4, 10))  # T-5 = index 4, clipped upper bound at 9


def test_multiple_events_for_one_symbol_union_their_windows():
    dates = _session_dates(40)
    ev1 = _event("MULTI", dates[10])
    ev2 = _event("MULTI", dates[30])
    mask = regime_break_mask("MULTI", dates, events=[ev1, ev2])
    true_idx = {i for i, v in enumerate(mask) if v}
    assert true_idx == set(range(5, 16)) | set(range(25, 36))


def test_unverified_event_never_causes_a_break():
    dates = _session_dates(21)
    ev = _event("UNCONFIRMED", dates[10], verified=False)
    mask = regime_break_mask("UNCONFIRMED", dates, events=[ev])
    assert not mask.any()


def test_ncrps_bonus_scheme_category_never_causes_a_break():
    dates = _session_dates(21)
    ev = _event("NCRPSCO", dates[10], category="NCRPS_BONUS_SCHEME")
    mask = regime_break_mask("NCRPSCO", dates, events=[ev])
    assert not mask.any()


def test_ex_date_missing_from_bars_anchors_to_the_first_session_on_or_after_it():
    # Symbol was suspended: no bar on ex_date. T0 is the first bar after it (the price reflects the
    # demerger when trading resumes); T-5..T-1 are the five bars before the ex-date.
    dates = [BASE + timedelta(days=i) for i in range(20) if i != 10]  # day 10 missing
    ex_date = BASE + timedelta(days=10)
    mask = regime_break_mask("SUSPENDED", dates, events=[_event("SUSPENDED", ex_date)])
    expected = {pd.Timestamp(BASE + timedelta(days=i)) for i in (5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16)}
    assert {pd.Timestamp(d) for d, v in zip(dates, mask) if v} == expected


def test_an_ex_date_before_the_window_marks_nothing():
    # RELIANCE-like: demerger a year before the window's first bar -- nothing in the window is T..T+5.
    dates = [BASE + timedelta(days=400 + i) for i in range(30)]
    mask = regime_break_mask("OLD", dates, events=[_event("OLD", BASE)])
    assert not mask.any()


def test_a_pre_demerger_regime_marks_exactly_the_five_sessions_before():
    dates = [BASE + timedelta(days=i) for i in range(10)]  # all before the ex-date
    mask = regime_break_mask("PRE", dates, events=[_event("PRE", BASE + timedelta(days=10))])
    assert [d for d, v in zip(dates, mask) if v] == dates[5:]  # T-5..T-1, not six


def test_sessions_are_counted_on_the_full_calendar_when_given():
    full = [BASE + timedelta(days=i) for i in range(40)]
    ex = BASE + timedelta(days=20)
    window = full[23:]  # a window that starts at T+3 of the full history
    mask = regime_break_mask("CAL", window, events=[_event("CAL", ex)], calendar=full)
    # T..T+5 = days 20..25 -> only days 23, 24, 25 are inside the window
    assert [d for d, v in zip(window, mask) if v] == full[23:26]
    # without the calendar the window's own first bar would wrongly be treated as T0
    naive = regime_break_mask("CAL", window, events=[_event("CAL", ex)])
    assert [d for d, v in zip(window, naive) if v] == full[23:29]


def test_duplicate_and_out_of_order_dates_are_each_independently_masked():
    # research.charting.bars preserves duplicates/out-of-order rows verbatim; the mask must
    # handle that: every occurrence of a date gets the same mask value, positional order of
    # the input is preserved in the output. The session calendar is derived from `dates`
    # itself (its own docstring: "using the symbol's own bar dates"), so this test passes
    # the FULL 21-session calendar (with some entries duplicated/reordered at the front) --
    # not a small scrambled subset, which would collapse the calendar down to just those
    # few sessions and change what the window means.
    dates = _session_dates(21)
    ev = _event("DUPES", dates[10])
    messy = [dates[12], dates[10], dates[10]] + dates  # 3 extra, then the full sequence
    mask = regime_break_mask("DUPES", messy, events=[ev])

    assert list(mask[:3]) == [True, True, True]  # dates[12], dates[10], dates[10] dup
    # the appended full 0..20 sequence: window is indices 5..15 inclusive
    expected_tail = [5 <= i <= 15 for i in range(21)]
    assert list(mask[3:]) == expected_tail
