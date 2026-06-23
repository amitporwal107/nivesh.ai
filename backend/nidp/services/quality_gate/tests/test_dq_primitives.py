"""
Tests for nidp_dq_primitives — each primitive catches a synthetic bad pattern
AND passes on clean data (the established quality_gate convention).

Run with pytest, or directly:  python test_nidp_dq_primitives.py
"""

from datetime import date
import pandas as pd

from nidp.services.quality_gate.dq_primitives import (
    assert_columns_exist, expect_non_empty, reconcile_executed_suites,
    TradingCalendar, freshness_within_trading_days,
    detect_q4_annual_contamination, fiscal_year,
)


# --- a small NSE-style holiday set for freshness tests ---
HOLIDAYS = {date(2026, 1, 26), date(2026, 3, 25)}  # Republic Day, a sample holiday
CAL = TradingCalendar(HOLIDAYS)


# ===========================================================================
# 1. META-GUARD
# ===========================================================================
def test_columns_exist_catches_misbound_column():
    # the original bug: suite references a column that doesn't exist
    r = assert_columns_exist("nse_financials_quarterly",
                             expected_cols=["symbol", "pat", "eps_typo_col"],
                             actual_cols=["symbol", "pat", "eps"])
    assert not r.success
    assert r.severity == "error"          # must abort, not silently pass
    assert "eps_typo_col" in r.observed["missing"]


def test_columns_exist_passes_when_all_present():
    r = assert_columns_exist("x", ["a", "b"], ["a", "b", "c"])
    assert r.success and r.severity != "error"


def test_non_empty_catches_empty_batch():
    r = expect_non_empty("mf_holdings_monthly", pd.DataFrame())
    assert not r.success and r.severity == "error"


def test_non_empty_passes_with_rows():
    r = expect_non_empty("x", pd.DataFrame({"a": [1, 2]}))
    assert r.success


def test_suite_coverage_catches_skipped_suite():
    r = reconcile_executed_suites(
        expected_assets=["prices_eod", "shareholding_pattern", "mf_holdings_monthly"],
        executed_assets=["prices_eod", "shareholding_pattern"],   # mf suite silently didn't run
    )
    assert not r.success and r.severity == "error"
    assert "mf_holdings_monthly" in r.observed["missing"]


def test_suite_coverage_passes_when_all_ran():
    r = reconcile_executed_suites(["a", "b"], ["a", "b"])
    assert r.success


# ===========================================================================
# 2. CALENDAR-AWARE FRESHNESS
# ===========================================================================
def test_freshness_does_not_false_positive_over_weekend():
    # asof = Monday 2026-01-12; latest data = Friday 2026-01-09. Hard-equality
    # would FAIL; trading-day logic should PASS (Sat/Sun aren't trading days).
    r = freshness_within_trading_days(
        "prices_eod", max_date=date(2026, 1, 9), calendar=CAL,
        max_lag_trading_days=1, asof=date(2026, 1, 12),
    )
    assert r.success, r.message


def test_freshness_does_not_false_positive_over_holiday():
    # 2026-01-26 is a holiday; asof Tue 2026-01-27, latest data Fri 2026-01-23
    # (23rd Fri, 24/25 weekend, 26 holiday) -> still within 1 trading day.
    r = freshness_within_trading_days(
        "prices_eod", max_date=date(2026, 1, 23), calendar=CAL,
        max_lag_trading_days=1, asof=date(2026, 1, 27),
    )
    assert r.success, r.message


def test_freshness_catches_genuine_staleness():
    # data a full week behind on a normal week -> should FAIL
    r = freshness_within_trading_days(
        "prices_eod", max_date=date(2026, 1, 5), calendar=CAL,
        max_lag_trading_days=1, asof=date(2026, 1, 12),
    )
    assert not r.success and r.severity == "fail", r.message


def test_freshness_settlement_lag_shifts_expectation():
    # T+1 feed: today's session lands tomorrow, so latest=prev trading day is OK.
    r = freshness_within_trading_days(
        "fno_bhavcopy", max_date=date(2026, 1, 9), calendar=CAL,
        max_lag_trading_days=0, settlement_lag=1, asof=date(2026, 1, 12),
    )
    assert r.success, r.message


# ===========================================================================
# 3. Q4-ANNUAL CONTAMINATION
# ===========================================================================
def _financials(q4_pat: float) -> pd.DataFrame:
    """HDFCBANK-style frame; q4_pat=130 is clean, q4_pat=460 is the doubled bug."""
    rows = [
        ("HDFCBANK", date(2023, 6, 30),  "q1",     False, 100, 1000),
        ("HDFCBANK", date(2023, 9, 30),  "q2",     False, 110, 1050),
        ("HDFCBANK", date(2023, 12, 31), "q3",     False, 120, 1100),
        ("HDFCBANK", date(2024, 3, 31),  "Q4",     False, q4_pat, 1150),  # note UPPER-case
        ("HDFCBANK", date(2024, 3, 31),  "annual", False, 460, 4300),
    ]
    return pd.DataFrame(rows, columns=[
        "symbol", "period_end", "period_type", "consolidated", "pat", "revenue"])


def test_q4_contamination_catches_doubled_pat():
    bad = _financials(q4_pat=460)  # Q4 carries the full-year PAT
    r = detect_q4_annual_contamination(bad, value_cols=["pat", "revenue"])
    assert not r.success and r.severity == "fail"
    rules = {v["rule"] for v in r.violations}
    assert "A.quarter_equals_annual" in rules   # Q4 == annual
    assert "B.sum_quarters_neq_annual" in rules  # quarters overshoot annual
    # the case-bug (upper-case "Q4") did not hide the contamination
    assert any(v["metric"] == "pat" for v in r.violations)


def test_q4_contamination_passes_on_clean_data():
    clean = _financials(q4_pat=130)  # 100+110+120+130 = 460 == annual
    r = detect_q4_annual_contamination(clean, value_cols=["pat", "revenue"])
    assert r.success, r.message


def test_q4_contamination_skips_balance_sheet_stocks():
    # total_assets must NOT be sum-reconciled; passing it as a value_col is ignored
    df = _financials(q4_pat=130).rename(columns={"revenue": "total_assets"})
    r = detect_q4_annual_contamination(df, value_cols=["pat", "total_assets"])
    assert "total_assets" in r.observed["metrics_skipped"]
    assert "pat" in r.observed["metrics_checked"]


def test_fiscal_year_mapping():
    assert fiscal_year(date(2023, 6, 30)) == 2024   # Q1 FY24
    assert fiscal_year(date(2024, 3, 31)) == 2024   # Q4 / annual FY24
    assert fiscal_year(date(2023, 12, 31)) == 2024  # Q3 FY24


# --- lightweight runner so this works without pytest ---
if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
