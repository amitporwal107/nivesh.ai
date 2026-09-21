"""Tests for research.charting.validate — synthetic frames only, no real data.

Every §9.1 rule_id gets a positive case (it fires) and a negative case (a clean
neighbour that must NOT fire it). Test-plan fixtures #6 (duplicate candle), #7 (missing
candle), #12 (incomplete candle) and #13 (corporate-action discontinuity) are covered
explicitly, in addition to the generic per-rule cases.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting import validate
from research.charting.validate import Finding


def _df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _empty_df() -> pd.DataFrame:
    df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _rule_ids(findings: list[Finding]) -> set[str]:
    return {f.rule_id for f in findings}


def _row(date, o, h, l, c, v):
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v}


# ---------------------------------------------------------------------------
# HIGH_BELOW_BODY
# ---------------------------------------------------------------------------

def test_high_below_body_positive():
    df = _df([_row("2021-01-01", 100, 99, 95, 101, 1000)])  # high < close
    findings = validate.validate_symbol(df)
    assert "HIGH_BELOW_BODY" in _rule_ids(findings)
    f = next(f for f in findings if f.rule_id == "HIGH_BELOW_BODY")
    assert f.date == pd.Timestamp("2021-01-01")
    assert f.observed == 99


def test_high_below_body_negative_normal_candle():
    df = _df([_row("2021-01-01", 100, 105, 95, 101, 1000)])
    findings = validate.validate_symbol(df)
    assert "HIGH_BELOW_BODY" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# LOW_ABOVE_BODY
# ---------------------------------------------------------------------------

def test_low_above_body_positive():
    df = _df([_row("2021-01-01", 100, 110, 101, 105, 1000)])  # low > min(open, close)=100
    findings = validate.validate_symbol(df)
    assert "LOW_ABOVE_BODY" in _rule_ids(findings)
    f = next(f for f in findings if f.rule_id == "LOW_ABOVE_BODY")
    assert f.observed == 101


def test_low_above_body_negative_normal_candle():
    df = _df([_row("2021-01-01", 100, 110, 95, 105, 1000)])
    findings = validate.validate_symbol(df)
    assert "LOW_ABOVE_BODY" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# HIGH_BELOW_LOW
# ---------------------------------------------------------------------------

def test_high_below_low_positive():
    df = _df([_row("2021-01-01", 100, 95, 105, 100, 1000)])  # high < low
    findings = validate.validate_symbol(df)
    assert "HIGH_BELOW_LOW" in _rule_ids(findings)
    f = next(f for f in findings if f.rule_id == "HIGH_BELOW_LOW")
    assert f.observed == 95 and f.detail["low"] == 105


def test_high_below_low_negative_normal_candle():
    df = _df([_row("2021-01-01", 100, 105, 95, 100, 1000)])
    findings = validate.validate_symbol(df)
    assert "HIGH_BELOW_LOW" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# NONPOSITIVE_PRICE
# ---------------------------------------------------------------------------

def test_nonpositive_price_positive_open():
    df = _df([_row("2021-01-01", 0, 10, -1, 5, 1000)])
    findings = validate.validate_symbol(df)
    assert "NONPOSITIVE_PRICE" in _rule_ids(findings)


def test_nonpositive_price_positive_close():
    df = _df([_row("2021-01-01", 10, 12, 8, -5, 1000)])
    findings = validate.validate_symbol(df)
    assert "NONPOSITIVE_PRICE" in _rule_ids(findings)


def test_nonpositive_price_negative_normal_candle():
    df = _df([_row("2021-01-01", 10, 12, 8, 11, 1000)])
    findings = validate.validate_symbol(df)
    assert "NONPOSITIVE_PRICE" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# NEGATIVE_VOLUME
# ---------------------------------------------------------------------------

def test_negative_volume_positive():
    df = _df([_row("2021-01-01", 10, 12, 8, 11, -100)])
    findings = validate.validate_symbol(df)
    assert "NEGATIVE_VOLUME" in _rule_ids(findings)
    f = next(f for f in findings if f.rule_id == "NEGATIVE_VOLUME")
    assert f.observed == -100


def test_negative_volume_negative_zero_is_fine():
    df = _df([_row("2021-01-01", 10, 12, 8, 11, 0)])
    findings = validate.validate_symbol(df)
    assert "NEGATIVE_VOLUME" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# DUPLICATE_TIMESTAMP — test-plan fixture #6
# ---------------------------------------------------------------------------

def test_duplicate_timestamp_positive_fixture_6():
    # "bar15 twice, C104 and C106"
    rows = [_row(f"2021-02-{i:02d}", 100, 102, 98, 100, 1000) for i in range(1, 15)]
    rows.append(_row("2021-02-15", 100, 106, 98, 104, 1000))
    rows.append(_row("2021-02-15", 100, 108, 98, 106, 1000))  # duplicate date
    df = _df(rows)
    findings = validate.validate_symbol(df)
    dup = [f for f in findings if f.rule_id == "DUPLICATE_TIMESTAMP"]
    assert len(dup) == 1
    assert dup[0].date == pd.Timestamp("2021-02-15")
    assert dup[0].observed == 2


def test_duplicate_timestamp_negative_unique_dates():
    rows = [_row(f"2021-02-{i:02d}", 100, 102, 98, 100, 1000) for i in range(1, 16)]
    df = _df(rows)
    findings = validate.validate_symbol(df)
    assert "DUPLICATE_TIMESTAMP" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# OUT_OF_ORDER
# ---------------------------------------------------------------------------

def test_out_of_order_positive():
    df = _df([
        _row("2021-01-04", 100, 102, 98, 100, 1000),
        _row("2021-01-01", 99, 101, 97, 99, 1000),
    ])
    findings = validate.validate_symbol(df)
    assert "OUT_OF_ORDER" in _rule_ids(findings)
    f = next(f for f in findings if f.rule_id == "OUT_OF_ORDER")
    assert f.date == pd.Timestamp("2021-01-01")
    assert f.observed == pd.Timestamp("2021-01-04")


def test_out_of_order_negative_ascending():
    df = _df([
        _row("2021-01-01", 99, 101, 97, 99, 1000),
        _row("2021-01-04", 100, 102, 98, 100, 1000),
    ])
    findings = validate.validate_symbol(df)
    assert "OUT_OF_ORDER" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# MISSING_CANDLE — test-plan fixture #7
# ---------------------------------------------------------------------------

def test_missing_candle_positive_fixture_7():
    # "trading day deleted inside formation window": calendar has 5 sessions, this
    # symbol is missing the middle one.
    full = _df([_row(f"2021-03-0{i}", 100, 102, 98, 100, 1000) for i in [1, 2, 3, 4, 5]])
    with_gap = full.drop(index=2).reset_index(drop=True)  # drops 2021-03-03
    calendar = validate.build_trading_calendar([full])
    findings = validate.validate_symbol(with_gap, calendar=calendar)
    missing = [f for f in findings if f.rule_id == "MISSING_CANDLE"]
    assert len(missing) == 1
    assert missing[0].date == pd.Timestamp("2021-03-03")


def test_missing_candle_negative_no_gap():
    full = _df([_row(f"2021-03-0{i}", 100, 102, 98, 100, 1000) for i in [1, 2, 3, 4, 5]])
    calendar = validate.build_trading_calendar([full])
    findings = validate.validate_symbol(full, calendar=calendar)
    assert "MISSING_CANDLE" not in _rule_ids(findings)


def test_missing_candle_not_evaluated_without_a_calendar():
    full = _df([_row(f"2021-03-0{i}", 100, 102, 98, 100, 1000) for i in [1, 2, 4, 5]])
    findings = validate.validate_symbol(full)  # no calendar passed
    assert "MISSING_CANDLE" not in _rule_ids(findings)


def test_missing_candle_ignores_dates_outside_symbols_own_range():
    # A symbol that starts trading on 03-03 shouldn't get MISSING_CANDLE for 03-01/03-02.
    universe_calendar_source = _df([_row(f"2021-03-0{i}", 100, 102, 98, 100, 1000) for i in [1, 2, 3, 4, 5]])
    late_listing = _df([_row(f"2021-03-0{i}", 100, 102, 98, 100, 1000) for i in [3, 4, 5]])
    calendar = validate.build_trading_calendar([universe_calendar_source])
    findings = validate.validate_symbol(late_listing, calendar=calendar)
    assert "MISSING_CANDLE" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# CORPORATE_ACTION_DISCONTINUITY — test-plan fixture #13
# ---------------------------------------------------------------------------

def test_corporate_action_discontinuity_positive_fixture_13():
    # "bars1-14 ~200-220 unadjusted, bar15+ ~100-110 (1:2 split)"
    rows = [_row(f"2021-04-{i:02d}", 200 + i, 205 + i, 198 + i, 202 + i, 1000) for i in range(1, 15)]
    rows.append(_row("2021-04-15", 108, 112, 105, 110, 1000))  # ~half of bar14's close (216)
    df = _df(rows)
    findings = validate.validate_symbol(df)
    ca = [f for f in findings if f.rule_id == "CORPORATE_ACTION_DISCONTINUITY"]
    assert len(ca) == 1
    assert ca[0].date == pd.Timestamp("2021-04-15")
    assert abs(ca[0].observed - 0.5) < 0.05
    assert ca[0].detail["matched_ratio"] == 0.5


def test_corporate_action_discontinuity_negative_normal_gap_control():
    # A normal ~8% gap down must NOT be flagged as a corporate action (test-plan: "a
    # normal gap must NOT be flagged as a corporate action").
    rows = [_row(f"2021-04-{i:02d}", 200 + i, 205 + i, 198 + i, 202 + i, 1000) for i in range(1, 15)]
    last_close = 202 + 14
    rows.append(_row("2021-04-15", round(last_close * 0.92, 2), round(last_close * 0.94, 2),
                      round(last_close * 0.90, 2), round(last_close * 0.93, 2), 1000))
    df = _df(rows)
    findings = validate.validate_symbol(df)
    assert "CORPORATE_ACTION_DISCONTINUITY" not in _rule_ids(findings)


def test_corporate_action_discontinuity_negative_near_ratio_but_within_normal_range():
    # A ratio close to 1.0 must never match, regardless of how it compares to the CA
    # ratio list (sanity: 0.95 is nowhere near any of 0.5/0.333/0.667/0.2/0.1).
    df = _df([
        _row("2021-04-01", 100, 102, 98, 100, 1000),
        _row("2021-04-02", 95, 97, 93, 95, 1000),
    ])
    findings = validate.validate_symbol(df)
    assert "CORPORATE_ACTION_DISCONTINUITY" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# INCOMPLETE_CANDLE — test-plan fixture #12
# ---------------------------------------------------------------------------

def test_incomplete_candle_positive_fixture_12():
    rows = [_row(f"2021-05-{i:02d}", 100, 102, 98, 100, 1000) for i in range(1, 20)]
    df = _df(rows)
    df["is_complete"] = True
    incomplete_row = _row("2021-05-20", 108, 111, 107, 110.6, 1000)
    incomplete_row["is_complete"] = False
    df = pd.concat([df, pd.DataFrame([incomplete_row])], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])

    findings = validate.validate_symbol(df)
    incomplete = [f for f in findings if f.rule_id == "INCOMPLETE_CANDLE"]
    assert len(incomplete) == 1
    assert incomplete[0].date == pd.Timestamp("2021-05-20")

    # Idempotent: re-running against the same (unmodified) frame gives the same result.
    findings_again = validate.validate_symbol(df)
    assert findings_again == findings


def test_incomplete_candle_negative_when_column_absent():
    df = _df([_row("2021-05-01", 100, 102, 98, 100, 1000)])
    findings = validate.validate_symbol(df)
    assert "INCOMPLETE_CANDLE" not in _rule_ids(findings)


def test_incomplete_candle_negative_when_flag_is_true():
    df = _df([_row("2021-05-01", 100, 102, 98, 100, 1000)])
    df["is_complete"] = True
    findings = validate.validate_symbol(df)
    assert "INCOMPLETE_CANDLE" not in _rule_ids(findings)


# ---------------------------------------------------------------------------
# build_trading_calendar
# ---------------------------------------------------------------------------

def test_build_trading_calendar_is_union_across_frames():
    df1 = _df([_row("2021-01-01", 1, 1, 1, 1, 1)])
    df2 = _df([_row("2021-01-04", 1, 1, 1, 1, 1), _row("2021-01-01", 1, 1, 1, 1, 1)])
    calendar = validate.build_trading_calendar([df1, df2])
    assert calendar == frozenset(pd.to_datetime(["2021-01-01", "2021-01-04"]))


def test_build_trading_calendar_ignores_empty_frames():
    calendar = validate.build_trading_calendar([_empty_df(), _df([_row("2021-01-01", 1, 1, 1, 1, 1)])])
    assert calendar == frozenset(pd.to_datetime(["2021-01-01"]))


# ---------------------------------------------------------------------------
# data_quality_status / pit_status (spec gap G-14) — orthogonality
# ---------------------------------------------------------------------------

def test_symbol_status_valid_and_pit_unverified_by_default():
    df = _df([_row(f"2021-06-{i:02d}", 100, 102, 98, 100, 1000) for i in range(1, 6)])
    findings = validate.validate_symbol(df)
    status = validate.symbol_status(df, findings)
    assert status.data_quality_status == "VALID"
    assert status.pit_status == "PIT_UNVERIFIED"


def test_symbol_status_invalid_on_hard_finding():
    # A minority of rows broken (1 of 10) -> INVALID, not BLOCKED (that threshold is
    # tested separately below with a majority broken).
    rows = [_row(f"2021-06-{i:02d}", 100, 102, 98, 100, 1000) for i in range(1, 10)]
    rows.append(_row("2021-06-10", 100, 99, 95, 101, 1000))  # HIGH_BELOW_BODY
    df = _df(rows)
    findings = validate.validate_symbol(df)
    status = validate.symbol_status(df, findings)
    assert status.data_quality_status == "INVALID"


def test_symbol_status_blocked_when_no_rows():
    df = _empty_df()
    findings = validate.validate_symbol(df)
    status = validate.symbol_status(df, findings)
    assert status.data_quality_status == "BLOCKED"


def test_symbol_status_blocked_when_hard_findings_dominate():
    # Every row broken -> BLOCKED, not merely INVALID.
    df = _df([
        _row("2021-06-01", 100, 90, 95, 101, 1000),  # HIGH_BELOW_BODY and HIGH_BELOW_LOW
        _row("2021-06-02", 100, 90, 95, 101, 1000),
    ])
    findings = validate.validate_symbol(df)
    status = validate.symbol_status(df, findings, blocked_row_fraction=0.5)
    assert status.data_quality_status == "BLOCKED"


def test_symbol_status_stale_when_as_of_far_after_last_date():
    df = _df([_row("2021-01-01", 100, 102, 98, 100, 1000)])
    findings = validate.validate_symbol(df)
    status = validate.symbol_status(df, findings, as_of=pd.Timestamp("2021-06-01"), stale_after_days=10)
    assert status.data_quality_status == "STALE"


def test_symbol_status_not_stale_without_as_of():
    df = _df([_row("2021-01-01", 100, 102, 98, 100, 1000)])
    findings = validate.validate_symbol(df)
    status = validate.symbol_status(df, findings)  # as_of not supplied: no hidden "today"
    assert status.data_quality_status == "VALID"


def test_symbol_status_partial_when_missing_candle_present():
    full = _df([_row(f"2021-03-0{i}", 100, 102, 98, 100, 1000) for i in [1, 2, 3, 4, 5]])
    with_gap = full.drop(index=2).reset_index(drop=True)
    calendar = validate.build_trading_calendar([full])
    findings = validate.validate_symbol(with_gap, calendar=calendar)
    status = validate.symbol_status(with_gap, findings)
    assert status.data_quality_status == "PARTIAL"


def test_data_quality_and_pit_status_vary_independently():
    # spec gap G-14: the two fields are orthogonal. Same OHLCV (VALID either way); only
    # pit_status should move when adjustment_verified changes.
    df = _df([_row("2021-06-01", 100, 102, 98, 100, 1000)])
    findings = validate.validate_symbol(df)

    unverified = validate.symbol_status(df, findings)
    assert unverified.data_quality_status == "VALID"
    assert unverified.pit_status == "PIT_UNVERIFIED"

    verified = validate.symbol_status(df, findings, adjustment_verified=True)
    assert verified.data_quality_status == "VALID"  # unchanged
    assert verified.pit_status == "PIT_VALIDATED"  # changed independently

    blocked_pit = validate.symbol_status(df, findings, adjustment_verified=False)
    assert blocked_pit.data_quality_status == "VALID"  # still unchanged
    assert blocked_pit.pit_status == "PIT_BLOCKED"


# ---------------------------------------------------------------------------
# Tracker T11 — check_known_corporate_action
# ---------------------------------------------------------------------------

def test_check_known_corporate_action_looks_unadjusted_on_a_real_jump():
    rows = [_row(f"2021-01-{i:02d}", 200 + i, 205 + i, 195 + i, 200 + i, 1000) for i in range(1, 6)]
    rows.append(_row("2021-01-06", 102, 106, 100, 103, 1000))  # ~half of bar5's close (205)
    df = _df(rows)
    result = validate.check_known_corporate_action("TEST", df, event_date="2021-01-06")
    assert result.verdict == "LOOKS_UNADJUSTED"
    assert result.ratio_at_event is not None
    assert abs(result.ratio_at_event - 0.5) < 0.05
    assert len(result.before) > 0 and len(result.after) > 0


def test_check_known_corporate_action_looks_adjusted_when_no_jump():
    rows = [_row(f"2021-01-{i:02d}", 200 + i, 205 + i, 195 + i, 200 + i, 1000) for i in range(1, 7)]
    df = _df(rows)
    result = validate.check_known_corporate_action("TEST", df, event_date="2021-01-06")
    assert result.verdict == "LOOKS_ADJUSTED"


def test_check_known_corporate_action_inconclusive_when_event_outside_frame():
    df = _df([_row("2021-01-01", 100, 101, 99, 100.5, 1000)])
    result = validate.check_known_corporate_action("TEST", df, event_date="2025-01-01")
    assert result.verdict == "INCONCLUSIVE"
    assert result.before == [] and result.after == []
