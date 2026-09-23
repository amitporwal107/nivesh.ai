"""research/charting/resample.py — PRD docs/charting.md §38.7 ("Weekly and monthly (P0, display
only)"), §38.12 row W2, §38.13 acceptance criterion 7. TC-120..TC-128 in
test_reports/charting_w2_weekly_monthly.md.

Every "independent" comparison in this file uses a PURE-PYTHON row-by-row accumulator (no pandas
groupby/resample machinery at all) so it genuinely cross-checks resample.py's pandas-based
implementation with separately written code, not the same code called twice.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from research.charting import bars, resample


# ---------------------------------------------------------------------------
# Independent (pure-Python, no pandas groupby/resample) reference resampler
# ---------------------------------------------------------------------------

def _independent_resample(df: pd.DataFrame, key_fn) -> list[dict]:
    """`key_fn(date) -> hashable period key`. Row-by-row dict accumulation: open = first row's
    open for that key, high/low = running max/min, close/volume/date = running last/sum. Groups
    are then sorted by their own last-seen date (never by pandas' internal grouping order) so
    this owes nothing to resample.py's own sort/groupby choices."""
    acc: dict = {}
    order: list = []
    for row in df.itertuples(index=False):
        key = key_fn(row.date)
        if key not in acc:
            acc[key] = {"open": row.open, "high": row.high, "low": row.low, "close": row.close,
                        "volume": row.volume, "date": row.date}
            order.append(key)
        else:
            g = acc[key]
            g["high"] = max(g["high"], row.high)
            g["low"] = min(g["low"], row.low)
            g["close"] = row.close
            g["volume"] += row.volume
            g["date"] = row.date
    rows = [acc[k] for k in order]
    rows.sort(key=lambda r: r["date"])
    for i, r in enumerate(rows):
        r["incomplete"] = (i == len(rows) - 1)
    return rows


def _independent_weekly(df: pd.DataFrame) -> list[dict]:
    return _independent_resample(df, lambda d: d.isocalendar()[:2])  # (iso_year, iso_week)


def _independent_monthly(df: pd.DataFrame) -> list[dict]:
    return _independent_resample(df, lambda d: (d.year, d.month))


def _assert_matches_independent(produced: pd.DataFrame, expected_rows: list[dict]) -> None:
    assert len(produced) == len(expected_rows)
    for i, exp in enumerate(expected_rows):
        got = produced.iloc[i]
        assert got["date"] == exp["date"], (i, got["date"], exp["date"])
        assert math.isclose(got["open"], exp["open"], rel_tol=0, abs_tol=1e-9)
        assert math.isclose(got["high"], exp["high"], rel_tol=0, abs_tol=1e-9)
        assert math.isclose(got["low"], exp["low"], rel_tol=0, abs_tol=1e-9)
        assert math.isclose(got["close"], exp["close"], rel_tol=0, abs_tol=1e-9)
        assert got["volume"] == exp["volume"]
        assert bool(got["incomplete"]) == exp["incomplete"]


# ---------------------------------------------------------------------------
# TC-120 / TC-121 — real ADANIENT (the symbol the spec itself cites), weekly + monthly
# ---------------------------------------------------------------------------

def test_tc120_weekly_matches_independent_resample_real_adanient():
    df = bars.load_symbol("ADANIENT")
    assert len(df) == 1417                      # spec's own cited figure
    produced = resample.resample_weekly(df)
    _assert_matches_independent(produced, _independent_weekly(df))


def test_tc121_monthly_matches_independent_resample_real_adanient():
    df = bars.load_symbol("ADANIENT")
    produced = resample.resample_monthly(df)
    _assert_matches_independent(produced, _independent_monthly(df))


# ---------------------------------------------------------------------------
# TC-122 — several more real symbols (spans every real 2021-2026 NSE holiday and every short
# month, e.g. every February, in range)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol", ["RELIANCE", "TCS", "BEL"])
def test_tc122_weekly_and_monthly_match_independent_resample_other_symbols(symbol):
    df = bars.load_symbol(symbol)
    assert len(df) > 0
    _assert_matches_independent(resample.resample_weekly(df), _independent_weekly(df))
    _assert_matches_independent(resample.resample_monthly(df), _independent_monthly(df))


# ---------------------------------------------------------------------------
# TC-123 — bar counts are sane (spec: "ADANIENT's 1,417 daily bars resample to about 299 weekly
# and 69 monthly")
# ---------------------------------------------------------------------------

def test_tc123_adanient_bar_counts_match_the_spec_figures_exactly():
    df = bars.load_symbol("ADANIENT")
    w = resample.resample_weekly(df)
    m = resample.resample_monthly(df)
    assert len(w) == 299
    assert len(m) == 69


# ---------------------------------------------------------------------------
# TC-124 — trailing bar incomplete, earlier bars are not
# ---------------------------------------------------------------------------

def test_tc124_trailing_bar_is_incomplete_and_every_earlier_bar_is_not():
    df = bars.load_symbol("ADANIENT")
    for resampler in (resample.resample_weekly, resample.resample_monthly):
        out = resampler(df)
        assert out["incomplete"].tolist() == [False] * (len(out) - 1) + [True]


# ---------------------------------------------------------------------------
# TC-125 — a real holiday (Republic Day, 26 Jan) is simply absent, hand-checked against the raw
# daily rows
# ---------------------------------------------------------------------------

def test_tc125_real_holiday_is_absent_and_the_weekly_bar_only_aggregates_the_4_real_sessions():
    df = bars.load_symbol("RELIANCE")
    dates = set(df["date"].dt.strftime("%Y-%m-%d"))
    assert "2022-01-26" not in dates            # Republic Day -- a real NSE holiday, not a weekend

    week = df[(df["date"] >= "2022-01-24") & (df["date"] <= "2022-01-28")]
    assert len(week) == 4                        # Mon/Tue/Thu/Fri present, Wed (holiday) absent

    w = resample.resample_weekly(df)
    row = w[(w["date"] >= "2022-01-24") & (w["date"] <= "2022-01-28")].iloc[0]
    assert row["date"] == pd.Timestamp("2022-01-28")           # last REAL session, not calendar Friday-always
    assert row["open"] == week.iloc[0]["open"] == 1179.60
    assert row["close"] == week.iloc[-1]["close"] == 1113.30
    assert row["high"] == week["high"].max() == 1193.80
    assert row["low"] == week["low"].min() == 1098.60
    assert row["volume"] == week["volume"].sum() == 78_498_856


# ---------------------------------------------------------------------------
# TC-126 — a short month (February, real data) aggregates correctly and has fewer underlying
# sessions than a 31-day month
# ---------------------------------------------------------------------------

def test_tc126_short_month_february_hand_checked_against_raw_daily_rows():
    df = bars.load_symbol("RELIANCE")
    feb = df[(df["date"] >= "2024-02-01") & (df["date"] <= "2024-02-29")]
    jan = df[(df["date"] >= "2024-01-01") & (df["date"] <= "2024-01-31")]
    assert len(feb) == 21 and len(jan) == 22 and len(feb) < len(jan)   # 2024 is a leap year

    m = resample.resample_monthly(df)
    row = m[(m["date"] >= "2024-02-01") & (m["date"] <= "2024-02-29")].iloc[0]
    assert row["open"] == feb.iloc[0]["open"]
    assert row["close"] == feb.iloc[-1]["close"]
    assert row["high"] == feb["high"].max()
    assert row["low"] == feb["low"].min()
    assert row["volume"] == feb["volume"].sum()


# ---------------------------------------------------------------------------
# TC-127 — empty input, and non-mutation of the input frame
# ---------------------------------------------------------------------------

def test_tc127_empty_dataframe_returns_empty_correctly_shaped_frame():
    empty = bars.load_symbol("NO_SUCH_SYMBOL_AT_ALL")
    assert empty.empty
    for resampler in (resample.resample_weekly, resample.resample_monthly):
        out = resampler(empty)
        assert out.empty
        assert list(out.columns) == list(resample.RESAMPLED_COLUMNS)


def test_tc127_resample_does_not_mutate_the_input_frame():
    df = bars.load_symbol("ADANIENT")
    before = df.copy(deep=True)
    resample.resample_weekly(df)
    resample.resample_monthly(df)
    pd.testing.assert_frame_equal(df, before)


# ---------------------------------------------------------------------------
# TC-128 — small hand-built fixture: OHLCV aggregation math, a weekly bar spanning a month
# boundary, and a synthetic "holiday" (a skipped business day) simply absent with no placeholder
# ---------------------------------------------------------------------------

def test_tc128_hand_built_fixture_ohlcv_math_and_week_spanning_a_month_boundary():
    # 2024-01-29 (Mon) .. 2024-02-02 (Fri) is ONE ISO week (5) that straddles the Jan/Feb boundary.
    # 2024-02-09 (Fri) is deliberately OMITTED -- a synthetic "holiday": the week 2024-02-05..09
    # must aggregate only the 4 present sessions, with no placeholder row for the missing Friday.
    rows = [
        ("2024-01-29", 100.0, 102.0, 99.0, 101.0, 1000),
        ("2024-01-30", 101.0, 103.0, 100.5, 102.0, 1100),
        ("2024-01-31", 102.0, 104.0, 101.5, 103.0, 1200),
        ("2024-02-01", 103.0, 105.0, 102.5, 104.0, 1300),
        ("2024-02-02", 104.0, 106.0, 103.5, 105.0, 1400),   # end of ISO week 5
        ("2024-02-05", 105.0, 107.0, 104.5, 106.0, 1500),   # ISO week 6 starts
        ("2024-02-06", 106.0, 108.0, 105.5, 107.0, 1600),
        ("2024-02-07", 107.0, 109.0, 106.5, 108.0, 1700),
        ("2024-02-08", 108.0, 110.0, 107.5, 109.0, 1800),
        # 2024-02-09 (Fri) omitted -- synthetic holiday
    ]
    df = pd.DataFrame({
        "date": pd.to_datetime([r[0] for r in rows]),
        "open": [r[1] for r in rows], "high": [r[2] for r in rows],
        "low": [r[3] for r in rows], "close": [r[4] for r in rows],
        "volume": [r[5] for r in rows],
    })

    w = resample.resample_weekly(df)
    assert len(w) == 2
    wk1, wk2 = w.iloc[0], w.iloc[1]
    # Week 1 (Jan29-Feb2): open=Jan29 open, close=Feb2 close, high/low over all 5, vol summed.
    assert wk1["date"] == pd.Timestamp("2024-02-02")
    assert wk1["open"] == 100.0 and wk1["close"] == 105.0
    assert wk1["high"] == 106.0 and wk1["low"] == 99.0
    assert wk1["volume"] == 1000 + 1100 + 1200 + 1300 + 1400
    assert wk1["incomplete"] is False or wk1["incomplete"] == False  # noqa: E712 - not the trailing bar
    # Week 2 (Feb5-8, Feb9 "holiday" simply absent): open=Feb5 open, close=Feb8 close (NOT a
    # placeholder Friday bar), high/low/vol over exactly those 4 real sessions.
    assert wk2["date"] == pd.Timestamp("2024-02-08")
    assert wk2["open"] == 105.0 and wk2["close"] == 109.0
    assert wk2["high"] == 110.0 and wk2["low"] == 104.5
    assert wk2["volume"] == 1500 + 1600 + 1700 + 1800
    assert wk2["incomplete"] == True  # noqa: E712 - the trailing bar

    m = resample.resample_monthly(df)
    assert len(m) == 2
    jan, feb = m.iloc[0], m.iloc[1]
    assert jan["date"] == pd.Timestamp("2024-01-31")
    assert jan["open"] == 100.0 and jan["close"] == 103.0
    assert jan["high"] == 104.0 and jan["low"] == 99.0
    assert jan["volume"] == 1000 + 1100 + 1200
    assert jan["incomplete"] == False  # noqa: E712
    assert feb["date"] == pd.Timestamp("2024-02-08")
    assert feb["open"] == 103.0 and feb["close"] == 109.0
    assert feb["high"] == 110.0 and feb["low"] == 102.5
    assert feb["volume"] == 1300 + 1400 + 1500 + 1600 + 1700 + 1800
    assert feb["incomplete"] == True  # noqa: E712
