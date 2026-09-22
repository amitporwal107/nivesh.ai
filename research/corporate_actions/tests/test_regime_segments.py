"""Synthetic-only: regime_segments splits a bar frame into pre/post regimes at each
confirmed demerger's ex_date -- no event (1 segment), one event (2 segments), multiple
events for the same symbol (N+1 segments), and "segments reconstitute the original frame
exactly" (no row duplicated or dropped).
"""
from datetime import date, timedelta

import pandas as pd

from research.corporate_actions.events import DemergerEvent
from research.corporate_actions.regime import regime_segments

BASE = date(2024, 1, 1)


def _event(symbol: str, ex_date: date) -> DemergerEvent:
    return DemergerEvent(
        symbol=symbol, ex_date=ex_date, date_type="EX_DATE", record_date=ex_date,
        category="DEMERGER", resulting_entity="", resulting_symbol="",
        source="TEST", source_reference="TEST", retrieved_at="2026-01-01T00:00:00Z",
        verified=True, gap_pct_kite=None, review_reason="",
    )


def _bars(n: int, start: date = BASE) -> pd.DataFrame:
    dates = [start + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": range(100, 100 + n), "high": range(101, 101 + n),
        "low": range(99, 99 + n), "close": range(100, 100 + n), "volume": [1000] * n,
    })


def test_no_events_returns_a_single_segment_equal_to_the_input():
    bars = _bars(20)
    segments = regime_segments("NOEVENTS", bars, events=[])
    assert len(segments) == 1
    pd.testing.assert_frame_equal(segments[0], bars.reset_index(drop=True))


def test_one_event_splits_into_exactly_two_segments_at_ex_date():
    bars = _bars(20)
    ex_date = (BASE + timedelta(days=10))
    ev = _event("SPLIT1", ex_date)
    segments = regime_segments("SPLIT1", bars, events=[ev])
    assert len(segments) == 2
    pre, post = segments
    assert (pre["date"] < pd.Timestamp(ex_date)).all()
    assert (post["date"] >= pd.Timestamp(ex_date)).all()
    assert len(pre) == 10  # days 0..9
    assert len(post) == 10  # days 10..19


def test_multiple_events_for_one_symbol_produce_n_plus_1_segments_in_order():
    bars = _bars(40)
    ev1 = _event("MULTI", BASE + timedelta(days=10))
    ev2 = _event("MULTI", BASE + timedelta(days=25))
    segments = regime_segments("MULTI", bars, events=[ev1, ev2])
    assert len(segments) == 3
    seg0, seg1, seg2 = segments
    assert (seg0["date"] < pd.Timestamp(BASE + timedelta(days=10))).all()
    assert (seg1["date"] >= pd.Timestamp(BASE + timedelta(days=10))).all()
    assert (seg1["date"] < pd.Timestamp(BASE + timedelta(days=25))).all()
    assert (seg2["date"] >= pd.Timestamp(BASE + timedelta(days=25))).all()
    assert len(seg0) == 10 and len(seg1) == 15 and len(seg2) == 15


def test_events_out_of_chronological_order_are_still_applied_correctly():
    # events.events_for_symbol sorts by ex_date -- passing them reversed here must not
    # change the result.
    bars = _bars(40)
    ev1 = _event("REVORDER", BASE + timedelta(days=10))
    ev2 = _event("REVORDER", BASE + timedelta(days=25))
    segments = regime_segments("REVORDER", bars, events=[ev2, ev1])
    assert len(segments) == 3
    assert len(segments[0]) == 10 and len(segments[1]) == 15 and len(segments[2]) == 15


def test_segments_reconstitute_the_original_frame_exactly():
    bars = _bars(30)
    ev1 = _event("RECON", BASE + timedelta(days=7))
    ev2 = _event("RECON", BASE + timedelta(days=19))
    segments = regime_segments("RECON", bars, events=[ev1, ev2])
    reconstituted = pd.concat(segments, ignore_index=True)
    pd.testing.assert_frame_equal(reconstituted, bars.reset_index(drop=True))


def test_a_different_symbol_with_no_events_is_unaffected_by_another_symbols_event():
    bars = _bars(20)
    ev = _event("OTHERSYM", BASE + timedelta(days=10))
    segments = regime_segments("THISSYM", bars, events=[ev])
    assert len(segments) == 1
    pd.testing.assert_frame_equal(segments[0], bars.reset_index(drop=True))
